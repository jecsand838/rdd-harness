"""Provision declared CI tools through a fixed installer map, never manifest commands."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import tomllib

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from tools.rdd.adapters import RddAdapterError, run_argv
    from tools.rdd.common import git
else:
    from .adapters import RddAdapterError, run_argv
    from .common import git

PIN = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
CARGO_TOOLS = {"cargo-tauri": "tauri-cli", "trunk": "trunk",
               "wasm-bindgen": "wasm-bindgen-cli", "wasm-pack": "wasm-pack"}
RUNNERS = {"linux": "ubuntu-24.04", "macos": "macos-latest", "windows": "windows-latest"}


def platform_name() -> str:
    return {"darwin": "macos", "win32": "windows"}.get(sys.platform, "linux")


def preparation_matrix(root: Path) -> dict:
    spec = json.loads((root / ".rdd/spec.json").read_text(encoding="utf-8"))
    platforms = {environment["platform"] for environment in spec.get("environments", [])
                 if not environment["host_profile"]}
    if not platforms or platforms - RUNNERS.keys():
        raise ValueError("Preparation needs at least one supported declared hosted environment")
    return {"include": [{"platform": platform, "os": RUNNERS[platform]} for platform in sorted(platforms)]}


def tool_plan(root: Path, platform: str) -> dict:
    spec_path = root / ".rdd/spec.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8")) if spec_path.exists() else {}
    environments = {e["id"] for e in spec.get("environments", [])
                    if e["platform"] == platform and not e["host_profile"]}
    tools = {}
    for resource in spec.get("resources", []):
        if resource["kind"] != "tool" or not environments.intersection(resource["environments"]):
            continue
        name, version = resource["path"], resource["version"]
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
            raise ValueError("CI tools must name a bare executable, not a path or command")
        if not isinstance(version, str) or not PIN.fullmatch(version):
            raise ValueError(f"CI tool {name} needs an exact three-part version")
        if name in tools and tools[name] != version:
            raise ValueError(f"Conflicting CI tool pins for {name}")
        tools[name] = version
    rust = tomllib.loads((root / "rust-toolchain.toml").read_text(encoding="utf-8"))["toolchain"]
    if not PIN.fullmatch(rust["channel"]):
        raise ValueError("CI requires an exact stable Rust version")
    for name in ("rustc", "cargo"):
        if name in tools and tools[name] != rust["channel"]:
            raise ValueError(f"{name} pin conflicts with rust-toolchain.toml")
    for component in rust.get("components", []):
        if component not in {"rustfmt", "clippy", "rust-src"}:
            raise ValueError("Unsupported Rust component")
    for target in rust.get("targets", []):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]+", target):
            raise ValueError("Invalid Rust target")
    python = {tools[name] for name in ("python", "python3") if name in tools}
    if len(python) > 1:
        raise ValueError("Conflicting Python executable pins")
    return {"python": next(iter(python), "3.11.9"), "buf": tools.get("buf", "1.73.0"),
            "rust": rust, "tools": tools}


def provision(root: Path, plan: dict, evidence: Path, candidate: Path | None = None) -> dict:
    evidence.mkdir(parents=True, exist_ok=True)
    candidate = candidate or root
    identities = {"candidate_commit": git(candidate, "rev-parse", "HEAD"),
                  "policy_commit": git(root, "rev-parse", "HEAD"),
                  "verifier_commit": git(Path(__file__).resolve().parents[2], "rev-parse", "HEAD")}
    for name, relative in (("spec", ".rdd/spec.json"), ("plan", ".rdd/plan/plan.json")):
        path = root / relative
        identities[name + "_file_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    commands = []

    def execute(argv: list[str]) -> str:
        number = len(commands) + 1
        result = run_argv(argv, root, timeout=1800,
                          stdout_path=evidence / f"{number:02}-stdout.log",
                          stderr_path=evidence / f"{number:02}-stderr.log",
                          env={"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
        commands.append({"argv": argv, "returncode": result.returncode,
                         "timed_out": result.timed_out,
                         "stdout": f"{number:02}-stdout.log",
                         "stderr": f"{number:02}-stderr.log"})
        (evidence / "commands.json").write_bytes(
            (json.dumps({"identities": identities, "commands": commands}, indent=2) + "\n").encode("utf-8"))
        if result.timed_out or result.returncode:
            raise ValueError(f"Provisioning failed: {argv[0]}; see {evidence}")
        if result.output_truncated:
            raise ValueError(f"Provisioning output exceeded capture budget: {argv[0]}; see {evidence}")
        return result.stdout.strip()

    rust = plan["rust"]
    command = ["rustup", "toolchain", "install", rust["channel"], "--profile", "minimal"]
    for component in rust.get("components", []):
        command.extend(["--component", component])
    for target in rust.get("targets", []):
        command.extend(["--target", target])
    execute(command)
    versions = {}
    tools = {"python": plan["python"], "buf": plan["buf"],
             "rustc": rust["channel"], "cargo": rust["channel"], **plan["tools"]}
    for name, version in sorted(tools.items()):
        if name in CARGO_TOOLS:
            execute(["cargo", f"+{rust['channel']}", "install", "--locked", "--force",
                     "--version", version, CARGO_TOOLS[name]])
        executable = sys.executable if name in {"python", "python3"} else shutil.which(name)
        if not executable:
            raise ValueError(f"Unprovisioned tool {name}: use a supported installer or qualified preinstalled runner")
        output = execute([executable, *([f"+{rust['channel']}"] if name in {"rustc", "cargo"} else []), "--version"])
        measured = re.search(r"(?<![0-9.])([0-9]+\.[0-9]+\.[0-9]+)(?![0-9.]|[-+][A-Za-z0-9])", output)
        if not measured or measured.group(1) != version:
            raise ValueError(f"Measured {name} does not match {version}: {output}")
        versions[name] = output
    receipt = {"scope": "installed_ci_tools", "application_complete": False,
               "platform": platform_name(), "identities": identities, "tools": versions}
    (evidence / "tools.json").write_bytes((json.dumps(receipt, indent=2) + "\n").encode("utf-8"))
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("describe", "provision", "matrix"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--evidence", type=Path,
                        help="New per-attempt directory for provisioning receipts and raw logs")
    parser.add_argument("--candidate-root", type=Path,
                        help="Candidate checkout when tool declarations come from a separate trusted policy")
    args = parser.parse_args()
    if args.action == "matrix":
        value = json.dumps(preparation_matrix(args.root), separators=(",", ":"))
        if args.github_output:
            with args.github_output.open("a", encoding="utf-8", newline="\n") as output:
                output.write("matrix=" + value + "\n")
        print(value)
        return
    plan = tool_plan(args.root, platform_name())
    if args.action == "describe":
        if args.github_output:
            with args.github_output.open("a", encoding="utf-8", newline="\n") as output:
                output.write(f"python={plan['python']}\nbuf={plan['buf']}\n")
        print(json.dumps(plan))
    else:
        if not args.evidence:
            parser.error("provision requires --evidence")
        print(json.dumps(provision(args.root, plan, args.evidence, args.candidate_root)))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, RddAdapterError) as exc:
        raise SystemExit(str(exc)) from exc
