# Preparation blocker: absent sidecar targets rejected by frozen policy

Run: `R20261008T061841Z-666065`. Frozen spec: `924507a8dc3876585af71d1065d94fa9131c56da15a6c6e8961d2a9dae47eaa7`. Requirements and all frozen contracts/generated files remain unchanged. The draft is not frozen or prepared.

## Reproduced failure

After removing invalid empty-file reservations and assigning sidecars to every affected task, `./rdd plan validate` exits 1:

```json
{"status":"failed","kind":"validation","error":"Missing file Cargo.toml needs an explicit preparation shell"}
```

The same rule applies to absent `apps/desktop/tauri.conf.json` and `apps/desktop/capabilities/main.json`. An empty file is invalid JSON; creating substantive valid application configuration during preparation violates the approved comment-only shell boundary. Invalid icon/manifest reservations are likewise not a workaround.

## Conflicting policy evidence

- `.agents/skills/preparation-workflow/SKILL.md`, Marker and shell rules: use sidecars for noncommentable files and do not insert malformed content into Cargo manifests, capability JSON or schemas to reserve a path. An unresolved task may have a registered sidecar while its target does not exist.
- `docs/harness/workflow-guide.md`, Stage two: use sidecars for editable noncommentable files; do not create bogus JSON or manifests merely to reserve paths.
- `tools/rdd/artifacts.py:220–221`: every absent task write must have an explicit shell, with no sidecar exception.
- `tools/rdd/artifacts.py:319–328`: materialization unconditionally writes every absent shell, even empty content.
- `tools/rdd/artifacts.py:306–309`: sidecar mode changes only marker destination to `.rdd/plan/anchors/Txxx.md`.
- `tools/rdd/artifacts.py:363–393`: anchor verification already tolerates absent target files and verifies their task markers; validation prevents that state from being prepared.
- `.rdd/schemas/plan.schema.json`: no deferred-file materialization field exists.
- `.rdd/spec.lock.json` includes the controller and schema policy inventories; editing the controller under the current specification would invalidate frozen input digests.

Affected tasks: T001, T004, T005, T006, T010 and T012. These contain the approved manifests/locks/configuration/icon/SQL targets. The inability to create the first runnable harness and application entry affects all downstream tasks and all53Must requirement closure; it is a preparation-policy defect, not a missing Todo behavior decision.

## Concrete repair proposal for a new specification/policy run

1. In `plan_validate`, permit a missing declared write without a shell when its task has `anchor.mode=sidecar`; retain exact target inventory, protected-path checks, ownership and graph checks. Missing inline anchors still need a safe explicit source shell.
2. Leave `materialize` creating only the manifest's explicitly approved comment-only shells, then the existing task sidecars. Do not synthesize empty JSON, lock, manifest or binary files. Do not introduce any product configuration or behavior here.
3. Add harness regression tests proving that a sidecar task with multiple absent manifests/JSON/locks/binary writes validates and prepares exactly its sidecar, preserves target absence and passes anchor verification. Retain tests that missing inline targets fail, protected paths remain unwritable, malformed/noncommentable shell content fails and unknown/stale/duplicate markers are rejected.
4. Qualify that controller-policy change in a new specification amendment/run and freeze new policy identities, keeping requirements and canonical/generated contract bytes unchanged. Re-run required contract proofs; preserve the current run/export and accepted history.
5. Reuse this reviewed draft graph, update its spec digest through the supported preparation workflow, revalidate/freeze it, run real `prepare` and `anchors verify`, then commit the actual prepared baseline.

The minimum authorization needed is a narrowly scoped new specification/policy amendment allowing safe absent-file sidecars and its regression tests, followed by resumed preparation. It does not authorize a Todo design change, production implementation, merge or deployment. Until that authorization and new freeze, do not edit protected policy, create invalid reservations, freeze this plan, or label the draft commit a prepared baseline.
