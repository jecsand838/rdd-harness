---
name: rdd-harness-reductive-repair-diff
description: Produce an isolated, complete unified patch and detailed plan for an audited RDD harness repair whose aggregate text-line delta is negative. Use for repair proposals; never apply to the user's working tree.
---

# RDD harness reductive repair diff

Prepare a reviewable candidate without applying it to the user's working tree. Consume a current [rdd-harness-audit](../rdd-harness-audit/SKILL.md) report; invoke audit if absent or stale. Refresh [rdd-harness-research](../rdd-harness-research/SKILL.md) for selected findings and techniques. Use [context-integrity](../context-integrity/SKILL.md) and [reuse-analysis](../reuse-analysis/SKILL.md), referencing canonical policy rather than copying it.

## Bound and identify the candidate

Select evidenced finding IDs within the requested scope. Record the exact base commit and comparison basis, staged/unstaged/untracked input manifest and content hashes, relevant run/spec/plan/policy identities, and preexisting failures. Preserve unrelated dirty work. A merge-base comparison is not necessarily the input to which the patch will apply.

Check active-run protection before editing even a disposable candidate. Never change requirements, frozen specs/contracts/generated bindings, bound skills/verifiers/gate policy, task/phase plans, controller receipts, or accepted history to make the repair pass. Route incompatible repair through [amend-requirements](../amend-requirements/SKILL.md) and leave affected work blocked. Without `.rdd/run.json`, maintenance may proceed without run initialization or fabricated receipts.

Create the candidate in an isolated worktree or disposable copy of that exact input, including relevant dirty files. Keep the original checkout untouched. In Plan Mode, make no filesystem edits, including candidate/worktree creation: develop the full patch in memory or the response and label unexecuted verification explicitly. Plan Mode never authorizes application.

## Repair and prove the reduction

For a behavioral defect, add an independently derived regression test and observe its relevant behavioral failure against the pinned input before implementation. Compilation/tool failures and skipped checks are not RED. Preserve the acceptance oracle. Follow applicable category ordering: tests, deletion, modification, justified addition, documentation. Prefer removing obsolete/duplicated logic and extending the existing owner; justify additions and every deletion against callers, exports, compatibility, documentation, and retained history.

The **entire proposed repair** must satisfy `text lines added - text lines deleted < 0`, aggregating every changed text file, including new tests, docs, configuration, and supporting changes. Report per-file and total additions/deletions/net against the same exact input and complete candidate; include new and untracked candidate files. Report text-byte changes and binary path/byte changes separately. Binary removal cannot satisfy the text-line rule.

This additional maintenance constraint is not a quality metric for ordinary RDD phases. Reject minification, compressed formatting, generated-file tricks, moving text to binaries/excluded files, weaker checks, removed coverage, unrelated deletions, and loss of required behavior or useful documentation. Reconcile renames and the complete inventory so nothing escapes counting. If a coherent, safe repair cannot achieve a strictly negative aggregate delta, stop and report the incompatibility; do not pad deletions or silently relax the rule.

Run relevant focused and cumulative checks on the candidate; capture actual commands, environment, outputs, and source identity. Do not claim unavailable or unexecuted verification. Replay the finished patch onto another disposable copy of the pinned input, check exact application and complete content equivalence, and recompute counts. In Plan Mode, these checks remain pending unless runnable without edits.

## Deliver the complete proposal

Provide a detailed, ordered plan tied to finding IDs: affected paths/owners, behavior before/after, implementation steps, deletion/reuse/addition rationale, downstream/compatibility impact, verification commands and expected assertions, actual RED/GREEN evidence, risks, and blockers.

Include the **complete exact unified patch**, with every hunk and full new tests/docs/files; no placeholders, omitted hunks, illustrative snippets, or diffstat in place of the patch. Supply it in the response or an accessible requested artifact and identify its hash. Include base/dirty-input manifests, candidate content identity, patch identity, per-file/aggregate line and byte counts, binary changes, and replay/verification results. Clearly mark incomplete evidence.

The proposal grants no application/publication authority and is not its own approval. Relevant input drift requires refreshing audit, candidate, counts, checks, and independent review before use. Hand the exact package to [rdd-harness-reductive-repair](../rdd-harness-reductive-repair/SKILL.md) only when repair is authorized.
