# Todo generation: manual blog demo

Checked against this checkout and the repository's GitHub settings on 2026-10-07.
This is an operator runbook, not a record of application completion. The Todo app
has not been generated. Use an interactive Bash or Zsh terminal, run commands in
order, and stop on any failure before continuing. The Codex stages are interactive,
potentially long-running sessions.

## 1. Finish setup

The inspected Mac already has Python 3.11.9, Git, Codex 0.161.0, authenticated
Codex and GitHub sessions, Git author identity, Rust 1.99.0, the WASM target, Buf
1.73.0, and Xcode Command Line Tools. `./rdd doctor --full` reports ready. The
configured models are advertised, but paid model access is established only by
actual use: Astra/ultra for coordination, Sol/xhigh for large work and independent
review, Luna/xhigh for small work. No Turso cloud account or database server is
needed. GitHub Actions is enabled; the current user has repository admin access.

Arrange the unchanged requirements' actual verification environments before
starting. These may be needed during specification qualification, not just at
the final gate:

| Environment | Hardware | Human accessibility verification |
| --- | --- | --- |
| macOS 15, arm64 | M1, 8 GiB, internal SSD | VoiceOver |
| Windows 11 25H2, x86_64 | i5-1135G7, 16 GiB, local NVMe SSD | NVDA |
| Ubuntu 24.04, x86_64, GNOME | i5-1135G7, 16 GiB, local NVMe SSD | Orca |

The inspected development Mac is macOS 26.7 / M3 Max / 128 GB. Use it to build
and demonstrate the app, but do not report its measurements as the required M1
results. A Mac-only run cannot satisfy the current full requirements. If the
reference environments are unavailable, arrange them or explicitly amend the
requirements before specification; a local demonstration is not full acceptance.

Provide clean installation profiles without development tools, a second
unprivileged account for access tests, and an evaluator for keyboard,
screen-reader, contrast, and resizing checks. Benchmark hosts need AC power,
normal performance mode, at least 20 GiB free local storage, an active 1280×720
logical-pixel window, and no concurrent build/benchmark workload. Specification
must pin OS patches, WebViews, frontend builders, packaging tools and any signing
requirements; install/qualify those selected dependencies before freezing. Do not
preselect an unrelated frontend or install an arbitrary latest Tauri CLI.

Native prerequisites: [Tauri installation guide](https://v2.tauri.app/start/prerequisites/).
Desktop macOS can use Command Line Tools; Windows development needs C++ Build
Tools and WebView2; Linux needs the documented native libraries. These development
machines do not replace clean packaged-application installation tests.

Use a repository revision containing the reviewed release-branch support before
starting this demo. `main` is a merge-only release branch: all specification and
preparation commits stay on `codex/todo-demo-baseline`, and implementation uses
the generated phase branches. Section 8 publishes one complete release PR after
project acceptance. Release CI uses operator-pinned source and prepared-policy
commits; the prepared baseline never needs to be merged separately into `main`.
The operator needs permission to manage repository Actions variables and branch
rules. Existing merge restrictions and required checks remain in force.

```text
main
 └─ codex/todo-demo-baseline       specification + preparation
     └─ rdd/<run-id>/p01
         └─ rdd/<run-id>/p02 …    accepted phase stack
             └─ codex/rdd-release/<run-id> → release PR → main
```

## 2. Start a clean demo checkout

Use a fresh clone for a reproducible recording, then create the authoring branch
before initializing or generating run artifacts. The destination below must not
already exist; use recovery rather than cloning over a previous demo.

```sh
gh repo clone jecsand838/rdd-harness "$HOME/RustroverProjects/rdd-todo-demo"
cd "$HOME/RustroverProjects/rdd-todo-demo"
git fetch origin
git switch -c codex/todo-demo-baseline origin/main
git status --short --branch
./rdd init
./rdd status
./rdd doctor --full
./rdd selftest
```

Expect a clean `codex/todo-demo-baseline`, initialized local state, and no active
application run. The controller rejects source authoring on `main` or detached
HEAD. Harness selftests prove the controller, not Todo functionality. Normal
Codex project-trust/permission prompts still apply. Do not disable sandboxing.

For a reproducible article, record the starting commit and requirements digest:

```sh
mkdir -p .rdd/evidence/blog
git rev-parse HEAD > .rdd/evidence/blog/starting-commit.txt
shasum -a 256 requirements/requirements.md > .rdd/evidence/blog/requirements.sha256
```

## 3. Specify the complete application

Start the run once, then launch the same coordinator configuration used by the
workflow launcher with a complete demo-specific initial prompt:

```sh
./rdd start --mode regenerate
codex --model gpt-6-astra -c 'model_reasoning_effort="ultra"' '
Use $specification-workflow for the active regenerate run. Treat the entire
requirements/requirements.md as the accepted product input and preserve it.
Derive and independently review all 53 requirements, domain boundaries, local
Protobuf API/contracts, Rust UI, embedded Turso persistence, failure semantics,
platform qualification, fixtures, benchmarks, accessibility, privacy and release
evidence. Qualify and pin the complete stack before freezing. Obtain real
required native qualification evidence; identify missing environments honestly.

For NFR-QUAL-002, specify a small developer handoff at tools/todo.py with these
commands: python3 tools/todo.py setup, build, and run. Setup installs or verifies
the pinned application build tools; build produces the release desktop package;
run opens that built package on macOS, without a development server, and fails
clearly if it is missing. These are future implementation deliverables, not
existing harness commands. Keep product logic and UI behavior entirely in Rust.
Setup, build and run must preserve tracked source and a clean Git status; place
generated packages and other build outputs in Git-ignored paths.
Also specify docs/todo/development.md with exact clean build/install/verification
commands and docs/todo/verification.md with executable native/reference-host
steps, actual check IDs, receipt/log transfer, and human observation protocols.
Reuse existing tooling where possible; avoid a second task framework.
Create immediately usable qualification and evidence-transfer instructions in
docs/specs/native-verification.md during this stage, before any qualification
that needs them. The later user handoff must not be an early gate dependency.
Include a supplemental packaged smoke check of setup/build/run on this actual
macOS 26.7 / M3 Max development machine. Record its package digest separately
from the required macOS 15 / M1 qualification and benchmark evidence.

Select and qualify all additional tools now, including their trusted CI setup.
Freeze the specification only after real contract compilation and independent
review. Commit the accepted specification on codex/todo-demo-baseline. Keep all
authored artifacts on that branch. Do not implement application behavior, push
main, or merge PRs in this stage.
'
```

This explicit prompt adds a predictable developer command surface to the
release handoff; it does not supply application code or alter product behavior.
The shorter standard entry point is `./rdd workflow specification --mode regenerate`,
but do not run both launch sequences for the same stage.

Answer material specification questions and perform requested native observations.
Missing reference access can block here. Return to the terminal after freeze:

```sh
./rdd spec validate
./rdd status
git status --short
git log -1 --oneline
test -f .rdd/spec.lock.json
```

Require a frozen specification and committed, clean output before continuing.
If the session left intended changes uncommitted, review `git diff`, then
`git add -A && git commit -m "Freeze Todo specification and contracts"`.
Do not advance past an unresolved or partially frozen design.

## 4. Prepare the backlog

```sh
./rdd workflow preparation
```

The session must independently review the target tree, task DAG, ordered
verticals, phases, exact writes, and the handoff commands specified above. It
must fully groom every task and work site, obtain both independent review perspectives, freeze the plan, run `prepare`, and commit the materialized baseline. This is `preparing`, not yet an accepted handoff. Initial
test tasks need executable behavioral RED; compiler errors are not RED.

Inspect the materialized output before final preparation acceptance:

```sh
./rdd plan validate
./rdd anchors verify
./rdd status
git status --short
test -f .rdd/plan/plan.lock.json
test -f .rdd/prepared.json
cat .rdd/plan/implementation-matrix.md
```

Require clean committed output. If necessary, review and commit the intended
remaining preparation changes before continuing. The Todo app still does not
exist at this point; shells and markers describe future work.

## 5. Publish and verify the dedicated prepared baseline

The first phase must have the exact committed prepared baseline on its remote
base branch. Keep the baseline fixed once implementation starts. No application
artifacts are authored on or merged into `main` at this stage.

```sh
test "$(git branch --show-current)" = codex/todo-demo-baseline
test -z "$(git status --porcelain)"
./rdd ci --branch codex/todo-demo-baseline
./rdd export-run .rdd/evidence/prepared-run.json
rdd_prepared_sha=$(git rev-parse HEAD)
git push -u origin codex/todo-demo-baseline
```

Define this helper in your operator terminal, then wait for the `push` workflow
for this exact baseline revision. It allows time for GitHub to register the run:

```sh
rdd_wait_push_ci() {
  local rdd_ci_branch="$1"
  local rdd_ci_sha="$2"
  local rdd_ci_run=""
  local rdd_ci_attempt
  for rdd_ci_attempt in {1..24}; do
    rdd_ci_run=$(gh run list --workflow rdd.yml --event push --branch "$rdd_ci_branch" \
      --commit "$rdd_ci_sha" --limit 1 --json databaseId \
      --jq '.[0].databaseId // empty')
    if [ -n "$rdd_ci_run" ]; then
      gh run watch "$rdd_ci_run" --exit-status
      return $?
    fi
    sleep 5
  done
  printf '%s\n' 'No matching push CI run appeared; inspect GitHub Actions.'
  return 1
}
rdd_wait_push_ci codex/todo-demo-baseline "$rdd_prepared_sha"
test "$rdd_prepared_sha" = "$(git ls-remote origin refs/heads/codex/todo-demo-baseline | cut -f1)"
```

Prepared-baseline CI must pass before implementation. Obtain its preparation-readiness receipts from the trusted pinned harness route, then run `./rdd readiness preparation`, record the semantic and execution reviewers for that exact committed materialization, and run `./rdd gate preparation`. The workflow is complete only when this gate reports `prepared`. These checks verify the reviewed handoff; they do not establish application completion. Do not
push intermediate, partially frozen specification/preparation commits as a
completed baseline. Keep the published baseline and sealed phase branches fixed.

One remaining GitHub setup step is mandatory with the current adapter:
`gh pr checks --required` fails when the PR base has no server-required checks,
even if `verify` exists and passes. After baseline CI succeeds, require `verify`
on the **prepared baseline and main**, preserving existing rules:

```sh
gh api --method POST repos/jecsand838/rdd-harness/rulesets --input - <<'JSON'
{
  "name": "RDD verify on Todo baseline and release",
  "target": "branch",
  "enforcement": "active",
  "bypass_actors": [],
  "conditions": {
    "ref_name": {
      "include": ["refs/heads/codex/todo-demo-baseline", "refs/heads/main"],
      "exclude": []
    }
  },
  "rules": [{
    "type": "required_status_checks",
    "parameters": {
      "strict_required_status_checks_policy": false,
      "required_status_checks": [{"context": "verify"}]
    }
  }]
}
JSON
```

Run that creation once; on resume inspect existing rules instead of making
duplicates. The [GitHub rulesets API](https://docs.github.com/en/rest/repos/rules#create-a-repository-ruleset)
supports an exact branch condition and required status checks. For later phase
PRs, their sealed predecessor also needs that requirement. Configure each
**exact sealed predecessor** only after sealing it. Do not apply a blanket
`rdd/**` status rule: protecting a working phase branch can prevent publishing
the very commit whose PR must produce its checks. The next section authorizes
the coordinator to perform this narrowly scoped setup between phases.

## 6. Generate the app with native Goal mode

```sh
./rdd goal
{ printf '/goal '; ./rdd goal; } | pbcopy
./rdd workflow implementation
```

The clipboard contains `/goal` followed by the exact repository objective.
The launcher opens a session; it
does not itself activate native Goal mode. See the
[official Goals guide](https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex).

Before submitting the goal, send this setup instruction in the same session:

> For this demo I authorize GitHub required-check setup on accepted phase bases.
> The prepared baseline and main already require verify. After each phase is
> sealed and before starting its successor, inspect the exact sealed branch's
> active rules. If verify is
> not required, use gh api POST repos/jecsand838/rdd-harness/rulesets to create
> a uniquely named active branch ruleset. Set conditions.ref_name.include to
> only that exact refs/heads/branch, conditions.ref_name.exclude to [], and
> bypass_actors to []. Its only rule is type required_status_checks, with
> parameters.required_status_checks=[{"context":"verify"}] and
> parameters.strict_required_status_checks_policy=false.
> Preserve existing rules; never target an active/future phase or an rdd/**
> wildcard. Do not merge, retarget, or change phase source. Continue only when
> the successor PR can obtain its real required verify result.

Then paste and submit the `/goal` command. This external repository setup
does not replace the controller's phase review, check or seal requirements.

The coordinator owns phase begin, ready-task selection, isolated claims, test
RED, implementation, integrations, marker cleanup, cumulative checks,
independent review, phase gates, PR publication/verification and seals. At most
two implementors run alongside the independent reviewer. Do not run competing
claims or phase transitions from another terminal. The goal continues until
actual project acceptance or an explicit blocker/budget/permission stop.

In another terminal, inspect progress at any time:

```sh
cd "$HOME/RustroverProjects/rdd-todo-demo"
./rdd status
git log -8 --oneline
gh pr list --state open --json number,title,headRefName,baseRefName,url
gh run list --workflow rdd.yml --limit 10
```

While a phase is open, `./rdd next` shows its eligible tasks. The `status` command
is authoritative; a dashboard, worker message, or green harness test is not
application completion. Capture one real RED-to-GREEN example, the task matrix,
and a sealed phase PR for the article.

Provide actual external evidence when requested, potentially at every phase.
Use the frozen `docs/specs/native-verification.md` and check inventory, and
`docs/todo/verification.md` when its planned handoff task has completed. These
instructions must specify exact check IDs, clone/checkout/checkpoint commands, host
qualification, and receipt/raw-log transfer for the selected design. The stable
controller transfer interfaces are:

```text
./rdd check ACTUAL_FROZEN_CHECK_ID
./rdd check import ACTUAL_RECEIPT_JSON --local-host
./rdd check import ACTUAL_CI_OR_MANUAL_RECEIPT_JSON
```

These three lines document syntax, not commands to paste with those labels.
Transfer real logs to each receipt's exact `log_path`. Use identical committed
source and frozen authority on the donor host; never invent a host receipt.
Manual checks need an identified observer's actual observations. CI and local
reference-host imports have different provenance; preserve it.

The complete acceptance workload includes real Turso and packaged native
journeys, privacy/account isolation, failure recovery, capacity limits,
cross-platform backup round trips, keyboard/screen readers, and P1–P3 benchmarks
on every reference platform. P1 requires 5 warm-ups + 30 launches; P2 requires
10 warm-ups + 100 samples per operation class; P3 requires 3 warm-ups + 30 exports
and 30 restores. Process-failure cases require 20 repetitions per operation/cut
point/platform. Keep raw samples, including slow samples. Follow the full
requirements and frozen protocols for the remaining details.

## 7. Verify completion and archive the evidence

Once the coordinator reports completion, run on the final phase branch:

```sh
./rdd status
./rdd anchors verify
./rdd stack verify
./rdd gate project
python3 - <<'PY'
import json
from pathlib import Path
report = json.loads(Path('.rdd/evidence/project-validation.json').read_text())
assert report['status'] == 'passed'
assert report['application_complete'] is True
print('Accepted application commit:', report['source_commit'])
PY
```

Only `status=passed` and `application_complete=true` establish completion.
Require all tasks complete, every primary/secondary packet removed, every golden scenario explicitly executed and passing, every phase sealed, the stack
verified ready, and required ordinary/manual/reference evidence passing.

Preserve the reports, complete runtime/check logs and Git objects before merging:

```sh
rdd_final_sha=$(python3 -c 'import json; print(json.load(open(".rdd/evidence/project-validation.json"))["source_commit"])')
test "$(git rev-parse HEAD)" = "$rdd_final_sha"
rdd_archive="$HOME/RustroverProjects/rdd-todo-demo-evidence-$rdd_final_sha"
mkdir -p "$rdd_archive"
cp .rdd/evidence/project-validation.json .rdd/evidence/project-validation.md \
  .rdd/evidence/completed-run.json "$rdd_archive/"
git bundle create "$rdd_archive/accepted-source.bundle" --all
git bundle verify "$rdd_archive/accepted-source.bundle"
```

Also copy the actual delivered packages and their digests identified in the
validation report into that archive. They are build outputs, not Git source.
Runtime/evidence files are ignored deliberately; do not force-add them to Git
and create a different supposedly accepted revision.

## 8. Verify and merge one complete release PR into main

Do this only after section 7 succeeds. A separate release PR preserves the phase
stack's accepted heads and base relationships. Keep every phase PR unmerged;
do not squash/rebase phase commits, retarget them, or force-push sealed branches.

Read the two accepted identities from the project evidence, then explicitly pin
them through repository Actions variables. A branch name or PR description does
not authorize new verification policy. These variables select the prepared
policy and project-accepted source for the one current release candidate.
The subshell stops at the first failed check before any later publishing step.

```sh
(
set -e
rdd_run_id=$(python3 -c 'import json; print(json.load(open(".rdd/evidence/project-validation.json"))["run_id"])')
rdd_final_sha=$(python3 -c 'import json; print(json.load(open(".rdd/evidence/project-validation.json"))["source_commit"])')
rdd_policy_sha=$(python3 - <<'PY'
import json
from pathlib import Path
report = json.loads(Path('.rdd/evidence/project-validation.json').read_text())
plan = json.loads(Path('.rdd/plan/plan.json').read_text())
first = plan['phases'][0]['id']
assert report['status'] == 'passed' and report['application_complete'] is True
assert report['phases'][first]['base_branch'] == 'codex/todo-demo-baseline'
print(report['phases'][first]['base_sha'])
PY
)
test -z "$(git status --porcelain)"
test "$(git rev-parse HEAD)" = "$rdd_final_sha"
test "$rdd_policy_sha" = "$(git ls-remote origin refs/heads/codex/todo-demo-baseline | cut -f1)"
git merge-base --is-ancestor "$rdd_policy_sha" "$rdd_final_sha"
gh variable set RDD_RELEASE_POLICY_SHA --body "$rdd_policy_sha"
gh variable set RDD_RELEASE_SOURCE_SHA --body "$rdd_final_sha"
rdd_release_branch="codex/rdd-release/$rdd_run_id"
git branch "$rdd_release_branch" "$rdd_final_sha"
git push origin "$rdd_release_branch"
printf '%s\n' \
  "Integrate the completed and project-gated RDD Todo application." \
  "Accepted source commit: $rdd_final_sha" \
  "Reviewed prepared policy commit: $rdd_policy_sha" \
  "The original phase reviews, checks, and seals are preserved." \
  "The completed-run checkpoint and package digests are archived." \
  > .rdd/evidence/blog/release-pr.md
gh pr create --base main --head "$rdd_release_branch" \
  --title "Integrate accepted Todo application" \
  --body-file .rdd/evidence/blog/release-pr.md
gh pr checks "$rdd_release_branch" --watch --fail-fast
test "$(gh pr checks "$rdd_release_branch" --json name,bucket \
  --jq '[.[] | select(.name == "verify") | .bucket] == ["pass"]')" = true
)
```

Release CI executes the trusted `main` verifier against the separately pinned
prepared policy, checks exact source and policy commits, their ancestry, frozen
authority and completion markers, then runs all applicable contract, phase and
project checks. Missing/stale pins, a different head, policy drift or incomplete
source block the PR. It retains the distinction between hosted CI and the
archived full project gate. If GitHub has not registered checks yet, repeat the
check command after the workflow appears; an absent check is not success.

After successful checks and normal release review, merge and inspect `main`:

```sh
(
set -e
rdd_run_id=$(python3 -c 'import json; print(json.load(open(".rdd/evidence/project-validation.json"))["run_id"])')
rdd_final_sha=$(python3 -c 'import json; r=json.load(open(".rdd/evidence/project-validation.json")); assert r["status"] == "passed" and r["application_complete"] is True; print(r["source_commit"])')
rdd_release_branch="codex/rdd-release/$rdd_run_id"
gh pr checks "$rdd_release_branch" --watch --fail-fast
test "$(gh pr checks "$rdd_release_branch" --json name,bucket \
  --jq '[.[] | select(.name == "verify") | .bucket] == ["pass"]')" = true
gh pr merge "$rdd_release_branch" --merge \
  --match-head-commit "$rdd_final_sha"
git fetch origin
test -z "$(git status --porcelain)"
git switch main
git pull --ff-only origin main
git merge-base --is-ancestor "$rdd_final_sha" HEAD
git diff --exit-code "$rdd_final_sha" HEAD --
test -z "$(git status --porcelain)"
git rev-parse HEAD
rdd_wait_push_ci main "$(git rev-parse HEAD)"
)
```

If checks fail, conflicts occur, the head changes, or the tree comparison differs,
stop and investigate; do not claim that the changed application is the accepted
one. Follow the amendment rule for a defect in a sealed obligation. Because this
uses a normal merge commit, `main` can have a different SHA while containing the
exact accepted application commit and identical tracked files. Record both.

The last command waits for CI on the resulting `main` push. Redefine the section 5
helper before this block if you started a new terminal.
The archived project gate remains bound to the accepted phase revision. Main CI
is cumulative source verification, not a fresh task-history/project gate. Do not
rerun stack acceptance after intentionally landing the release and call changed
PR states a new acceptance report. Automatic branch deletion is currently
enabled; the release copy can be deleted without rewriting phase heads,
and the Git bundle retains all accepted local source history.

## 9. Launch the packaged application and record the demo

The following commands are the small handoff requested in section 3 and must
have been implemented and verified as part of the frozen plan. They do not
exist in today's boilerplate:

```sh
cd "$HOME/RustroverProjects/rdd-todo-demo"
python3 tools/todo.py setup
python3 tools/todo.py build
python3 tools/todo.py run
test -z "$(git status --porcelain)"
git status --short --branch
git log -1 --oneline
```

Use a dedicated demo OS account or the documented fresh-data procedure; do not
delete an existing personal database. Keep the packaged application open at the
end. Demonstrate:

1. Offline first launch; create tasks due yesterday/today/tomorrow and undated,
   duplicate titles, Unicode text, and a notes-only search term.
2. Edit a task, clear optional values, reject an empty title while preserving
   entered input, and demonstrate keeping/discarding an unsaved draft.
3. Complete/reopen; combine status, due-date and literal text filters; show sort
   choices, result counts, and distinct empty/no-results states.
4. Cancel deletion, then delete one duplicate while retaining the other.
5. Export while filtered, showing a complete unencrypted backup; modify data,
   cancel restore, then confirm replacement and show restored state after restart.
6. Launch a second time with a draft open; show one window and preserved input.
7. Use keyboard and VoiceOver, 200% text, offline help and version information.

These interactions illustrate the product; the archived complete verification
report supports the stronger article claim. Report the accepted application
SHA, main merge SHA, requirements digest, phase PRs, actual platforms, and package
digests. A local rebuild is a new package artifact unless its digest matches the
accepted package; retain the originally tested packages for release evidence.

## Recovery

Preserve state before interruption:

```sh
./rdd export-run .rdd/evidence/run-checkpoint.json
```

In Codex, use `/goal pause` before deliberately stopping implementation. Inspect
`git branch --show-current`, `git status --short`, and `./rdd status`. Return to
the recorded baseline or phase branch before resuming; the controller refuses
source repair on `main`, detached HEAD, or the wrong named branch. Preserve dirty
work if Git cannot switch safely; do not force-switch, reset, or discard it.
After fixing the actual issue, restore the controller and the same Codex session:

```sh
./rdd resume
./rdd status
codex resume
```

Choose the implementation session, inspect its goal, then use `/goal resume`.
Do not restart with regenerate to recover an ordinary paused run. A legacy run
whose recorded baseline is `main` remains available for inspection and export;
preserve it, then start a fresh amend/regenerate run on a dedicated baseline.
Never rewrite its recorded branch or freeze locks to relocate it. Follow controller
blockers; exhausted budgets, authority/planning defects and sealed-phase
failures may require a new specification run. Never edit SQLite, locks, receipts,
task statuses or unresolved markers by hand. If all you have is Git source,
recover the exact accepted source and matching completed-run checkpoint; source
alone does not carry runtime state. See the [workflow guide](workflow-guide.md)
and [evidence guide](evidence-guide.md).
