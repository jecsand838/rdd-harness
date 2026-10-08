# Native instance lease qualification

## Required capability

FR-024 requires one database-owning process per account and data location, including simultaneous launches, with activation of the existing window. NFR-PRIV-001 prohibits outbound networking and NFR-PRIV-002 restricts managed files to the current account. This experiment qualifies Darwin file-lease and private file acknowledgment primitives; the solution specification owns the complete selected lifecycle protocol.

## Candidate and evidence

Use an exclusive nonblocking Darwin `flock` on a persistent lease file in the account-private data directory. Acquire it before opening the database, keep the owning file descriptor alive through shutdown, and never unlink or replace the lease file to release it. A losing launch must not initialize a database. Distinct selected data locations use distinct lease files.

The [Apple XNU flock manual](https://raw.githubusercontent.com/apple-oss-distributions/xnu/main/bsd/man/man2/flock.2) and installed SDK 27.0 `usr/share/man/man2/flock.2` were read on 2026-10-08. They document exclusive advisory ownership and nonblocking contention returning `EWOULDBLOCK`. Advisory locking requires every application launch to cooperate; it is not protection from a hostile process with the same account privileges. Constants `LOCK_EX=2`, `LOCK_NB=4` match installed SDK `usr/include/sys/fcntl.h`.

The experiment adds no Rust runtime crate. It uses Rust 1.99.0 standard facilities and the OS-provided function declaration; no SDK source is copied or redistributed. Production may bind the already selected exact `libc` dependency. The rejected plugin and selected complete protocol are recorded in the runtime decision and dependency qualification documents.

## Reproduction and measured observations

Run `python3 experiments/spec-instance/run.py`. It compiles [the probe](../../experiments/spec-instance/probe.rs) with `rustc --edition=2024 -D warnings`, creates disposable fixtures under ignored `target/spec-instance`, and removes its own fixture directory on completion. `--record` refreshes draft evidence; ordinary execution leaves the accepted evidence files unchanged.

| Case | Observable oracle | Result |
|---|---|---|
| Eight children released from an explicit pipe barrier | Exactly one obtains the exclusive lease and creates the owner-only marker; seven report secondary and create no owner marker | Passed |
| Private activation requests | Each losing child publishes its unique nonce in an exclusive-created 0600 temporary and renames it to a request; primary publishes the identical acknowledgment only after its simulated callback marker; each child compares the nonce | Seven simultaneous and one later sequential acknowledgment passed |
| Managed-file permissions | Lease, request, acknowledgment, and callback fixture files are mode 0600, containing directory mode 0700 | Passed |
| Owner interrupted | Parent sends SIGKILL and observes signal 9; a new child acquires the same lease inode without deleting/replacing the lease | Passed |
| Independent data location | A child for a second private directory obtains its own exclusive lease while the first location remains owned | Passed |

The primary polls private fixture requests every 50 milliseconds. The fixture's activation callback records a marker rather than manipulating a real window. The marker precedes publication of an acknowledgment, providing an independent ordering oracle. Real application acknowledgment must follow successful native window show/focus on the event loop; a timeout or focus failure is not an acknowledgment or permission to open another database writer.

[Machine result](../../experiments/spec-instance/results.json) pins source hashes, compiler identity, and successful exit. [Transcript](../../experiments/spec-instance/transcript.txt) records actual observations. [Reference environment](reference-host.json) identifies the qualified Mac and SDK. The runner asserts all children terminate as expected, including the two deliberately killed lease owners; no fixture process is retained after success.

## Limits and later obligations

This is a generic OS primitive experiment, with no Todo behavior, real database owner, real UI draft, or production activation adapter. The real packaged dependency probe separately qualifies the selected Tauri native window show/focus APIs; it does not establish the full multi-instance application behavior. No foreign-account access, malicious same-account process, stale nonce replay, unresponsive primary, or application performance acceptance is claimed by this experiment. The packaged FR-024 suite must exercise simultaneous/sequential launches, correct existing-window activation and preserved drafts, no second database owner, failed startup, pending shutdown, stale activation files, and owner death using the actual application adapter. Runtime locks must fail closed on permission/I/O errors; primary nonresponsiveness alone must never break a held lease. Requalify if the selected SDK, storage location, locking method, or activation protocol changes.
