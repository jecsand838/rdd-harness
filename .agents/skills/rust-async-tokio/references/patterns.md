# Async ownership and cancellation

Contents: [Locks](#release-synchronous-locks-before-waiting), [admission](#supervise-work-and-bound-admission), [cancellation](#cancel-only-work-with-defined-drop-behavior), [blocking work](#blocking-work), [sources](#primary-references).

Original examples illustrate local patterns, not finalized application interfaces. Compile adaptations against pinned versions.

## Release synchronous locks before waiting

Bad:

```rust
async fn refresh(cache: &std::sync::Mutex<Vec<String>>) {
    let values = cache.lock().unwrap();
    render_view(&values).await;
}
```

Better: take the required snapshot in a lexical scope, handling poisoning explicitly.

```rust
#[derive(Debug)]
struct CacheUnavailable;

fn snapshot(cache: &std::sync::Mutex<Vec<String>>)
    -> Result<Vec<String>, CacheUnavailable>
{
    let values = cache.lock().map_err(|_| CacheUnavailable)?;
    Ok(values.clone())
}

async fn refresh(cache: &std::sync::Mutex<Vec<String>>)
    -> Result<(), CacheUnavailable>
{
    let values = snapshot(cache)?;
    render_view(&values).await;
    Ok(())
}
```

`render_view` stands for an existing async consumer. Copying a small view snapshot is deliberate. For large data, consider a shared immutable snapshot or narrower projection after measuring. Never retain a synchronous lock across `.await` because a current executor happens to be single-threaded.

## Supervise work and bound admission

Bad:

```rust
for request in incoming {
    tokio::spawn(async move { persist(request).await });
}
// No capacity, outcome handling, or shutdown ownership.
```

Better conceptual arrangement:

```rust
enum Job {
    Apply { command: Command, reply: tokio::sync::oneshot::Sender<Outcome> },
}

async fn writer(mut rx: tokio::sync::mpsc::Receiver<Job>, mut store: Store) {
    while let Some(Job::Apply { command, reply }) = rx.recv().await {
        let outcome = store.apply(command).await;
        // A disconnected caller cannot cancel an already admitted commit.
        let _ = reply.send(outcome);
    }
}
```

`Command`, `Outcome`, and `Store` mean approved application types. Pair this with bounded admission, a guard enforcing one pending mutation, a supervisor observing worker failure, and reconciliation of uncertain results. Queue capacity alone cannot prevent one active mutation plus a queued duplicate. A failed reply delivery cannot justify blindly repeating a mutation.

## Cancel only work with defined drop behavior

This complete helper only signals a refresh generation; it makes no persistent changes:

```rust
async fn tick_until_cancelled(
    cancel: tokio_util::sync::CancellationToken,
    tx: tokio::sync::watch::Sender<u64>,
) {
    let mut timer = tokio::time::interval(std::time::Duration::from_secs(30));
    let mut generation = 0;
    loop {
        tokio::select! {
            _ = cancel.cancelled() => break,
            _ = timer.tick() => {
                generation += 1;
                if tx.send(generation).is_err() { break; }
            }
        }
    }
}
```

The approved date/focus behavior determines when to recompute Today and Overdue. Do not wrap a non-cancellation-safe transaction in the same pattern and call the cancelled operation rejected. A timeout describes the waiter's state; actual commit outcome needs independent knowledge.

## Blocking work

Use `spawn_blocking` for finite work when the async path cannot avoid blocking. Limit concurrency before spawning. Observe the join result and the closure's `Result`. A started blocking closure generally continues even if its waiter is aborted. Do not let it mutate files after declaring shutdown complete. For persistent blocking loops, use an explicitly owned thread with a cooperative shutdown path.

## Primary references

Checked 2026-10-07.

Select primary sources tagged `rust-async-tokio` in the [engineering source catalog](../../../../.rdd/sources/engineering.json).
