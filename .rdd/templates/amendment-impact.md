# Amendment impact analysis

> Authoring template. Preserve prior sealed artifacts and use a new run. Do not patch previous acceptance history.

## Reason and baselines

State whether this is a requirement change, design correction, dependency issue, or sealed-phase defect. Record prior/current requirement digests, code baseline, prior run, and observed failure when applicable.

## Requirement delta

Identify added, changed, removed, and unchanged IDs. Include changed shared vocabulary/data rules, platform matrices, and benchmark definitions. Retire IDs rather than reusing them.

## Impact closure

Trace requirements to specification sections, operations/contracts, scenarios, modules, dependencies, migrations, fixtures, benchmarks, docs, and evidence. Record reverse callers and NFR ripple effects.

## Preserved artifacts

For every retained artifact family, explain why its semantics remain valid. Distinguish reusable design reasoning from evidence that must be rerun at the new revision.

## Compatibility and migration

State intended breaking changes, contract version/tag treatment, stored-data handling, deployment effects, and recovery obligations.

## New-run work

Identify solution changes to freeze, the scope to replan, and cumulative regressions. Do not inject tasks into a sealed previous phase.
