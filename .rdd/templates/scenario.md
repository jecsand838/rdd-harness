# Acceptance scenario

> Authoring template. Add the scenario's machine record to `.rdd/spec.json` using the active schema. Use a stable scenario ID; preserve it for the same observable obligation.

## Identity and scope

State scenario ID, title, requirement IDs, solution-element/behavior and operation/module IDs, scenario kind, and supported environments.

## Initial state

Define fixture contents, identities, relevant time/clock, persisted state, permissions, network conditions, and deterministic seeds. Distinguish committed state from unsubmitted input.

## Stimulus

Describe the action sequence or concurrent/interruption schedule. Identify the actual boundary exercised. Avoid referring to an implementation helper as the sole acceptance boundary for user-visible behavior.

## Observable oracle

Define exact expected state, result, error, timing, and forbidden side effects. Include negative assertions where needed. Use a distinct replacement fixture when testing restore, migration, or copying to ensure a no-op cannot pass.

## Evidence method

State the test type, required hardware/platform/manual observations, check ID, command/evaluator, output artifact, and failure interpretation. Define how the test reports the executed scenario ID, assertion outcome and evidence. Aggregate success cannot cover an omitted, filtered or skipped scenario.

## Boundaries and limitations

State which uncertainty or failure model is covered. Do not extrapolate a finite test to untested hardware or arbitrary fault conditions. A skipped required scenario remains missing evidence.

## TDD plan

State what assertion should fail before behavior exists, the expected actual assertion/panic diagnostic (not source-line text), permitted compile scaffolding, and how behavioral RED will be captured. Missing tools and unrelated compiler failures are setup failures, not behavioral RED.
