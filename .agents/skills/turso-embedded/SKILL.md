---
name: turso-embedded
description: Implement or review a persistent local Turso database through the current turso Rust crate. Use for connection ownership, transaction semantics, parameterized SQL, migrations, backup/restore, crash recovery, or engine compatibility qualification in the Rust Todo application.
---

# Embedded Turso

Use `turso`, the Rust embedded engine required by NFR-TECH-003. Do not substitute `libsql`, a cloud embedded replica, a remote driver, SQLite via another crate, or browser storage. This baseline excludes sync and cloud credentials.

## Procedure

1. Read the exact pinned crate documentation and approved qualification results. Confirm APIs, supported SQL, platform builds, transaction behavior, data-format compatibility, and local durability settings. Record feature flags. A successful SQL statement does not prove a requested pragma took effect.
2. Open the persistent account-specific local path only after instance arbitration. Own the database and connections for a defined lifecycle. Distinguish absence from inability to read an existing database. Preserve inaccessible, invalid, or newer-format storage.
3. Parameterize values and whitelist any variable identifiers/order clauses. Keep SQL inside the storage adapter. Validate input natively and bind it with the approved data representation; do not infer SQL collation implements the required Unicode search semantics.
4. Serialize admitted user mutations according to FR-018. Use actual transactions for multi-statement invariants and complete collection restore. Treat capacity checks and writes as one operation. Keep UI confirmation and expensive backup parsing outside the write transaction.
5. Acknowledge success only after commit. On an unknown commit outcome, preserve the operation identity and reconcile before retry. Verify rollback-on-error/drop behavior against the pinned engine; do not assume every failure is an automatic confirmed rollback.
6. Export one consistent committed snapshot into the specified JSON format. Validate the complete restore candidate, retain the confirmed candidate identity/content, and replace the collection atomically. Never copy just a live `.db` file as a valid logical backup.
7. Version migrations, retain the prior dataset until success, reject unsupported future formats, and test failed/interrupted transitions. Do not create an empty database to recover from a migration error.

## Evidence

Run real-disk restart, process termination, lock contention, read-only/corrupt/newer fixtures, invalid backup, destination aliases, atomic replacement, and defined capacity tests. Retain platform and engine versions with results. Unknown engine behavior is a specification blocker; never enable an experimental feature opportunistically during implementation.

Read [persistence guidance](references/persistence.md) for original examples, backup details, and current compatibility caveats.
