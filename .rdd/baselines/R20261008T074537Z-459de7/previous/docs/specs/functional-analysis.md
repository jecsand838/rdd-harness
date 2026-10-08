# Functional analysis

Scope: active regeneration run `R20261008T061841Z-666065`; baseline commit `151aa83117a87e886c076b07ac0599f3347d2f24`. Canonical input: `requirements/requirements.md`, TODO-REQ 0.2.0, revision 2, all Must. Requirement-file SHA-256: `d038897476ed992b7c04bca4d2641790cd4f828f3f305529ba74a14655d0e2fe`. Analysis accessed 2026-10-08. This document defines functional semantics and independent fixtures; the dependency decision and contract documents own qualified versions and wire inventories.

## Evidence and limits

Documented requirement facts: Sections 2-4 define one per-account offline collection, FR-001..FR-025, data vocabulary and excluded features. Sections 6-7 define the sole supported Mac, maximum-field capacity cases and actual-engine/process-failure evidence. Runtime observation: `./rdd status` identifies this run as specification with no tasks/phases/frozen spec; Git HEAD equals the baseline. Repository observation: `apps/README.md`, `modules/README.md`, `docs/specs/README.md` and the source inventory contain no Todo implementation; `contracts/rdd/v1/harness.proto` is only a qualification fixture. These observations establish no application behavior. No dependency capability or measured application performance is claimed here.

Primary local sources: `requirements/requirements.md` (version 0.2.0/revision 2, accessed 2026-10-08; supports every normative behavioral claim), `AGENTS.md` (baseline commit, same access date; supports authority/scope), `.rdd/schemas/spec.schema.json` (schema version 1, same access date; supports scenario shape), and controller status/Git command outputs (this run/commit; establish current state only). There are no external-source claims in this analysis; current dependency/API claims belong to the separate qualification record.

## Ownership and semantic authority

`solution.md` owns the accepted module graph, representations and state transitions. This independent analysis contributes the scenario inventory and the explicit Q1 reference oracle below. The module split was selected over per-field/per-operation modules because capacity, replacement and task transitions share one cohesive invariant owner.

## Independent small query fixture Q1

Fixture IDs are numeric suffixes padded to 32 lowercase hex digits. Today is 2028-02-29. Created times T0..T4 are 2028-02-20T00:00:00.000000000Z through 2028-02-24T00:00:00.000000000Z. Every Open record has absent completed time and updated time equal to its created time. Every Completed record has completed time 2028-02-25T00:00:00.000000000Z and updated time equal to that instant, except record 03 whose legitimate subsequent clock-corrected edit has updated time 2028-02-24T00:00:00.000000000Z. Initial text below is literal stored text; record 06 uses decomposed e plus U+0301. Table notes marked empty mean the empty string; backslash escapes describe the exact stored code points.

| ID suffix | Status | Due | Created | Title | Notes |
|---|---|---|---|---|---|
| 01 | Open | 2028-02-28 | T1 | Alpha | café |
| 02 | Open | 2028-02-29 | T2 | Beta | Straße |
| 03 | Completed | 2028-02-29 | T2 | CAFÉ | résumé |
| 04 | Completed | 2028-02-28 | T3 | punctuation [a.*%_] | empty |
| 05 | Open | absent | T2 | Echo | notes-only needle |
| 06 | Open | 2028-03-01 | T3 | e\u0301clair | empty |
| 07 | Completed | absent | T1 | SIGMA | Σςσ |
| 08 | Open | 2028-02-29 | T4 | Turkish I | Istanbul |
| 09 | Open | 2028-03-01 | T4 | Turkish dotted İ | i\u0307 |
| 0a | Open | absent | T0 | tabs a\tb | empty |

Authored oracle sets: Open={01,02,05,06,08,09,0a}; Completed={03,04,07}; All={01..09,0a}; All/Today={02,03,08}; All/Overdue={01}; All/NoDate={05,07,0a}; Completed/Overdue={}. The cross-product status/date/search matrix is computed independently from these declared row facts, never by the product evaluator. Expected All order: newest [08,09,04,06,02,03,05,01,07,0a]; oldest [0a,01,07,02,03,05,04,06,08,09]; earliest due [04,01,08,02,03,09,06,05,07,0a]. Default Open order is [08,09,06,02,05,01,0a].

Exact search oracles: trimmed STRASSE->{02}; café->{01,03}; cafe->{}; canonical-equivalent éclair->{06}; needle->{05}; literal [a.*%_]->{04}; résumé->{03}; resume->{}. Isolated fold fixture H1 uses candidate title values I, ı, İ, i plus U+0307: query i matches I/İ/i+dot but not dotless ı; query İ matches İ/i+dot; query ı matches only dotless ı. Isolated sigma fixture matches Σ/ς/σ under default full folding. Freeze those exact transformed constants under the qualified Unicode version.

At local Today=2028-03-01, All/Today={06,09} and All/Overdue={01,02,08}. No stored due date changes. D1, capacity-maximum fixtures and benchmark protocols remain separate from Q1 and must not derive their expected sets from production implementations.

## Evidence obligations and unresolved limits

The `.rdd/spec.json` scenario inventory supplies one golden scenario for each FR plus explicit negative/boundary/failure scenarios. Descriptions name fixtures, stimulus, independent oracle and retained evidence. FUNCTIONAL and QUERY cover real approved native/domain behavior; BACKUP and RECOVERY must include actual embedded Turso, selected local files and fresh-profile round trips. LIFECYCLE includes delivered-package launch/close/single-instance/help. Checks may additionally use instrumented same-revision builds for deterministic barriers, with that distinction recorded; instrumentation is not delivered-package evidence.

Process failure tests use 20 repetitions per before-commit/pending-commit/after-ack cut for each of create/edit/complete/reopen/delete and whole restore on the supported Mac. The ledger is external to the killed process. Every acknowledged operation belongs to reopened sequential history; only the terminal unacknowledged operation may be wholly present/absent. Power loss, OS/device failure and hostile same-account/external database changes remain outside the verified model.

No Todo application tests have run; scenario expectations define future acceptance, rather than passing product results. The dependency and filesystem qualification records report the separate actual specification experiments. Native/package/VoiceOver evidence is required on macOS 26.7 build 25G229 arm64, M3 Max/128 GiB; other hosts cannot stand in for it. Requirements changes or unresolved contract conflicts must be resolved in this specification run before freezing.
