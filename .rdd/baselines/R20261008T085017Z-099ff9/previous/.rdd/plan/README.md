# Frozen implementation plan

The preparation workflow writes `plan.json`, validates task/requirement/check references and dependency cuts, then freezes `plan.lock.json`. `./rdd prepare` creates the implementation matrix, declared shells and exact task comments.

`plan.json` is the canonical scope. Inline/sidecar markers are a recoverable projection. Live task/phase state is read through `./rdd status`; never hand-edit it into the frozen plan.
