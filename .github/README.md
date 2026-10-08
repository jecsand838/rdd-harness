# Verification integration

`workflows/rdd.yml` provides the required aggregate `verify` check. Protect the workflow, controller and baseline rules with your repository's review/rules configuration or an externally required workflow. Repo-local files cannot themselves grant or enforce organization-level GitHub policy.

Commit/push the approved preparation baseline before opening phase PRs. Bootstrap CI reports harness-only status; phase CI executes frozen cumulative ordinary native checks and publishes evidence. Manual/reference-host obligations remain required at local phase/project gates.
