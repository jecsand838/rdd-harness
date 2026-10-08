# Independent review — reference-host and portable-proof closure

Decision: **PASS**, no findings. Scope: specification coherence, complete-check placement and bounded portability corrections; no phase or application acceptance.

Reviewer: independent read-only `rdd_reviewer`, `gpt-6.1-sol`, xhigh, canonical agent `/root/goal_launch_review`. Run `R20261008T085017Z-099ff9`; reviewed draft based on `79554ad2aad114d8128ff6823ce2d100b19151f6`; parent frozen specification `271089c2a7960561069989afc826d3a9c50644c51a7a6815dc7e8af2d1935d55`. The coordinator records the review supplied by that distinct reviewer; it is not a self-review.

## Exact reviewed source

| Path | SHA-256 |
| --- | --- |
| .rdd/spec.json, before adding this report binding | 36f4dc5ce07bd73d0fb6dee92b20d55eb7562b6b44a9912b8f4b6830805ef5a0 |
| docs/specs/ci-host-amendment.md | 67e6629dc55d04c9638e41ae7080a0bbbf67f696446b57c444af653d059577d6 |
| docs/specs/check-design.md | 68ee237883718f7065f361297736d703d90a049d59ff5ed1b0d1e2ff28ab4efe |
| tools/rdd/proto_traits.py | 1bad5af53b2ada80323b4d6a32f11526cea81167106b0a1b71b0603f0b841d85 |
| tools/proto-codegen/tests/test_orchestration.py | 737535320b54943e1812132d1a0dbf455c1ab0d1ceb5a07ffca3e54740bb7ae9 |
| .github/workflows/rdd.yml | c6997e8688f05e5c04d840f897b92ce1df77c7ece40593cde5c0be672276c4a4 |

The reviewer independently recomputed these hashes, validated all 53 requirements, six modules, 73 scenarios and 28 checks, and ran `git diff --check`. Requirements retain SHA-256 `d038897476ed992b7c04bca4d2641790cd4f828f3f305529ba74a14655d0e2fe`. All 84 qualification input hashes, six generated files and unrelated manifest semantics are unchanged. Exactly 13 host profiles and six platform lists change; every check command/kind/budget/metric/RED pattern and scenario mapping remains intact. The complete classification has 22 reference checks and six ordinary checks. The remaining ordinary prerequisites fit existing hosted provisioning; no further concrete portability defect was found in the bounded audit.

`C-INSTANCE` remains the entire disposable Darwin lease/nonce/crash primitive and cannot satisfy application FR-024. `C-ARCH` retains its complete portable source/dependency/provider/consumer/command inventory and forbidden fixtures; its future evaluator is not yet implemented. Actual native/application/package/full-report requirements remain qualified-host obligations, with hosted `pending_external` never a pass.

## Examined and independently reproduced evidence

The reviewer ran the unchanged input proof: 84 inputs and four fixtures with 10,000 records each. An in-memory replay against original driver source at the reviewed base fails the new metadata regression specifically with `.rdd-generated.json` drift; the current binary writer passes, including rejection of intentionally CRLF-corrupted frozen metadata. No repository source or controller state was changed by review.

All 12 raw real contract logs in `.rdd/runtime/contracts-6u9w4gp3/` have matching hashes: native/WASM compilation, valid provider, actual invalid-signature E0050 and zero generated-byte drift. Full harness regression `.rdd/runtime/ci-host-selftest.log` has SHA-256 `4b05a45e59e4a596c8df1d21cfa16283c073bc4b0baa28c0bc570cd6f687e546`: 241 tests in 132.387 seconds, one opt-in installed-Codex smoke skip, return code zero, scope `harness_regression`, `application_complete=false`.

The actual Python 3.11.9 UTF-8 startup proof and both raw logs match `.rdd/runtime/ci-portability-audit/utf8-policy-result.json`, SHA-256 `926a549dae099ce0c3746ac726c5e70f8062d028fed77e774c656b133f24d4b0`. Controlled C locale with UTF-8 off fails D1 decoding; changing only `PYTHONUTF8=1` passes the complete unchanged helper. Its source SHA-256 remains `94401017afe96b7fd64ff936a45412c0b4aa2918d912fdc29dda41cd3c90e747`. This is actual local subprocess evidence, not a hosted Windows/locale observation.

The supported host qualifier binds measured observations SHA-256 `c39e904099bb3bdfa92eb47853f6269ffbc9d04d396ab561fdfa2ab6e8a65562`. The independent 23-command root packet at `.rdd/runtime/reference-host-observation/20261008T090042Z-9972d917/observations.json`, SHA-256 `31fed9f5756550542e63b872d4940c187ab6bc1077705221a758858256c3be4d`, corroborates exact OS/build, arm64 M3 Max/128 GiB, WebKit, APFS SSD, pinned tools and current AC/space. These establish identity/prerequisites only. Actual benchmark setup, calibration/window conditions and human/application observations remain due.

## Required continuation

Add only this report's document binding, then execute all seven current-source specification proofs and controller freeze. Rebind and independently review preparation, run the controller, publish the exact prepared baseline, and require fresh three-platform hosted CI before phase opening. All native/manual/benchmark/phase/PR/project obligations remain mandatory. This review does not substitute for any remaining execution or the final project gate.
