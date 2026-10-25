# API design and implementation patterns

## Operation inventory

Specification supplies this information before implementation:

| Field | Example purpose |
|---|---|
| Requirement/scenario IDs | Trace accepted behavior and its independent oracle |
| Owning module and caller | Establish allowed dependency direction |
| Request and response type | Match generated schema |
| Validation | Field limits, state combinations, format versions |
| Errors | Stable public codes and safe recovery actions |
| Side effects | Which state changes, and under what transaction |
| Repeated request | No-op, rejection, or distinct operation as specified |
| Admission and acknowledgment | Pending limit, commit point, uncertainty handling |
| Capability/path scope | Which window and selected resource are authorized |

Do not infer that identical create content is an idempotency key: the Todo requirements allow different tasks with identical titles and notes. Distinguish suppressing repeated activation of one pending submission from a later deliberate create.

## Bad: a generic escape hatch

```rust
#[tauri::command]
async fn execute_sql(sql: String) -> Result<String, String> {
    database_execute(sql).await
}
```

This puts storage authority in the UI and bypasses domain contracts.

## Better: behavior-specific application service

```rust
impl TaskApplication {
    pub async fn complete(&self, request: api::CompleteRequest)
        -> Result<api::CompleteResponse, api::OperationError>
    {
        let identity = TaskIdentity::try_from(request.identity)?;
        self.mutations.complete(identity).await
    }
}
```

Names are illustrative and must be replaced by the frozen generated interface. `mutations.complete` owns admission, idempotent completion semantics, persistence, and outcome reconciliation. The real type must implement the generated service trait, not merely reproduce its method names manually. The transport adapter delegates to it and serializes only approved outputs.

## Keep transport and domain separate

Generated request fields are representations, not automatically validated values. A wire `string` can contain a bad date or oversized title. An enum may contain a future numeric value. Validate and map explicitly, including optional absence versus a zero/default value. Avoid a stringly typed map in the middle of an otherwise typed call chain.

For a future requirements amendment that introduces an HTTP API, specification must add transport-specific obligations such as authentication, authorization, HTTP semantics, resource identity, caching, and rate limits. Do not invent them for this local application or create dormant endpoints for possible reuse.

## Primary references

Checked 2026-10-07.

Select primary sources tagged `create-api` in the [engineering source catalog](../../../../.rdd/sources/engineering.json).
