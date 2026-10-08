# Logging and tracing patterns

## Explicitly select fields

Bad:

```rust
#[tracing::instrument]
async fn save_task(request: TaskDraft, path: std::path::PathBuf) {
    tracing::info!(?request, ?path, "saving task");
}
```

Default argument capture and `Debug` output can disclose user data. Logging a full database error may also contain SQL values or a selected path.

Better illustrative function:

```rust
#[tracing::instrument(
    name = "task.save",
    skip_all,
    fields(operation = "save", correlation = %context.correlation_id())
)]
async fn save_task(context: &Context, request: TaskDraft)
    -> Result<SaveReceipt, OperationError>
{
    let outcome = context.tasks.save(request).await;
    match &outcome {
        Ok(_) => tracing::info!(outcome = "committed", "operation completed"),
        Err(error) => tracing::warn!(
            outcome = error.outcome_code(),
            error_code = error.safe_code(),
            "operation unresolved or rejected"
        ),
    }
    outcome
}
```

Types and code vocabulary are illustrative. `safe_code` must return a closed, non-sensitive code, not arbitrary `Display` text. Configure timestamp, severity, and application version in the sink/event layer. If `save` returns an uncertain outcome, never rewrite it as a rejection in diagnostics or UI feedback.

## Async span context

Bad:

```rust
let entered = tracing::info_span!("restore").entered();
perform_restore().await;
drop(entered);
```

Better:

```rust
use tracing::Instrument;
perform_restore()
    .instrument(tracing::info_span!("restore", operation = "restore"))
    .await;
```

The future is entered during its polls. Propagate the approved correlation ID into background work; do not log private data to obtain correlation.

## Retention and privacy checks

Use a finite event vocabulary and explicit field allowlist. Seed conspicuous synthetic titles, Unicode notes, a due date, query, selected path, and backup content; exercise all failure paths and assert none appears in any retained diagnostic file. Inspect compressed/rotated outputs if the design uses them. Verify retention after restart and at the exact configured boundary.

Prevent diagnostics from becoming a data dependency. If the sink fails, preserve the application's valid mutation result and use a safe fallback that does not recurse into the same failing logger. Runtime diagnostics are distinct from harness evidence; the latter may include source paths but must still avoid user secrets.

## Primary references

Checked 2026-10-07.

- [Tokio tracing overview](https://tokio.rs/tokio/topics/tracing)
- [tracing instrument and field selection](https://docs.rs/tracing/latest/tracing/attr.instrument.html)
- [Span enter and async warning](https://docs.rs/tracing/latest/tracing/span/struct.Span.html#method.enter)
