---
name: rust-async-tokio
description: Implement or review Rust async work using Tokio, including Send and lifetime bounds, shared state, bounded queues, cancellation safety, blocking work, shutdown, and deterministic tests. Use for database operations, Tauri commands, background refresh, or async lifecycle defects.
---

# Rust async with Tokio

Read the approved concurrency, mutation acknowledgment, shutdown, and failure-model specifications. Use the runtime already owned by Tauri; do not create a runtime per command or call blocking `block_on` from an async task.

## Procedure

1. Assign every resource and spawned task an owner. Keep a join handle, task set, or tracker; define who observes errors and waits during shutdown. Dropping a handle must never be mistaken for cancelling work.
2. Keep synchronous code short on executor threads. Await async I/O. Move finite CPU-heavy or unavoidable blocking work to a bounded blocking facility; use an explicit worker thread for a long-lived blocking loop. `spawn_blocking` is not a cancellation mechanism.
3. Inspect values retained across every `.await`. Multi-threaded spawned tasks need `Send` and owned or `'static`-compatible captures. A `'static` bound does not require leaking data. Never force `unsafe impl Send` to silence the compiler.
4. Choose synchronization deliberately. A short, uncontended standard mutex can protect synchronous data if its guard ends before `.await`. An async mutex can protect async resource ownership, but keep the critical section narrow. A stateful I/O owner with a bounded queue can make admission, ordering, and shutdown explicit.
5. Define queue capacity, admission behavior, and overload reporting. For this Todo baseline, accept at most one pending user mutation; do not queue duplicate submissions silently. Keep read/view work responsive under the approved policy.
6. Treat cancellation as a state transition. Cancelling a UI future does not prove a database mutation did not commit. Once admitted, drive a mutation to a known committed/rejected result or reconcile uncertainty before retry. Use `select!` only where dropping the losing future preserves semantics.
7. Close admission before shutdown, signal cancellable background work, resolve admitted mutations, and join owned work. Normal close must satisfy FR-018. Forced termination is covered by recovery tests.

## Checks

Exercise duplicate submission, slow I/O, queue saturation, receiver disappearance, join failure, close during commit, and cancellation at meaningful boundaries. Synchronize tests deterministically; keep real timing for benchmarks. Record evidence for the phase gate.

Read [async patterns](references/patterns.md) for original examples and primary sources.
