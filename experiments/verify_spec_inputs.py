#!/usr/bin/env python3
"""Verify frozen qualification inputs and deterministic fixture identities."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
fixtures = json.loads((root / "docs/specs/fixture-inventory.json").read_text())
for rel, record in fixtures["files"].items():
    raw = (root / rel).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == record["sha256"], rel
    assert len(raw) == record["bytes"], rel
for label in ("D1", "D2"):
    data = json.loads((root / f"contracts/fixtures/{label}.json").read_text())
    tasks = data["tasks"]
    assert len(tasks) == 10000
    assert len({task["id"] for task in tasks}) == 10000
    assert sum(task["status"] == "Open" for task in tasks) == 8000
    assert all(len(task["title"]) == 80 and len(task["notes"]) == 256 for task in tasks)
    assert sum(any(ord(c) > 127 for c in task["title"]) for task in tasks) >= 1000
    for status in ("Open", "Completed"):
        counts = [sum(t["status"] == status and t["due_date"] == due for t in tasks) for due in (None,"2026-10-07","2026-10-08","2026-10-09")]
        assert len(set(counts)) == 1
    oracle = json.loads((root / f"contracts/fixtures/{label}-oracle.json").read_text())
    assert len(oracle["sets"]["search_unique"]) == 1
    assert len(oracle["sets"]["search_cafe"]) == 1000
    assert len(oracle["sets"]["overdue"]) == 2000
    assert all(set(order) == {t["id"] for t in tasks} for order in oracle["orders"].values())
d1 = json.loads((root / "contracts/fixtures/D1.json").read_text())["tasks"]
d2 = json.loads((root / "contracts/fixtures/D2.json").read_text())["tasks"]
assert not ({t["id"] for t in d1} & {t["id"] for t in d2})
print(json.dumps({"status":"passed","fixtures":4,"tasks_per_dataset":10000,"scope":"specification fixture identities and distributions only"}))
