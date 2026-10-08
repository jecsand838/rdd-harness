---
name: create-api
description: Implement an approved application API operation or endpoint set with generated contracts, validation, error semantics, access control, and boundary tests. Use for local Tauri command APIs or future explicitly specified transports; do not add an HTTP/gRPC server to the offline Todo baseline.
---

# Implement an API set

Read the authoritative operation inventory, contracts, scenario oracle, and error/admission policy. The current product API is local Tauri IPC. A protobuf `service` declaration does not require a network server.

## Procedure

1. Map each operation to its requirement IDs, caller, owning module, request, response, errors, side effects, and admission/commit semantics. Implement only approved operations.
2. Bind the generated service interface to a concrete application service. Keep transport conversion thin. Reject invalid values natively even when the Rust UI validates them for feedback.
3. Define behavior for missing identities, repeated operations, no-op changes, invalid enum/presence combinations, oversized requests, and stale results using the frozen specification. An operation missing these semantics cannot be improvised in implementation.
4. For mutations, enforce one pending operation for the collection, preserve drafts, and acknowledge only commit. For queries, preserve required AND filtering, exact identity sets, ordering, and non-mutating behavior.
5. Scope access to required capabilities and selected files. Do not expose raw SQL, arbitrary filesystem paths, script evaluation, or generic reflection-based dispatch.
6. Test the public boundary before implementation. Include serialization compatibility, input rejection, side-effect absence on rejection, persistence, uncertainty, and caller restrictions. Wire the actual UI consumer and remove superseded calls.
7. Update operation documentation and traceability using the exact implemented contract version. Do not rename fields, add commands, or broaden error meanings to avoid a blocker.

## Completion evidence

Compile consumer and provider against generated signatures; run the relevant boundary suite and architecture checks. Record the operation-to-scenario mapping and any transport limitation for the phase review.

Read [API patterns](references/api.md) and use `tauri-commands-events` for Tauri adapters or `protobuf-contracts` for schema questions.
