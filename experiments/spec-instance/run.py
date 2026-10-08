#!/usr/bin/env python3
"""Run only generic native instance-lease qualification; --record saves evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--record", action="store_true")
    args = parser.parse_args()
    target = ROOT / "target" / "spec-instance"
    target.mkdir(parents=True, exist_ok=True)
    binary = target / "instance-probe"
    source = HERE / "probe.rs"
    command = ["rustc", "--edition=2024", "-D", "warnings", str(source), "-o", str(binary)]
    compiled = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=60)
    transcript = "COMMAND rustc --edition=2024 -D warnings experiments/spec-instance/probe.rs -o target/spec-instance/instance-probe\n"
    transcript += compiled.stdout + compiled.stderr + f"EXIT {compiled.returncode}\n"
    if compiled.returncode:
        print(transcript, end="")
        raise SystemExit(compiled.returncode)
    with tempfile.TemporaryDirectory(prefix="run-", dir=target) as scratch:
        result = subprocess.run([str(binary), str(Path(scratch) / "fixtures")], cwd=ROOT,
                                capture_output=True, text=True, timeout=40)
    transcript += "COMMAND target/spec-instance/instance-probe <fresh-owned-fixture-directory>\n"
    transcript += result.stdout + result.stderr + f"EXIT {result.returncode}\n"
    print(transcript, end="")
    if result.returncode:
        raise SystemExit(result.returncode)
    assert "cases=5 application-acceptance=false" in result.stdout
    if args.record:
        (HERE / "transcript.txt").write_text(transcript)
        evidence = {
            "purpose": "Darwin file-lease feasibility; not Todo or packaged single-instance acceptance",
            "host_profile": "REF-MAC-M3MAX",
            "observed_date_utc": "2026-10-08",
            "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in [source, Path(__file__)]},
            "transcript_sha256": hashlib.sha256(transcript.encode()).hexdigest(),
            "rustc": subprocess.check_output(["rustc", "--version"], text=True).strip(),
            "reproduce": "python3 experiments/spec-instance/run.py",
            "exit_code": result.returncode,
            "simultaneous_children": 8,
            "result": "passed",
            "limits": ["Activation callback is simulated, not window focus", "No application/database implementation", "No different-account access test", "Not the full FR-024 packaged acceptance suite"],
        }
        (HERE / "results.json").write_text(json.dumps(evidence, indent=2) + "\n")


if __name__ == "__main__":
    main()
