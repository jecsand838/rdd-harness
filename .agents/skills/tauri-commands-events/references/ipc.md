# IPC patterns

## Pick a mechanism by its semantics

| Need | Mechanism | Additional application obligation |
|---|---|---|
| Read or mutate data and receive outcome | Command | Validate, authorize, and define commit acknowledgment |
| Invalidate a view or announce an approved change | Scoped event | Handle missed notifications and clean up listeners |
| Deliver ordered progress/messages | Channel | Bound production and decide disconnect behavior |

Tauri events do not provide a strongly typed protocol or fine-grained per-payload capability enforcement. Commands and generated bindings provide a better point to enforce required mutation semantics. Channels order delivery, but an ordering guarantee is not a bounded backpressure policy or durable message log.

## Bad: event-driven mutation with unvalidated JSON

```rust
app.listen("save", move |event| {
    let request: serde_json::Value = serde_json::from_str(event.payload()).unwrap();
    write_task(request);
});
```

This creates a second application API, has no committed result, and can panic on untrusted input. A listener's existence does not authorize a request.

## Better: thin command bound to the generated API

Illustrative shape; names and payload limits must come from the frozen specification:

```rust
use prost::Message;

#[tauri::command]
async fn apply_change(
    state: tauri::State<'_, AppState>,
    encoded: Vec<u8>,
) -> Result<Vec<u8>, PublicError> {
    if encoded.len() > MAX_REQUEST_BYTES {
        return Err(PublicError::payload_too_large());
    }
    let request = api::ApplyChangeRequest::decode(encoded.as_slice())
        .map_err(|_| PublicError::invalid_payload())?;
    let response = state.service.apply_change(request).await?;
    Ok(response.encode_to_vec())
}
```

`AppState`, `api`, `PublicError`, and limits refer to approved generated/adapted types; this is not an additional Todo contract. The service implements the generated trait and validates domain meaning before storage. Payloads must be bounded at every relevant entry path, including backup files. A binary message remains untrusted.

Prost messages do not automatically imply ProtoJSON-compatible Serde behavior. Specification must choose a tested binary envelope or a pinned compatible JSON mapping. For this byte-array illustration, Tauri serializes `Vec<u8>` as JSON numbers. A raw IPC response/channel uses different Tauri types. Measure payload cost before choosing; preserve the same authoritative schema in either case. Account for 64-bit numbers, enum unknowns, optional fields, bytes, and date semantics.

## Errors and notifications

Bad sequence: commit, attempt an event, then return the event error as if the mutation failed.

Better sequence: obtain the authoritative committed result; return its contract-defined acknowledgment; attempt any specified notification with separate redacted delivery diagnostics. A notification error may require a refresh or channel reconnect, but cannot undo the write or justify repeating it.

Do not encode raw SQL exceptions using `error.to_string()` as the public API. Use stable codes and safe field identifiers. On uncertainty, preserve the pending operation identity and reconcile the stored outcome before enabling a retry that could create a duplicate.

## State and resource lifetime

Register exactly the type requested by `State<'_, T>`; a mismatch can fail at runtime. Avoid a standard mutex guard across `.await`. Managed state already has runtime-owned shared access; add `Arc` only when a separate owned handle is justified. Track listeners and spawned workers so closing a page/window cannot leave unbounded subscriptions or unsupervised tasks.

## Primary references

Checked 2026-10-07.

Select primary sources tagged `tauri-commands-events` in the [engineering source catalog](../../../../.rdd/sources/engineering.json).
