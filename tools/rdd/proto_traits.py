#!/usr/bin/env python3
"""Buf -> prost messages + local service traits -> positive/negative Rust proof.

The normal check never rewrites generated source. The explicit --write mode
publishes a fully checked candidate. First use may require --bootstrap-lock;
the resulting Cargo.lock files must be committed before a specification freezes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any

# Support both controller imports and the documented direct-script command.
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from tools.rdd.adapters import CommandResult, RddAdapterError, run_argv
else:
    from .adapters import CommandResult, RddAdapterError, run_argv


class ContractCheckError(RuntimeError):
    """A failed check, or a missing prerequisite explicitly marked as blocked."""

    def __init__(self, message: str, *, blocked: bool = False):
        super().__init__(message)
        self.blocked = blocked


def _contained(root: Path, path: Path) -> Path:
    """Reject symlink traversal and writes outside this selected repository."""
    try:
        parts = path.relative_to(root).parts
    except ValueError as error:
        raise ContractCheckError(f"path is outside repository: {path}") from error
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ContractCheckError(f"symlink is not allowed for contract outputs: {current}")
    try:
        path.resolve().relative_to(root)
    except ValueError as error:
        raise ContractCheckError(f"resolved path leaves repository: {path}") from error
    return path


def _files(directory: Path) -> dict[str, str]:
    if not directory.exists():
        return {}
    result = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ContractCheckError(f"generated output contains a symlink: {path}")
        if path.is_file():
            result[path.relative_to(directory).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _reject_source_symlinks(directory: Path) -> None:
    if directory.is_symlink():
        raise ContractCheckError(f"contract source directory is a symlink: {directory}")
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise ContractCheckError(f"contract source symlink is not permitted: {path}")


def _publish(candidate: Path, output: Path, runtime: Path) -> None:
    """Swap directories with rollback; never replace an unowned output tree."""
    if output.exists() and not (output / ".rdd-generated.json").is_file():
        if any(output.iterdir()):
            raise ContractCheckError(
                f"refusing to replace non-generated contents in {output}; choose an empty output directory"
            )
    output.parent.mkdir(parents=True, exist_ok=True)
    previous = runtime / "previous-generated"
    had_previous = output.exists()
    if had_previous:
        output.rename(previous)
    try:
        candidate.rename(output)
    except OSError:
        if had_previous:
            previous.rename(output)
        raise
    if had_previous:
        shutil.rmtree(previous)


def run_contracts(
    root: Path,
    *,
    write: bool = False,
    bootstrap_lock: bool = False,
    targets: tuple[str, ...] = (),
    against: str | None = None,
) -> dict[str, Any]:
    """Run complete shape verification; raise ContractCheckError on non-pass.

    Public controller API. `against` is passed as one Buf input argument;
    no shell interpretation is used. Targets supplement the host check.
    """
    root = root.resolve()
    cargo = shutil.which("cargo")
    buf = shutil.which("buf")
    missing = [name for name, found in (("cargo", cargo), ("buf", buf)) if not found]
    if missing:
        raise ContractCheckError(
            "missing contract prerequisites: " + ", ".join(missing)
            + "; install the documented pinned tools and rerun", blocked=True
        )
    if bootstrap_lock and not write:
        raise ContractCheckError("--bootstrap-lock requires --write; a read-only check cannot create locks")
    for target in targets:
        if not target or target.startswith("-") or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in target):
            raise ContractCheckError(f"invalid Rust target: {target!r}")
    manifest = _contained(root, root / "tools/proto-codegen/Cargo.toml")
    output = _contained(root, root / "gen/rust")
    runtime_root = _contained(root, root / ".rdd/runtime")
    config = _contained(root, root / "buf.yaml")
    if not manifest.is_file() or not config.is_file():
        raise ContractCheckError("tools/proto-codegen/Cargo.toml and buf.yaml must exist")
    contracts = _contained(root, root / "contracts")
    if not contracts.is_dir():
        raise ContractCheckError("the contracts source directory must exist")
    _reject_source_symlinks(contracts)
    _reject_source_symlinks(manifest.parent)
    runtime_root.mkdir(parents=True, exist_ok=True)
    lock_path = _contained(root, runtime_root / "proto-codegen.lock")
    try:
        lock_fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise ContractCheckError(
            "another contract check owns .rdd/runtime/proto-codegen.lock; "
            "if the prior process crashed, verify it stopped before removing that lock"
        ) from error
    with os.fdopen(lock_fd, "w", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))

    runtime = Path(tempfile.mkdtemp(prefix="contracts-", dir=runtime_root))
    logs = runtime / "logs"
    logs.mkdir()
    steps: list[dict[str, Any]] = []
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(_contained(root, runtime_root / "cargo-target"))

    def execute(args: list[str], name: str, *, expected_failure: bool = False) -> CommandResult:
        stem = f"{len(steps) + 1:02d}-{name}"
        stdout_log, stderr_log = logs / f"{stem}.stdout", logs / f"{stem}.stderr"
        try:
            completed = run_argv(
                args, cwd=root, env=env, timeout=1200,
                stdout_path=stdout_log, stderr_path=stderr_log,
                max_capture_bytes=4 * 1024 * 1024,
            )
        except (OSError, RddAdapterError) as error:
            raise ContractCheckError(f"{name} could not execute: {error}", blocked=True) from error
        log = logs / f"{stem}.log"
        log.write_text(json.dumps({
            "stdout": completed.stdout, "stderr": completed.stderr,
            "timed_out": completed.timed_out, "output_truncated": completed.output_truncated,
        }, indent=2) + "\n", encoding="utf-8")
        steps.append({
            "name": name, "command": args, "exit_code": completed.returncode,
            "expected_failure": expected_failure,
            "log": log.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
        })
        if completed.timed_out or completed.output_truncated:
            raise ContractCheckError(f"{name} was timed out or exceeded its output budget; see {log.relative_to(root)}", blocked=True)
        if completed.returncode and not expected_failure:
            raise ContractCheckError(f"{name} failed; see {log.relative_to(root)}")
        return completed

    def generate(destination: Path, proof: str | None = None) -> None:
        args = [str(cargo), "run", "--quiet", "--locked", "--manifest-path", str(manifest), "--", str(descriptor), str(destination)]
        if proof:
            args.append(proof)
        execute(args, "generate-" + (proof or "contracts"))

    def cargo_check(directory: Path, name: str, target: str | None = None, *, expected_failure: bool = False) -> CommandResult:
        args = [str(cargo), "check", "--locked", "--manifest-path", str(directory / "Cargo.toml")]
        if target:
            args.extend(["--target", target])
        return execute(args, name, expected_failure=expected_failure)

    try:
        execute([str(buf), "--version"], "buf-version")
        execute([str(cargo), "--version"], "cargo-version")
        execute([str(buf), "lint", "--disable-symlinks"], "buf-lint")
        descriptor = runtime / "schema.bin"
        execute([str(buf), "build", "--disable-symlinks", "--as-file-descriptor-set", "--output", str(descriptor)], "buf-build")
        if against:
            execute([str(buf), "breaking", "--disable-symlinks", "--against", against], "buf-breaking")

        generator_lock = _contained(root, manifest.parent / "Cargo.lock")
        if not generator_lock.exists():
            if not bootstrap_lock:
                raise ContractCheckError(
                    "generator Cargo.lock is missing; run contract generation with --write --bootstrap-lock, "
                    "then commit both Cargo.lock files before freezing specification", blocked=True
                )
            execute([str(cargo), "generate-lockfile", "--manifest-path", str(manifest)], "bootstrap-generator-lock")
        execute([str(cargo), "test", "--quiet", "--locked", "--manifest-path", str(manifest)], "generator-tests")

        candidate = runtime / "candidate"
        generate(candidate)
        old_lock = _contained(root, output / "Cargo.lock")
        if old_lock.is_file():
            shutil.copyfile(old_lock, candidate / "Cargo.lock")
        elif bootstrap_lock:
            execute([str(cargo), "generate-lockfile", "--manifest-path", str(candidate / "Cargo.toml")], "bootstrap-generated-lock")
        else:
            raise ContractCheckError(
                "generated Cargo.lock is missing; first generation requires --write --bootstrap-lock", blocked=True
            )
        cargo_check(candidate, "compile-host")
        for index, target in enumerate(dict.fromkeys(targets), start=1):
            cargo_check(candidate, f"compile-target-{index}", target)

        valid = runtime / "valid-proof"
        generate(valid, "valid")
        shutil.copyfile(candidate / "Cargo.lock", valid / "Cargo.lock")
        cargo_check(valid, "signature-positive")
        invalid = runtime / "invalid-proof"
        generate(invalid, "invalid")
        shutil.copyfile(candidate / "Cargo.lock", invalid / "Cargo.lock")
        negative = cargo_check(invalid, "signature-negative", expected_failure=True)
        if negative.returncode == 0 or "E0050" not in negative.stdout + negative.stderr:
            raise ContractCheckError(
                "signature negative proof did not fail for the deliberately incorrect method parameter count"
            )

        metadata = {
            "generator": "rdd-proto-codegen/0.1.0", "prost_version": "0.14.4",
            "descriptor_sha256": hashlib.sha256(descriptor.read_bytes()).hexdigest(),
            "files": _files(candidate),
        }
        (candidate / ".rdd-generated.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        expected, actual = _files(candidate), _files(output)
        changed = sorted(name for name in expected.keys() | actual.keys() if expected.get(name) != actual.get(name))
        if write:
            _publish(candidate, output, runtime)
        elif changed:
            raise ContractCheckError(
                "generated Rust drift: " + ", ".join(changed[:12])
                + "; regenerate only in the authorized specification/preparation operation"
            )
        result = {
            "status": "passed", "scope": "schema_messages_and_local_unary_service_signatures",
            "descriptor_sha256": metadata["descriptor_sha256"],
            "generated_path": "gen/rust", "generated_files": expected,
            "targets": ["host", *dict.fromkeys(targets)],
            "signature_positive": "passed", "signature_negative": "expected_E0050",
            "write": write, "changed_files": changed, "steps": steps,
            "limitations": [
                "Does not prove that application implementations use the generated traits; project architecture and consumer/provider checks are still required.",
                "Does not verify application behavior, packaging, semantic compatibility, or unlisted compilation targets.",
            ],
        }
        report = runtime / "result.json"
        result["report_path"] = report.relative_to(root).as_posix()
        report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return result
    finally:
        lock_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--write", action="store_true", help="publish checked generated files")
    parser.add_argument("--bootstrap-lock", action="store_true", help="resolve missing Cargo.lock files on first authorized generation")
    parser.add_argument("--target", action="append", default=[], help="also compile this installed Rust target")
    parser.add_argument("--against", help="Buf breaking-check baseline input")
    args = parser.parse_args()
    try:
        result = run_contracts(args.root, write=args.write, bootstrap_lock=args.bootstrap_lock,
                               targets=tuple(args.target), against=args.against)
    except ContractCheckError as error:
        print(json.dumps({"status": "blocked" if error.blocked else "failed", "error": str(error)}))
        return 2 if error.blocked else 1
    except OSError as error:
        print(json.dumps({"status": "blocked", "error": str(error)}))
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
