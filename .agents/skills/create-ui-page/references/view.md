# UI state and interaction patterns

## Model mutually exclusive states

Bad:

```rust
struct Editor {
    saving: bool,
    saved: bool,
    failed: bool,
    unknown: bool,
}
```

This can represent simultaneous success, failure, and uncertainty.

Better illustrative state:

```rust
enum SaveState {
    Idle,
    Pending { operation: OperationId },
    Rejected { field: Option<FieldId>, code: ErrorCode },
    Uncertain { operation: OperationId },
    Committed { revision: Revision },
}

struct Editor {
    baseline: TaskView,
    draft: TaskDraft,
    save: SaveState,
}
```

The names and states are an illustration; use the exact approved contract and UI specification. Keep a draft through rejection and uncertainty. A mutation result may update the baseline; an event by itself cannot establish committed state. Preserve the user's text when a display filter removes a task from view.

## Ignore stale read results

Bad: every completed search replaces the result list, even if it began before the current query.

Better pure reducer pattern:

```rust
struct QueryState {
    generation: u64,
    visible: Vec<TaskView>,
}

impl QueryState {
    fn accept(&mut self, generation: u64, rows: Vec<TaskView>) {
        if generation == self.generation {
            self.visible = rows;
        }
    }
}
```

Create a new generation when query inputs change. Handle overflow according to the approved ID policy, and retain error/pending state for the current generation. Cancellation can reduce wasted read work but does not make response ordering safe by itself.

## Render untrusted data as text

Bad declarative pattern: inserting a title into an unchecked HTML property or constructing JavaScript with string interpolation.

Better: bind a string to the framework's text-node rendering API. Use real buttons, inputs, labels, and dialog semantics. Keep generated glue isolated; do not introduce a parallel JavaScript state machine because an example in the framework documentation uses one.

## Interaction evidence

| Journey | Evidence to capture |
|---|---|
| Invalid title | Field association, retained draft, no native mutation |
| Slow save | Busy feedback by the specified deadline, no false success |
| Repeated activation | One admitted effect, no hidden queued duplicate |
| Search changes quickly | Final identity set corresponds to current inputs |
| Delete/restore confirmation | Identified target, cancellation unchanged, predictable focus |
| Dirty navigation/close | Retain cancels navigation; discard is explicit |
| Empty and filtered-empty | Different messages and useful actions |
| Midnight/resume | Derived dates refresh without changing stored dates |

Keep native error recovery understandable without exposing traces or SQL. Prefer announced state changes over transient color-only signals. A visually polished screenshot cannot establish keyboard completion.

## Primary references

Checked 2026-10-07.

- [Tauri Rust frontend configuration](https://v2.tauri.app/start/frontend/)
- [Tauri IPC](https://v2.tauri.app/develop/calling-rust/)
- [Tauri event and channel delivery](https://v2.tauri.app/develop/calling-frontend/)
- [WCAG 2.2 normative criteria](https://www.w3.org/TR/WCAG22/)
