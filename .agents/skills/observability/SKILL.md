---
name: observability
description: Add or review private local structured logging, tracing spans, bounded retention, and safe diagnostic error codes for Rust and Tauri. Use for startup/storage/backup/migration diagnostics, async trace context, privacy tests, or observability task implementation.
---

# Private local observability

Read NFR-OBS-001, the privacy requirements, and the approved event vocabulary. The baseline requires local diagnostics and prohibits outbound telemetry. Do not add a collector or export endpoint.

## Procedure

1. Enumerate required events and safe fields: timestamp, severity, application version, operation category, correlation identity, and approved outcome/error code. Trace a meaningful operation boundary rather than every tiny method.
2. Default to `#[tracing::instrument(skip_all)]` or explicit field selection. Record no task titles, notes, due dates, search text, backup contents, or selected absolute paths. Inspect third-party error formatting before recording any cause.
3. Preserve trace context across asynchronous calls and owned tasks. Do not keep a synchronous span-enter guard across `.await`; instrument the future or use the async-aware macro.
4. Configure an account-local sink with bounded files and total retention no greater than the requirement's 10 MiB. Account for the active file, rotation, and restart. Diagnostic write failure must neither corrupt data nor reject an otherwise valid operation.
5. Avoid reporting success before commit. Distinguish application rejection, uncertain outcome, committed outcome, and notification delivery failure. Do not use error-level messages to conceal a silently ignored storage failure.
6. Test seeded sensitive values, path/error leakage, disabled/unwritable sinks, rotation boundaries, crash restart, and zero outbound connections. Keep benchmark instrumentation overhead visible and consistent with the approved protocol.

## Evidence

Record safe schema, representative sanitized events, retention/failure behavior, and privacy test results for phase review. Do not attach genuine task data or raw paths to review artifacts.

Read [logging patterns](references/logging.md) for original bad/good instrumentation and official sources.
