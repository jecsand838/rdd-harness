# Suite design

## Independent oracle

Bad: create a fixture with production serialization, restore it, export with that same serialization, and compare only the byte count.

Better: define an independent task dataset with fixed identities and every required field. Load through the approved API, export, decode with a separately reviewed format oracle, restore into a distinct collection, reopen storage, and compare semantic fields. Use different original and replacement datasets so a no-op restore fails.

## Minimum suite contract

| Concern | Required design |
|---|---|
| Discovery | A registered test target and command that actually executes it |
| Inputs | Frozen scenario IDs and fixtures with independent expected results |
| Isolation | New profile/database/temp location per applicable case |
| Synchronization | Observable readiness and fault cut points |
| Outcomes | Pass, failure, blocked, not-applicable, or skipped distinguished |
| Identity | Requirements/spec baseline, tested revision, package/fixture digests |
| Diagnostics | Raw command logs, safe failure detail, environment description |
| Integrity | No production changes to expected outputs merely to obtain green |

## Example boundary matrix

| Case | Why it can reveal a real defect |
|---|---|
| 200 vs 201 scalar-value title | Detects byte counting or wrong bound |
| Duplicate content with distinct identities | Detects accidental content-based deduplication |
| Completed task edited | Detects lost completion state/history |
| Notes-only Unicode search | Detects title-only or incorrect normalization logic |
| Capacity check under repeated activation | Detects split check/write and duplicate admission |
| Commit succeeds but response is lost | Detects false rejection and blind retry |
| Corrupt/newer database at startup | Detects silent empty-database replacement |
| Restore file changes after confirmation | Detects applying unconfirmed content |
| Diagnostic sink full | Detects logging becoming a mutation dependency |
| Release build without test plugins | Detects packaging an automation backdoor/server |

Use the exact requirement cases and counts rather than treating this table as complete coverage.

## Benchmark discipline

Record the specified reference machine, OS/WebView patch, power mode, fixture digest, package, warm-ups, all measured samples, and operation correctness. Start and stop timing at the approved UI/commit boundaries. Compute nearest-rank p95 from each platform and operation class separately. Keep slow results; exclude measurements only for independently documented environmental/instrumentation failure.

A unit-test timeout cannot establish a p95 budget. Paused clocks cannot establish real responsiveness. A faster replacement machine cannot stand in for unavailable required hardware without a requirements amendment. The harness must preserve the distinction between instrumented and delivered package evidence.

## Primary references

Checked 2026-10-07.

Select primary sources tagged `create-test-suite` in the [engineering source catalog](../../../../.rdd/sources/engineering.json).
