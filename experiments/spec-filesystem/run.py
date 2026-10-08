#!/usr/bin/env python3
"""Compile and execute a disposable native filesystem probe; --record saves evidence."""
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
    target = ROOT / "target" / "spec-filesystem"
    target.mkdir(parents=True, exist_ok=True)
    binary = target / "filesystem-probe"
    source = HERE / "probe.rs"
    compile_command = ["rustc", "--edition=2024", "-D", "warnings", str(source), "-o", str(binary)]
    compile_result = subprocess.run(compile_command, cwd=ROOT, text=True, capture_output=True, timeout=60)
    transcript = "COMMAND rustc --edition=2024 -D warnings experiments/spec-filesystem/probe.rs -o target/spec-filesystem/filesystem-probe\n"
    transcript += compile_result.stdout + compile_result.stderr + f"EXIT {compile_result.returncode}\n"
    if compile_result.returncode:
        print(transcript, end="")
        raise SystemExit(compile_result.returncode)
    with tempfile.TemporaryDirectory(prefix="run-", dir=target) as scratch:
        command = [str(binary), str(Path(scratch) / "fixtures")]
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=60)
    transcript += "COMMAND target/spec-filesystem/filesystem-probe <fresh-owned-fixture-directory>\n"
    transcript += result.stdout + result.stderr + f"EXIT {result.returncode}\n"
    print(transcript, end="")
    if result.returncode:
        raise SystemExit(result.returncode)
    assert "crash-cases=6 production-acceptance=false" in result.stdout
    if args.record:
        (HERE / "transcript.txt").write_text(transcript)
        evidence = {
            "purpose": "Narrow filesystem qualification, not Todo implementation or acceptance",
            "host_profile": "REF-MAC-M3MAX",
            "observed_date_utc": "2026-10-08",
            "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in [source, Path(__file__)]},
            "transcript_sha256": hashlib.sha256(transcript.encode()).hexdigest(),
            "rustc": subprocess.check_output(["rustc", "--version"], text=True).strip(),
            "reproduce": "python3 experiments/spec-filesystem/run.py",
            "exit_code": result.returncode,
            "crash_cut_repeats": 3,
            "crash_cuts": ["before-publication", "after-publication-before-ack"],
            "result": "passed",
            "limits": ["No power-loss guarantee", "No application backup/restore implementation", "No concurrent external-modifier claim", "Not the full application interruption matrix or benchmark", "No external-drive qualification"],
        }
        (HERE / "results.json").write_text(json.dumps(evidence, indent=2) + "\n")


if __name__ == "__main__":
    main()
