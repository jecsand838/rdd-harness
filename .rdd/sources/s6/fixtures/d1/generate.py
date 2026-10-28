"""Specification fixture generation only; imports no application/ICU code."""
from pathlib import Path
import hashlib
import json
import platform
import uuid

ROOT = Path(__file__).parent
SEED = "rdd.todo.d1.r5.v1"

def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()

manifest = {"seed": SEED, "nominal_date": "2026-10-27", "generator_python": platform.python_version(), "files": {}}
all_ids = set()
for variant in ("A", "B"):
    tasks = []
    for i in range(10000):
        raw = bytearray(hashlib.sha256(f"{SEED}:{variant}:{i:05d}".encode("ascii")).digest()[:16])
        raw[6] = (raw[6] & 15) | 64
        raw[8] = (raw[8] & 63) | 128
        identity = str(uuid.UUID(bytes=bytes(raw)))
        assert identity not in all_ids
        all_ids.add(identity)
        title = f"{variant} {'TASK' if i % 2 else 'task'} {i:05d}"
        if i % 10 == 0:
            title += " Café"
        if i % 100 == 0:
            title += " [x]*"
        title = title.ljust(80, "t")
        notes = f"{variant} note {i:05d}"
        if i % 10 == 0:
            notes += " cafe\u0301 Straße"
        if i == 42:
            notes += " notes-only-key"
        notes = notes.ljust(256, "n")
        created = {"seconds": 1700000000 + i // 4, "nanos": 0}
        completed = {"seconds": created["seconds"] + 10, "nanos": 0} if i % 5 == 0 else None
        tasks.append({"identity": identity, "title": title, "notes": notes,
                      "due_date": [None, "2026-10-26", "2026-10-27", "2026-10-28"][(i // 5) % 4],
                      "status": "Completed" if completed else "Open", "created_time": created,
                      "updated_time": completed or created, "completed_time": completed})
    ids = [t["identity"] for t in tasks]
    def choose(predicate):
        return [ids[i] for i in range(10000) if predicate(i)]
    def ordered(key):
        return [t["identity"] for t in sorted(tasks, key=key)]
    keyid = lambda t: uuid.UUID(t["identity"]).bytes
    oracle = {
        "variant": variant,
        "ids_by_index": ids,
        "sets": {
            "all": ids, "Open": choose(lambda i: i % 5 != 0), "Completed": choose(lambda i: i % 5 == 0),
            "Any": ids, "No due date": choose(lambda i: (i // 5) % 4 == 0),
            "Today@2026-10-27": choose(lambda i: (i // 5) % 4 == 2),
            "Overdue@2026-10-27": choose(lambda i: i % 5 != 0 and (i // 5) % 4 == 1),
            "query:zero-match-❌": [], "query:task": ids,
            f"query:{variant} task 00042": [ids[42]], "query:notes-only-key": [ids[42]],
            "query:[x]*": choose(lambda i: i % 100 == 0),
            "query:cafe+U0301": choose(lambda i: i % 10 == 0),
            "query:STRASSE": choose(lambda i: i % 10 == 0), "query:cafe": [],
        },
        "orders": {
            "newest": ordered(lambda t: (-t["created_time"]["seconds"], -t["created_time"]["nanos"], keyid(t))),
            "oldest": ordered(lambda t: (t["created_time"]["seconds"], t["created_time"]["nanos"], keyid(t))),
            "due": ordered(lambda t: (t["due_date"] is None, t["due_date"] or "", -t["created_time"]["seconds"], -t["created_time"]["nanos"], keyid(t))),
        },
    }
    for name, value in ((f"D1{variant}.json", {"format_version": 1, "tasks": tasks}), (f"D1{variant}.oracle.json", oracle)):
        data = canonical(value)
        (ROOT / name).write_bytes(data)
        manifest["files"][name] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
manifest["generator_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
(ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
print(json.dumps(manifest, ensure_ascii=False, indent=2))
