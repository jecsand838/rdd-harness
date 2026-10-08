# Independent preparation review

Decision: **changes_requested**. One unresolved controller-policy mismatch prevents plan freeze and preparation. This is a preparation review, not phase or application acceptance.

Reviewer: independent `rdd_reviewer`, `gpt-6.1-sol`, xhigh; session/task `/root/prepare/review_plan`. Run: `R20261008T061841Z-666065`. Accepted source HEAD: `9ecd6063a7064e8dca83a31565f803b15c5d90fb`. There is no active implementation phase or candidate application commit.

The reviewed uncommitted `.rdd/plan/plan.json` has SHA-256 `47281a014616141badf5a586484d7cd6514ffe029571681a39a015bc0618e566`. It consumes frozen specification `924507a8dc3876585af71d1065d94fa9131c56da15a6c6e8961d2a9dae47eaa7` and unchanged requirement digest `d038897476ed992b7c04bca4d2641790cd4f828f3f305529ba74a14655d0e2fe`.

The six reviewed supporting artifacts match their bindings in that candidate:

| Artifact under `.rdd/plan/` | SHA-256 |
| --- | --- |
| planning-notes.md | f6df2c992bdd5f3ee7352fd2e5ffde28dd0073df273fae0c266e898cc988bcd3 |
| target-tree.md | df0b57de5d7c2a62fadea8c6fb11b9e0180d13b54086a44708a5e427797611d1 |
| capabilities.json | 2c4c108dbc73bc1ccbc84b457a1821c94aeaf5ed27be0997779627cf1a8cdb60 |
| traceability.json | 2abaf0ee1d984bc66e748d0120eb545eb53602b8894a69e9f0e7953c83ff0f14 |
| scenario-matrix.md | b15b14c11b51fa16b08a11154a0d45afc4a8986a2b9063b99397539f12bb9f37 |
| preparation-blocker.md | 40701e7edab5f02eb60d2e9f09d7c7283abcfaa2ed85656aca116ead70f6610e |

## Evidence examined

Read `AGENTS.md`, requirements, frozen solution/decisions, operation and scenario inventories, generated contract boundaries, check-design/quality/dependency protocols, relevant preparation/graph/phase/reuse skills, plan schema, candidate tasks/write sets, supporting artifacts, and controller validation/materialization/evidence code. `./rdd doctor` reported prerequisites ready; that establishes no application result.

Independent schema, graph, category, producer ancestry, vertical order and write-overlap checks found no additional structural issue. The draft has 21 tasks, seven verticals, one complete-product phase, 103 target paths, 60 comment-only shells and six sidecar-anchored tasks. All 53 requirements, 73 frozen scenarios and 137 requirement/scenario pairs are represented; all 27 checks retain their frozen commands and evidence obligations. All 169 files recorded in `spec.lock.json` independently matched their hashes. No frozen file is a task write.

The whole-product phase avoids inventing unspecified intermediate operation availability. T001 establishes the runnable real native-boundary scaffold, and each tests task requires its own admissible behavioral RED. T010 claims only source wiring before the addition owners; all compilation, persistence, UI, packaging, documentation and NFR obligations join before P01 acceptance. Shared writes are serialized. Planned actual-engine recovery, external delivered-package observers, human/platform evidence and benchmark preconditions remain mandatory.

Verified draft corrections include explicit standalone child fixtures instead of accidental Cargo binary discovery; declared qualified icon reuse; fixed light appearance; complete operation-provider/prerequisite matrix links; bundled third-party notices; and pre-gate handoff evidence that excludes its own receipt and later controller closure artifacts. These are reviewed plan corrections, not implementation results.

## Unresolved finding PREP-R1

Severity: **blocker**. Scope: preparation materialization; tasks T001/T004/T005/T006/T010/T012. Requirement impact: NFR-TECH-004 and NFR-SEC-002 cannot proceed to their planned manifest/configuration and build verification. Affected source/policy locations: `tools/rdd/artifacts.py:220`, `tools/rdd/artifacts.py:324`, `.agents/skills/preparation-workflow/SKILL.md:30` and `:34`.

The skill requires safe sidecars for unsafe comment formats, including JSON, lockfiles and binaries, and explicitly says: “Never insert malformed content into `Cargo.toml`, capability JSON, or schema files to reserve a path.” The controller instead requires every absent declared write to have a shell, independently of the task's sidecar mode. Its materializer physically writes every declared shell. Empty `apps/desktop/tauri.conf.json` and `apps/desktop/capabilities/main.json` would be invalid JSON; producing fake valid configuration during preparation is also prohibited. Sidecar anchors do not currently avoid those file writes.

The corrected draft removes the 18 unsafe reservations and leaves those targets absent. Actual `./rdd plan validate` exits 1 with:

```json
{"status":"failed","kind":"validation","error":"Missing file Cargo.toml needs an explicit preparation shell"}
```

This demonstrates the controller cannot validate the safe absent-file plan. The earlier all-shell draft's structural validation did not establish acceptable preparation behavior. No plan freeze, shell/anchor materialization, prepared receipt or application acceptance is justified.

Corrective action: qualify a narrowly scoped specification/policy amendment that supports absent unsafe-format write targets represented by task sidecars, with regression evidence for validation, materialization, anchors and retained protection of frozen paths. Preserve requirements, contracts and generated bytes. The controller is a frozen policy input, so do not change it inside this preparation run or bypass its checks. Then independently re-review, validate, freeze, prepare, verify anchors and commit the actual prepared baseline.

The coordinator has recorded the planning blocker; current controller state is `blocked`, with no frozen plan or implementation task state. This finding remains unresolved. Adding only this report's digest to the draft may be verified as an evidence-binding change; any other candidate change requires renewed review. Neither that insertion nor an unapplied proposed repair converts this verdict into a pass.
