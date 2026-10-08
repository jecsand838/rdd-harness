# Machine artifact schemas

The checked-in JSON schemas define specification, plan, review, evidence, blocker and checkpoint formats. The portable Python controller supports the explicit strict subset documented in `tools/rdd/common.py`; unsupported keywords fail. Semantic validators additionally enforce traceability, DAG cuts, categories, write scopes and evidence identities.

Templates with empty arrays are authoring aids, not valid accepted artifacts. A JSON schema cannot prove semantic completeness or observer honesty. Do not change these acceptance rules during implementation.
