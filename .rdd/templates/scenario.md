# Acceptance scenario

S3 authors `docs/specs/scenarios.json`, a complete array using the `scenarios` property of [spec.schema.json](../schemas/spec.schema.json). Preserve IDs for unchanged obligations. S6 consumes the accepted catalog; it cannot add or rewrite its assertions. See [artifact handoffs](../../docs/harness/artifact-guide.md#s1-domain-inventory).

For each record, specify:

- **Identity and scope:** requirement IDs, S1 solution-element IDs and kind. Every claimed edge must describe an asserted obligation, not merely share a requirement label.
- **Independent fixture:** contents, identities, time, persisted state, permissions, network conditions and seeds; distinguish committed state from unsubmitted input.
- **Stimulus:** the action, concurrency or interruption schedule through the actual application/module boundary; an internal helper alone cannot prove user-visible behavior.
- **Oracle:** exact state, result, error, timing and forbidden effects. Use a distinct replacement fixture for restore/migration/copying so a no-op cannot pass.
- **Verification:** planned check IDs, evaluator, platform/hardware/manual prerequisites and executed-scenario evidence. State the bounded failure model; do not extrapolate to untested faults or hosts.

Use the [evidence guide](../../docs/harness/evidence-guide.md#explicit-golden-scenario-results) for per-scenario outcomes and [behavioral RED](../../docs/harness/evidence-guide.md#behavioral-red) for the assertion, permitted scaffolding and failure interpretation. Aggregate success cannot cover skipped or omitted scenarios; compilation/tool failures are not behavioral RED.
