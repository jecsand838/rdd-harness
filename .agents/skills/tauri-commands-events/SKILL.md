---
name: tauri-commands-events
description: Implement or review Tauri 2 commands, events, channels, managed state, and generated Protobuf adapters. Use for local UI-to-native APIs, mutation acknowledgment, progress delivery, command validation, event cleanup, or IPC security defects.
---

# Tauri commands, events, and channels

Read the frozen application API, generated Rust service interface, public errors, and operation semantics. A contract defect or missing operation discovered during preparation/implementation is a blocker for specification; do not add an unofficial command or event route.

## Procedure

1. Use commands for validated request/result operations. Use events for small notifications that may have multiple consumers. Use channels for approved ordered streams/progress. Do not use frontend-emitted events as an unauthenticated mutation API.
2. Decode into generated request types, then validate domain values and operation permissions natively. Enforce payload limits before expensive decoding. Bind the adapter to the generated service signature; an arbitrary JSON object named like the contract is insufficient.
3. Keep managed state types exact and stable. `State<T>` injection must match the managed type. Clone an owned service handle when background ownership requires it; do not move a borrowed state reference into an unbounded task. Use `Result` and owned payloads for async command boundaries.
4. Return serializable, contract-defined success/error data. Keep internal error details in redacted diagnostics. Distinguish rejected, pending, and uncertain outcomes. Return mutation success only after commit; channel delivery or event emission is never proof of persistence.
5. Make cancellation and disconnection explicit. If a caller disappears after admission, finish/reconcile the write according to specification. Treat a lost notification after commit as a delivery issue, not as a rejected write that invites duplication.
6. Scope notifications to the intended window, namespace event names, include only approved payload data, and remove listeners on teardown. Re-query authoritative state after reconnect or missed notifications. Reject stale query responses using an approved generation/request identity.
7. Restrict custom commands through the declared application-command permission mechanism and capabilities. Check native path authority independently. Verify that an unapproved window or malformed direct invocation cannot bypass the UI's constraints.

## Checks

Test wire round trips, unknown enum values, missing/oversized/invalid payloads, state registration, duplicate activation, close during commit, stale responses, removed listeners, denied callers, and notification failure after a successful mutation. Compile native and Rust/WASM consumers. Report results at the phase gate.

Read [IPC patterns](references/ipc.md) before choosing serialization or command/event mechanisms.
