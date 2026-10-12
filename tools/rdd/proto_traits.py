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
    from tools.rdd.common import RddError, RddStorageError, Store, read_json, require_source_branch
else:
    from .adapters import CommandResult, RddAdapterError, run_argv
    from .common import RddError, RddStorageError, Store, read_json, require_source_branch


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


def _seal_contract_index(root: Path, candidate: Path) -> dict:
    """Bind derived symbols to local bytes while retaining imported identities."""
    index = read_json(candidate / ".rdd-generated.json")
    source_hashes, dependencies = {}, []
    for source in index["descriptor_sources"]:
        local = _contained(root, root / "contracts" / source)
        if local.is_file():
            source_hashes[local.relative_to(root).as_posix()] = hashlib.sha256(local.read_bytes()).hexdigest()
        else:
            dependencies.append(source)
    index["source_hashes"] = source_hashes
    index["descriptor_dependencies"] = dependencies
    for symbol in index["services"] + index["types"]:
        local = "contracts/" + symbol["descriptor_source"]
        symbol["source"] = local if local in source_hashes else None
    index["binding_sources"] = {path: ["contracts/" + source if "contracts/" + source in source_hashes
        else "descriptor:" + source for source in sources] for path, sources in index["binding_sources"].items()}
    index["support_files"] = sorted(set(index["support_files"]) | {"gen/rust/Cargo.lock"})
    return index


def _boundary_proof(runtime: Path, candidate: Path, index: dict, *, defect: str | None = None,
                    operation: str | None = None) -> tuple[Path, Path]:
    """Disposable independent crates compile concrete providers and callers.

    Every type/signature comes from the generated descriptor index. These
    fixtures provide only Default responses and are never product artifacts.
    """
    provider, consumer = runtime / "provider", runtime / "consumer"
    for directory in (provider, consumer):
        (directory / "src").mkdir(parents=True)
    dependency = json.dumps(str(candidate))
    (provider / "Cargo.toml").write_bytes((
        '[package]\nname = "rdd-proof-provider"\nversion = "0.0.0"\nedition = "2021"\n'
        '[workspace]\n[dependencies]\nprost-types = "=0.14.4"\nrdd-contracts = { path = ' + dependency + ' }\n').encode("utf-8"))
    (consumer / "Cargo.toml").write_bytes((
        '[package]\nname = "rdd-proof-consumer"\nversion = "0.0.0"\nedition = "2021"\n'
        '[workspace]\n[dependencies]\nprost-types = "=0.14.4"\nrdd-contracts = { path = ' + dependency + ' }\n'
        'rdd-proof-provider = { path = ' + json.dumps(str(provider)) + ' }\n').encode("utf-8"))
    providers, callers = [], []
    # Compile descriptor-derived data imports even when no RPC references them.
    # This uses the existing application contract qualification, not a test suite.
    callers.extend(f"pub type ImportedType{number} = {record['rust_type']};"
                   for number, record in enumerate(index["types"]))
    caller_number = 0
    for number, service in enumerate(index["services"]):
        trait = service["rust_trait"]
        providers += [f"pub struct Provider{number};", f"impl {trait} for Provider{number} {{"]
        for method in service["operations"]:
            faulty = method["symbol"] == operation
            request, response = method["rust_input"], method["rust_output"]
            wrong_request = "bool" if faulty and defect == "provider_request" else request
            wrong_response = "()" if faulty and defect == "provider_response" else response
            if faulty and defect == "associated_error":
                providers.append("    type Error = (); ")
                wrong_response = f"Result<{response}, Self::Error>"
                expression = f"Err::<{response}, ()>(())"
            else:
                expression = f"<{wrong_response}>::default()"
            providers.append(f"    fn {method['rust_method']}(&self, _request: {wrong_request}) "
                f"-> impl core::future::Future<Output = {wrong_response}> + Send {{ async {{ {expression} }} }}")
            call_request = "false" if faulty and defect == "consumer_request" else "request"
            callers.append(f"pub fn call_{caller_number}(request: {request}) -> impl core::future::Future<Output = {response}> + Send {{ "
                f"async move {{ let provider = rdd_proof_provider::Provider{number}; "
                f"{trait}::{method['rust_method']}(&provider, {call_request}).await }} }}")
            caller_number += 1
        providers.append("}")
    if defect == "dependency_direction":
        providers.append("use rdd_proof_consumer::call_0;")
    (provider / "src/lib.rs").write_bytes(("\n".join(providers) + "\n").encode("utf-8"))
    (consumer / "src/lib.rs").write_bytes(("\n".join(callers) + "\n").encode("utf-8"))
    return provider, consumer


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
    if write:
        try:
            require_source_branch(root)
            locator_path = root / ".rdd/run.json"
            locator = read_json(locator_path) if locator_path.is_file() else {}
            if locator.get("run_id"):
                state = Store.read(root, locator["run_id"])
                if not state.get("base_branch"):
                    raise RddError("The active run has no recorded authoring baseline; preserve it and start a fresh run.", "environment")
                require_source_branch(root, state["base_branch"])
                if state["status"] != "specification":
                    raise RddError("Generated contracts are writable only during specification; preserve the frozen outputs and start a new specification run.", "environment")
            elif any((root / rel).exists() for rel in (".rdd/spec.lock.json", ".rdd/plan/plan.lock.json", ".rdd/prepared.json")):
                raise RddError("This checkout has frozen artifacts without an active run. Restore its checkpoint or start a new specification run before generating contracts; seed qualification requires an unfrozen checkout.", "environment")
        except RddStorageError:
            raise
        except RddError as error:
            if getattr(error, "rdd_storage_error", None) is not None:
                raise
            raise ContractCheckError(str(error), blocked=True) from error
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
    report_output_bytes = 0
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(_contained(root, runtime_root / "cargo-target"))

    def execute(args: list[str], name: str, *, expected_failure: bool = False) -> CommandResult:
        nonlocal report_output_bytes
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
        log.write_bytes((json.dumps({
            "name": name, "command": args, "exit_code": completed.returncode,
            "expected_failure": expected_failure,
            "stdout": completed.stdout, "stderr": completed.stderr,
            "timed_out": completed.timed_out, "output_truncated": completed.output_truncated,
        }, indent=2) + "\n").encode("utf-8"))
        log_digest = hashlib.sha256(log.read_bytes()).hexdigest()
        report_output_bytes += len(json.dumps({"stdout":completed.stdout,"stderr":completed.stderr},ensure_ascii=False).encode("utf-8"))
        steps.append({
            "name": name, "command": args, "exit_code": completed.returncode,
            "expected_failure": expected_failure,
            "log": log.relative_to(root).as_posix(),
            "sha256": log_digest, "log_digest": log_digest,
            "stdout": completed.stdout, "stderr": completed.stderr,
        })
        if report_output_bytes > 2 * 1024 * 1024:
            raise ContractCheckError("contract proof report exceeds the 2 MiB transferable diagnostic budget", blocked=True)
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

        contract_index = _seal_contract_index(root, candidate)
        proof_root = runtime / "boundary-proof"
        provider, consumer = _boundary_proof(proof_root, candidate, contract_index)
        for directory, label in ((provider, "provider"), (consumer, "consumer")):
            shutil.copyfile(candidate / "Cargo.lock", directory / "Cargo.lock")
            # The generated dependency lock pins all transitive external crates;
            # only disposable workspace/path package entries are resolved here.
            execute([str(cargo), "generate-lockfile", "--offline", "--manifest-path", str(directory / "Cargo.toml")], "proof-lock-" + label)
            cargo_check(directory, "boundary-" + label)
            for number, target in enumerate(dict.fromkeys(targets), start=1):
                cargo_check(directory, f"boundary-{label}-target-{number}", target)
        negative_proofs = []
        for service in contract_index["services"]:
            for method in service["operations"]:
                for defect, code in (("provider_request", "E0053"), ("provider_response", "E0271"),
                                     ("consumer_request", "E0308"), ("associated_error", "E0437")):
                    target_root = runtime / f"negative-boundary-{len(negative_proofs)}"
                    bad_provider, bad_consumer = _boundary_proof(target_root, candidate, contract_index,
                        defect=defect, operation=method["symbol"])
                    selected = bad_consumer if defect == "consumer_request" else bad_provider
                    source_lock = consumer if defect == "consumer_request" else provider
                    shutil.copyfile(source_lock / "Cargo.lock", selected / "Cargo.lock")
                    rejected = cargo_check(selected, f"boundary-negative-{len(negative_proofs)}", expected_failure=True)
                    if rejected.returncode == 0 or code not in rejected.stdout + rejected.stderr:
                        raise ContractCheckError(f"{defect} did not reject {method['symbol']} with {code}")
                    negative_proofs.append({"operation": method["symbol"], "defect": defect, "diagnostic": code})
        bad_provider, _ = _boundary_proof(runtime / "negative-dependency", candidate, contract_index, defect="dependency_direction")
        shutil.copyfile(provider / "Cargo.lock", bad_provider / "Cargo.lock")
        rejected = cargo_check(bad_provider, "boundary-dependency-negative", expected_failure=True)
        if rejected.returncode == 0 or "E0432" not in rejected.stdout + rejected.stderr:
            raise ContractCheckError("reverse provider dependency was not rejected with E0432")

        metadata = {
            "generator": "rdd-proto-codegen/0.1.0", "prost_version": "0.14.4",
            "descriptor_sha256": hashlib.sha256(descriptor.read_bytes()).hexdigest(),
            "files": {p: h for p, h in _files(candidate).items() if p != ".rdd-generated.json"},
            "contract_index": contract_index,
        }
        (candidate / ".rdd-generated.json").write_bytes(
            (json.dumps(metadata, indent=2, sort_keys=True) + "\n").encode("utf-8")
        )
        expected, actual = _files(candidate), _files(output)
        changed = sorted(name for name in expected.keys() | actual.keys() if expected.get(name) != actual.get(name))
        if write:
            _publish(candidate, output, runtime)
        elif changed:
            raise ContractCheckError(
                "generated Rust drift: " + ", ".join(changed[:12])
                + "; regenerate only in the authorized specification operation"
            )
        result = {
            "status": "passed", "scope": "schema_messages_and_local_unary_service_signatures",
            "descriptor_sha256": metadata["descriptor_sha256"],
            "generated_path": "gen/rust", "generated_files": expected,
            "targets": ["host", *dict.fromkeys(targets)],
            "signature_positive": "passed", "signature_negative": "expected_E0050",
            "boundary_provider": "passed", "boundary_consumer": "passed",
            "boundary_negative_proofs": negative_proofs, "dependency_direction_negative": "expected_E0432",
            "qualified_services": [s["symbol"] for s in contract_index["services"]],
            "qualified_operations": [m["symbol"] for s in contract_index["services"] for m in s["operations"]],
            "write": write, "changed_files": changed, "steps": steps,
            "limitations": [
                "Does not prove that application implementations use the generated traits; project architecture and consumer/provider checks are still required.",
                "Does not verify application behavior, packaging, semantic compatibility, or unlisted compilation targets.",
            ],
        }
        report = runtime / "result.json"
        result["report_path"] = report.relative_to(root).as_posix()
        report.write_bytes((json.dumps(result, indent=2) + "\n").encode("utf-8"))
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
    except RddError as error:
        detail = str(error)
        if getattr(error, "rdd_storage_error", None) is not None:
            detail += "; " + str(error.rdd_storage_error)
        print(json.dumps({"status": "blocked", "kind": "environment", "error": detail}))
        return 2
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
