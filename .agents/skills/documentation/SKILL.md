---
name: documentation
description: Update user, developer, API, compatibility, and release documentation with verified commands and requirement traceability. Use for phase documentation tasks, local Todo help, build/verification handoff, ADR updates in specification, or stale-document cleanup.
---

# Update documentation

Read the owned documentation task, applicable requirements, current behavior, and approved artifact authority. Requirements remain canonical; generated plans and specifications cannot be silently rewritten during implementation to excuse different behavior.

## Procedure

1. Identify the audience and existing authoritative page. Update it instead of creating a duplicate guide. Remove superseded commands and descriptions within the assigned scope.
2. Write the actual user operation, prerequisite, outcome, and recovery path. Keep implementation mechanics out of user flows unless users need them to make a decision.
3. For developer instructions, execute commands from a clean or equivalent controlled checkout. Record prerequisites, supported versions, paths, generated files, and required credentials without exposing values. Separate tested commands from unavailable-platform instructions.
4. For this Todo app, cover offline use, title/notes/date rules, completion/deletion, search/filter semantics, data locations, unencrypted backups, replacement restore, draft/pending behavior, and recoverable failures. State that deletion has no built-in undo.
5. Update contract/API references from the frozen source and code generation. Update release compatibility notes, dependency inventory, package digests, and evidence links from actual outputs. Do not claim passing accessibility, packaging, benchmarks, or production readiness without required evidence.
6. Keep ADRs concise: decision, requirement pressure, considered alternatives, and consequences. Architectural changes belong in specification. During implementation, report a proposed change as a blocker instead of editing an approved decision.
7. Validate internal paths and external citations, remove stale duplicate instructions, and keep agent-facing context small. Put detailed examples in relevant references rather than growing `AGENTS.md` into another specification.

## Completion evidence

Record changed authoritative pages, verified commands, cited source dates, and known environment limits for the phase gate. Documentation tasks normally follow tests, deletions, modifications, and additions; correct misleading instructions promptly when needed to complete current work safely.

Read [documentation patterns](references/writing.md) for examples and review checks.
