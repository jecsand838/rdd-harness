# Independent review — PREP-POLICY-001

Decision: **pass for the narrow specification/policy amendment**. No unresolved finding was identified in this scope. This review does not establish preparation completion or Todo application acceptance.

Reviewer: independent `rdd_reviewer`, `gpt-6.1-sol`, xhigh; session `/root/prepare/review_plan`. Run `R20261008T074537Z-459de7` starts from `d3678ac039ec75a507044cb9cabf1bcac6dbf7af`, with parent specification `924507a8dc3876585af71d1065d94fa9131c56da15a6c6e8961d2a9dae47eaa7`.

## Exact candidate and scope

| Reviewed artifact | SHA-256 |
| --- | --- |
| `.rdd/spec.json` before adding this review to its documents inventory | 70f7a8f163d4103fba3837b44d3097ddd9eb179deace792278f5db62630e12cc |
| `docs/specs/preparation-policy-amendment.md` | 774d9863a52b419d61e509242e900eee3d08da3a62a6fc2903392355f10198c8 |
| `tools/rdd/artifacts.py` | cc4af9315587ee93c17e25c8f16534eef96b0b28a4893b7196858e176e42bd18 |
| `tests/harness/test_artifacts.py` | 1d7fc8d9bbf7210c49691b85b62835bef87488d6db87a6044a0e46fd3cf8b7d2 |

Reviewed repository authority, the archived prior freeze and blocked plan, current amendment manifest/document, actual two-file repair diff, validator/materializer/anchor code, regression assertions, and unchanged product inventories. Adding only this file's path to the manifest's documents inventory is the expected review-binding change. Any substantive change to the reviewed policy, tests, amendment or product inventories requires renewed review.

## Findings and evidence

The implementation changes one missing-file condition: a task with a sidecar may reserve its exact absent declared writes without shells. Earlier protected-path and target-inventory checks remain in place; safe-path validation, anchor-in-write validation, graph/category/coverage enforcement and missing-inline-shell refusal are preserved. Materialization remains unchanged and creates only declared shells and task projections. The sidecar exception supplies no business behavior or new permission to modify frozen inputs.

Independently executed `python3 -m unittest tests.harness.test_artifacts.GraphTests -v`: **19 tests passed**. The new positive case covers multiple absent Cargo/JSON/lock/binary targets, actual sidecar creation, retained target absence, anchor verification and repeated idempotent materialization. The negative case rejects absent contract, generated and controller-policy writes. Existing category, coverage, missing-inline-shell and shell-no-behavior assertions remain active.

Independently executed the new check's complete command, `python3 -m unittest discover -s tests/harness -p test_artifacts.py -v`: **50 tests passed**. It also exercises path escape/symlinks, restrictive atomic writes, marker drift/reconciliation, source preservation, schema and frozen-identity handling. The command selects a real nonzero assertion inventory and returns failure on regression.

An additional independent subprocess loaded the original validator bytes from commit `d3678ac` without changing repository files and ran the newly added positive sidecar case. It reached the validator and failed with `Missing file app/Cargo.toml needs an explicit preparation shell`, reproducing the prior behavior. Current policy passes that same case. This is a controller-policy behavior comparison, not product RED evidence.

The repair worker reported an actual captured `./rdd selftest` tool run: 240 tests in 132.727 seconds, `OK (skipped=1)`, return code 0, scope `harness_regression`, and `application_complete=false`. The one skip was the optional `RDD_CODEX_SMOKE` test with its opt-in variable unset. That broader run was not independently repeated here and has no standalone raw-log file; its captured tool observation is supporting evidence. The directly executed 19/50-test results above and the forthcoming persisted `C-POLICY-SIDECARS` controller proof are the independently examined policy checks. No skipped application or platform result is treated as passing.

## Retained obligations and freeze conditions

Direct comparison with the archived prior manifest found unchanged requirements digest, canonical/generated inventories, decisions, six modules, 73 scenarios, requirement mappings, project check IDs and all 27 prior check definitions. Comparison against the prior frozen-file hashes found only the authorized manifest and two repaired harness files changed; every other previously frozen file remained exact. Requirements SHA-256 remains `d038897476ed992b7c04bca4d2641790cd4f828f3f305529ba74a14655d0e2fe`. The impact inventory covers every intended write from the still-unimplemented blocked plan.

The added `C-POLICY-SIDECARS` proof supplements the six retained contract checks. It neither changes Todo behavior nor replaces product verification. Actual `./rdd spec validate` passed with 53 requirements, six modules, 73 scenarios and 28 checks. Specification freeze must still execute all seven declared contract-policy proofs and bind their fresh results. Preparation then requires a newly rebound, independently reviewed and validated plan, real controller materialization, anchor verification and an actual committed prepared baseline.

The earlier blocked run, review and observations remain historical records. This review approves the amended policy's coherence; it does not alter their recorded disposition. Native/package/benchmark/privacy/accessibility and all other Todo acceptance obligations remain unperformed.
