#!/usr/bin/env python3
"""Frozen specification proof runner; verifies inputs before executing experiments."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    mode = sys.argv[1] if len(sys.argv) == 2 else ""
    if mode not in {"inputs", "consumer", "filesystem", "instance", "dependencies"}:
        raise SystemExit("expected inputs|consumer|filesystem|instance|dependencies")
    manifest = json.loads((ROOT / "contracts/qualification-inputs.json").read_text())
    for command, expected in manifest["tool_versions"].items():
        observed = subprocess.run([command,"--version"],cwd=ROOT,text=True,capture_output=True,check=True).stdout.strip()
        if observed != expected:
            raise RuntimeError(f"qualification tool drift: {command}: {observed!r}, expected {expected!r}")
    for relative, expected in manifest["files"].items():
        path = ROOT / relative
        if path.is_symlink() or ROOT not in path.resolve().parents:
            raise RuntimeError(f"unsafe qualification input: {relative}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"qualification input drift: {relative}")
    commands = {
        "inputs": [[sys.executable,"experiments/verify_spec_inputs.py"]],
        "consumer": [["cargo","test","--locked","--manifest-path","experiments/contract-consumer/Cargo.toml"],
                     ["cargo","check","--locked","--tests","--manifest-path","experiments/contract-consumer/Cargo.toml","--target","wasm32-unknown-unknown"]],
        "filesystem": [[sys.executable,"experiments/spec-filesystem/run.py"]],
        "instance": [[sys.executable,"experiments/spec-instance/run.py"]],
        "dependencies": [[sys.executable,"experiments/spec-dependencies/recheck.py"]],
    }
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(ROOT / ".rdd/runtime/qualification-target")
    for argv in commands[mode]:
        print(json.dumps({"command":argv,"cwd":".","scope":"specification qualification, not Todo acceptance"}),flush=True)
        subprocess.run(argv,cwd=ROOT,env=env,check=True,timeout=7000)
    print(json.dumps({"status":"passed","mode":mode,"verified_inputs":len(manifest["files"])}))


if __name__ == "__main__":
    main()
