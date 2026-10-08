# Evidence and qualified checks

An observation is accepted only for its exact source, frozen requirement/specification/plan, check command, native platform, required host profile and outcome. A hash binds bytes. It does not establish that an observer was honest or that a model actually used the stated account. The developer controls the local trust boundary.

## Defining checks during specification

Every check in `.rdd/spec.json` specifies its command, platform/environment, input resources, host profile, timeout, and applicable RED, metric and scenario-result protocols. The JSON schema and semantic validator reject missing fields, unknown references and unsupported forms.

`argv` is a list of exact process arguments; no shell is involved. The single portable substitution `{python}` becomes the running Python interpreter. Use reviewed source scripts for multi-step processes. They must produce a nonzero exit when assertions fail. Do not bury accepted inputs in ignored source folders or dynamically weaken the protocol.

`platforms: ["any"]` means one supported host can discharge this check. A list such as `["linux", "windows", "macos"]` means the phase/project gate requires a receipt for **each** named native platform. A single Linux result cannot satisfy it. The `manual` kind has an empty `argv`; observers supply receipts instead of running a pretend verification command.

Checks read committed source and write only build/runtime/evidence outputs. The executor captures source identity before and after, so a test that changes source cannot give accepted evidence. Check timeouts and truncated output are inconclusive, never successful RED.

## Behavioral RED

A tests-category task integrates its test commit first, then runs its registered check with `--expect fail --task T001`. Its `red_pattern` must match the specific failed behavioral assertion, for example a named assertion about a saved task being absent after an acknowledged save. Do not use a generic `error` or `failed` substring.

The executor requires a positive nonzero exit, a matching frozen assertion, and no compiler/import/syntax/missing-tool failure. Imported RED is evaluated again from the raw log. The test must fail for the intended missing behavior. Every tests task needs behavioral RED; there is no standalone green-bootstrap exemption.

An initial test task may include minimum compilable scaffolding and typed boundary stubs that explicitly return an unimplemented outcome. The assertions must execute and fail on the unmet behavior, and later production tasks replace those stubs. The scaffolding cannot pass feature acceptance or implement the feature in advance. The independent reviewer verifies that final tests exercise real providers and actual storage/IPC boundaries.

## Benchmarks

The benchmark process prints exactly one JSON object to stdout. Put progress or diagnostic text on stderr. Example shape:

```json
{
  "errors": 0,
  "samples": {"interaction_latency": [13.0, 14.0, 16.0, 12.0]},
  "units": {"interaction_latency": "ms"},
  "environment": {
    "host_profile": "todo-reference-linux-v1",
    "cpu": "record the actual CPU",
    "memory_bytes": 17179869184,
    "build": "release",
    "dataset": "the frozen fixture identity"
  }
}
```

This short illustrative sample is not an accepted Todo benchmark. The real protocol freezes workload size, seed, warmup, measured scope, minimum samples, supported hardware, sampling rules and thresholds under the non-functional requirements.

Each machine limit names the raw sample series, statistic (`p95`, `p50`, `min`, `max`, `mean`), unit, minimum sample count, limit and comparison (`lte`/`gte`). The controller independently evaluates raw numbers and rejects duplicate JSON keys, nonfinite numbers, wrong units, too few samples or a nonzero error count. It uses nearest-rank percentiles: sorted sample at index `ceil(q * n) - 1`. Freeze that convention in the benchmark protocol.

For a check with `host_profile`, create `.rdd/runtime/host.json` on its actual qualified host:

```json
{
  "profile": "todo-reference-linux-v1",
  "platform": "linux",
  "qualification": {
    "protocol": "link to the frozen qualification protocol",
    "observer": "identify the person or trusted runner",
    "evidence": "actual hardware, OS, power mode, calibration and setup observations"
  }
}
```

The controller requires matching host/platform/profile and a nonempty qualification, and binds the host snapshot to the raw log and receipt. It cannot infer reference-machine equivalence from an arbitrary self-entered string. The independent reviewer checks the actual qualification evidence. Do not create a fictional profile to make a shared runner pass.

## Check receipts and CI transfer

`./rdd check CHECK_ID` writes a receipt and raw log under `.rdd/evidence/checks/`. Receipt fields are defined in `.rdd/schemas/evidence.schema.json`; use the actual generated receipt rather than reconstructing its observations in prose. Evidence IDs are safe filename identifiers, usually controller-generated UUIDs.

Hosted CI publishes `ci.json`, ordinary check receipts/logs and its toolchain receipt. It never declares project completion. Download artifacts from the actual PR check run, verify its source commit, and stage each raw log at the receipt's exact repository-relative `log_path`. Then import its receipt:

```sh
./rdd check import .rdd/runtime/downloaded-ci/CHECK_RECEIPT.json
```

An import must have `origin: "ci"`, identify its actual observer/run URL under `https://github.com/`, match the frozen command and exact source/spec/plan, and carry its unmodified matching raw log. A source change after CI makes old receipts stale. The current implementation validates recorded provenance and content; it does not independently attest a downloaded Actions artifact signature. Only import artifacts from your trusted workflow and repository.

Preparation acceptance additionally queries GitHub for the exact candidate run and attempt, successful verifier jobs, independently selected harness variable and identical candidate/trusted workflow bytes. These checks use GitHub's [workflow run API](https://docs.github.com/en/rest/actions/workflow-runs#get-a-workflow-run), [attempt job API](https://docs.github.com/en/rest/actions/workflow-jobs#list-jobs-for-a-workflow-run-attempt), and [repository variable API](https://docs.github.com/en/rest/actions/variables#get-a-repository-variable). A plausible URL or locally asserted green report cannot establish preparation CI success.

For evidence executed by this controller on a separate native/reference host, preserve its `origin: "local"` and transfer its real raw log. Import with `./rdd check import FILE --local-host`. This explicit route records the transfer in the run audit; it does not turn a self-entered host label into an attestation. Use the actual required platform and qualified hardware.

Before specification freeze, the same check/import machinery accepts the declared contract and stage-readiness proofs. They bind a complete draft to its prospective specification-lock digest, with `phase: null` and `plan_digest: null`. Commit the draft and transfer it with an exported run checkpoint to the required native qualification hosts. `spec freeze` checks every declared native platform and reuses only matching current-source receipts; missing platforms block the freeze. This supports the supplied requirements' runtime/database/UI/packaging qualification without pretending that Linux proves Windows or macOS.

Logs containing sensitive task/user data are a product defect under the supplied privacy requirements. Use synthetic fixtures and the logging skill. The controller does not record environment variables or authentication credentials.

## Manual observations

Manual checks require actual observations by an identified evaluator. This includes screen-reader behavior and any explicitly manual native verification. The raw log is a JSON document with this structure:

```json
{
  "decision": "pass",
  "protocol": "spec:<SPEC_DIGEST>#check:<CHECK_ID>",
  "observations": [
    "Actual steps, environment and observed outcomes.",
    "Any limitations, deviations or material conditions."
  ]
}
```

Replace the angle-bracket tokens with the exact current specification digest and frozen check ID. The `protocol` string must match that identity. The corresponding receipt uses `origin: "manual"`, the actual actor, native platform, source/spec/plan digests and raw-log hash, with `command: []`, `expectation: "pass"`, `outcome: "pass"`, and `returncode: 0`. Follow the full evidence schema for the remaining fields.

`observations` may be a nonempty string or a nonempty list of nonempty strings. A check box without written findings is not sufficient. The harness can enforce record completeness and identity; it cannot perform the human observation by accepting a label.

## Workflow readiness and independent review

Register actual authors with `./rdd author record --stage STAGE --session-id ID`; the manifest author list must match the registered stage authors. Run `./rdd readiness specification`, `./rdd readiness plan` or `./rdd readiness preparation` for the appropriate candidate. These use the existing command/log/receipt infrastructure with stage-bound identities. Baseline tools, facilities, fixtures and evidence-transfer routes require actual probes. Future implementation resources require correctly ordered producer tasks; readiness does not implement the product early.

Two distinct reviewer sessions record `semantic` and `execution` perspectives through `./rdd review record FILE`. Both must be independent of the registered authors, inspect the same exact candidate and required raw evidence, and approve with zero unresolved findings. Use the stage-review schema for complete fields. Session/model provenance is an explicit runtime record, not an authenticated attestation. Preserve previous findings and reviewer-verified resolutions across iterations.

`spec freeze` and `plan freeze` consume the corresponding approvals and proofs. After `prepare`, commit the actual packets, shells and matrix before final preparation readiness and review. Obtain real clean-checkout CI and required native prerequisite evidence; missing local receipts cannot magically exist in a hosted checkout. `gate preparation` alone grants `prepared` status and binds the exact committed baseline.

Review, readiness and gate outputs are excluded from the candidate they certify by the controller's explicit inventory rules. Do not add ignore paths to conceal unreviewed source or create a report hash that recursively includes itself. The P01 branch must start from the accepted preparation revision; later phases retain their sealed predecessor rule.

## Explicit golden scenario results

A check with `scenario_ids` writes its declared `results_path` beneath `.rdd/evidence/results/`. The runner must derive individual outcomes from assertions that actually executed. Its JSON result has this form:

```json
{"scenarios": [{"id": "S1", "outcome": "pass"}]}
```

The result must contain exactly the declared scenario IDs, each once. The executor embeds the raw result in the hashed check log. Manual checks put the same entries in `scenario_results` alongside their actual protocol and observations. Use the actual frozen IDs; the example is not evidence.

Gate validation joins these results to the frozen scenario/check mapping. Required scenarios that were omitted, skipped, filtered, duplicated or failed cannot be covered by an aggregate zero exit code. Preserve each result's source/check/log binding and the relevant assertion evidence.

## Independent phase review

Obtain the candidate source commit/digest from `./rdd status` after source and marker cleanup are committed. The independent reviewer reads the cumulative receipts and returns JSON matching `review.schema.json`. It must use the configured `rdd_reviewer` role/model and a session distinct from implementors.

The review covers requirement completeness, actual boundary usage, phase closure, test validity, privacy/security, idiomatic Rust/Tauri/Turso, code/spec bloat, reuse decisions, documentation and raw benchmark protocols. It references every cumulative check. Unresolved blocking/high/medium findings prevent the phase gate. Low findings remain visible in the accepted review/report; do not erase them.

Record the review with `./rdd review record FILE`, then `./rdd gate phase P01`. A later source change invalidates the review and gate. Live progress review occurs throughout implementation; the final phase gate is the acceptance point.

## Artifacts and retention

Runtime and evidence are ignored by Git so that writing an observation cannot change the source revision it describes. Use `export-run` before moving or deleting a working checkout. The completed-run checkpoint contains run state, raw check logs and the final reports. Actual source, frozen artifacts, worker branches and any large external datasets must be preserved separately.

Keep final validation bound to the tested commit. Copying its report into versioned project documentation creates a later documentation commit and does not retroactively change the accepted revision. Do not call that later revision tested unless its relevant verification is rerun.
