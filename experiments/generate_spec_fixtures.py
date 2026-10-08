#!/usr/bin/env python3
"""Specification fixtures only. No application code or observed performance claims."""
import datetime as dt
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "contracts/fixtures"
TODAY = "2026-10-08"
SEED = "TODO-REQ-r2-D1-20261008"


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def fixture(label):
    tasks = []
    for index in range(10000):
        identity = hashlib.sha256(f"{SEED}:{label}:{index}".encode()).hexdigest()[:32]
        title = f"{label} task {index:05d} " + ("café Straße " if index % 10 == 0 else "ordinary ")
        title = title + "x" * (80 - len(title))
        notes = f"{label} notes {index:05d} literal [a*b?] "
        if index % 10 == 0:
            notes += "cafe\u0301 Σσς "
        if index == 3141:
            notes += "unique-needle-3141 "
        notes += "n" * (256 - len(notes))
        timestamp = (dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(seconds=index // 4)).strftime("%Y-%m-%dT%H:%M:%S.000000000Z")
        completed = index % 5 == 4
        tasks.append(dict(id=identity, title=title, notes=notes,
                          due_date=[None, "2026-10-07", TODAY, "2026-10-09"][index % 4],
                          status="Completed" if completed else "Open",
                          created_at=timestamp, updated_at=timestamp,
                          completed_at=timestamp if completed else None))
    return dict(format="todo-backup", version=1, tasks=tasks)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    inventory = {}
    for label in ("D1", "D2"):
        data = fixture(label)
        raw = encoded(data)
        path = OUT / f"{label}.json"
        path.write_bytes(raw)
        tasks = data["tasks"]
        assert len(tasks) == 10000 and sum(t["status"] == "Open" for t in tasks) == 8000
        assert all(len(t["title"]) == 80 and len(t["notes"]) == 256 for t in tasks)
        ids = lambda seq: [t["id"] for t in seq]
        # Independent fixture construction oracle: known index membership, no application query helper.
        sets = {"all": ids(tasks), "open": ids(tasks[i] for i in range(10000) if i % 5 != 4),
                "completed": ids(tasks[i] for i in range(10000) if i % 5 == 4),
                "no_due": ids(tasks[i] for i in range(0,10000,4)),
                "today": ids(tasks[i] for i in range(2,10000,4)),
                "overdue": ids(tasks[i] for i in range(1,10000,4) if i % 5 != 4),
                "search_zero": [], "search_unique": [tasks[3141]["id"]],
                "search_cafe": ids(tasks[i] for i in range(0,10000,10)),
                "search_literal": ids(tasks)}
        # Timestamp fixtures are canonical UTC fixed width, permitting lexical reference sorting.
        oldest = sorted(tasks, key=lambda t:(t["created_at"],t["id"]))
        newest = sorted(tasks, key=lambda t:t["id"])
        newest.sort(key=lambda t:t["created_at"],reverse=True)
        due = sorted(newest,key=lambda t:(t["due_date"] is None,t["due_date"] or ""))
        oracle = {"sets":sets,"orders":{"oldest":ids(oldest),"newest":ids(newest),"earliest_due":ids(due)}}
        oracle_path = OUT / f"{label}-oracle.json"
        oracle_path.write_bytes(encoded(oracle))
        for p in (path,oracle_path):
            inventory[p.relative_to(ROOT).as_posix()] = {"sha256":hashlib.sha256(p.read_bytes()).hexdigest(),"bytes":p.stat().st_size}
    inventory_path = ROOT / "docs/specs/fixture-inventory.json"
    inventory_path.write_text(json.dumps({"seed":SEED,"today":TODAY,"unicode_version":"16.0.0","files":inventory},indent=2)+"\n")


if __name__ == "__main__":
    main()
