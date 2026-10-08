# Local persistence guidance

## Current route and qualification

As checked on 2026-10-07, Turso's Rust quickstart recommends `turso` for embedded local use. Its local builder opens a database file; cloud sync is an optional path. `turso_serverless` and the `libsql` remote/replica routes solve different deployment needs and do not satisfy this Todo baseline.

Pin a crate version rather than relying on `latest`. The quickstart is an entry point, not a complete compatibility contract. Qualify the actually used statements, pragmas, Rust API, target platforms, and recovery behavior. The current SDK reference and multiprocess page contain different-looking builder examples; resolve any discrepancy against the pinned crate's compilation and docs before specification freeze.

Default database ownership is one OS process, with connections/threads inside it. Experimental multiprocess WAL is unnecessary here and has platform/format constraints. Coordinate application instance ownership before opening the file. Do not start a separate CLI inspector against a live single-process database during tests.

## Parameterize values

Bad:

```rust
let sql = format!("UPDATE task_titles SET title = '{}' WHERE id = '{}'", title, id);
connection.execute(&sql, ()).await?;
```

Better illustrative local statements:

```rust
let database = turso::Builder::new_local(storage_path).build().await?;
let connection = database.connect()?;
connection.execute(
    "UPDATE task_titles SET title = ?1 WHERE id = ?2",
    (title, id),
).await?;
```

The table and function context are illustrative, not a frozen Todo schema. Keep the database owner alive for the intended lifecycle. Use the approved field representations and independent validation. Values can be bound; table names and SQL direction keywords require a fixed allowlist. Avoid `LIKE` wildcard behavior where requirements require literal substring semantics.

## Atomicity means the whole invariant

Bad restore: delete existing rows, then insert replacements one autocommitted row at a time.

Better sequence: validate all records and uniqueness outside storage mutation; bind the exact validated candidate to the confirmation; acquire mutation admission; begin one qualified transaction; replace rows and required metadata; commit; acknowledge; refresh the view. On rejection keep the old state. On an uncertain commit reconcile before another write.

A transaction is also needed wherever a check and write must remain indivisible, including a capacity check under concurrent access. Use the documented `transaction` and `commit` APIs for the pinned crate. Keep transaction acquisition, commit, and rollback failure semantics explicit; do not write a handwritten `BEGIN`/`COMMIT` abstraction that is unaware of connection ownership or cancellation.

## Backup publication

The user backup is versioned JSON containing a consistent committed snapshot. It is independent of engine-file layout and WAL state.

1. Establish the approved consistent read snapshot.
2. Serialize bounded validated data to a temporary file in the permitted destination filesystem.
3. Complete and validate the file before publication; use the platform-qualified replacement primitive.
4. Preserve an existing destination until publication succeeds. Reconcile uncertain publication as old-complete or new-complete.
5. Reject destinations aliasing database, WAL/recovery, migration, or diagnostic files, including supported symlink/hardlink/case/path equivalence cases.
6. Handle selected-file replacement between validation and restore by retaining the validated candidate or revalidating and asking for renewed confirmation.

Simple `std::fs::rename` is not a universal cross-platform proof of replace-existing semantics, directory durability, or support on every filesystem. Select a documented mechanism and test it on the required local filesystems. Reject unsupported storage before modifying an existing destination. Do not grant the UI generic directory-wide filesystem permission just because one file was selected.

## Durability and migration

Turso Cloud durability percentages describe cloud infrastructure; they do not establish local-file durability. Record the pinned engine's local settings and independently run the specified process-kill model. Keep the acknowledgment ledger outside the killed child. A later acknowledged restore can supersede prior tasks, so validate sequential history rather than unioning every historical row.

For upgrades, preserve recoverable prior data before a format transition and reject newer formats. Keep old fixtures immutable. Release one still needs a versioned initial fixture and future-format rejection even though prior-release migration is not yet applicable.

## Primary references

Checked 2026-10-07.

- [Rust quickstart](https://docs.turso.tech/sdk/rust/quickstart)
- [Rust API reference](https://docs.turso.tech/sdk/rust/reference)
- [SQLite compatibility](https://docs.turso.tech/sql-reference/compatibility)
- [Transactions](https://docs.turso.tech/sql-reference/statements/transactions)
- [Multiprocess constraints](https://docs.turso.tech/sql-reference/multiprocess-access)
- [Cloud durability scope](https://docs.turso.tech/cloud/durability)
