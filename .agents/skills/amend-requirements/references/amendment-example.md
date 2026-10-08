# Worked amendment impact

Assume the previous baseline permits a maximum title length of 200 scalar values. The updated requirements change the limit to 300.

## Immediate and transitive impact

The changed text may appear in a shared vocabulary section rather than inside the creation requirement. The impacted set can include creation, edit, restore, input feedback, maximum-capacity fixtures, backup validation, UI accessibility messages, performance datasets, and persistence assumptions. Search the traceability graph and actual call paths; do not limit impact to whichever requirement block was edited.

A Protobuf string field may remain unchanged because it does not encode the scalar-value limit. The semantic specification and tests still change. If a database constraint encodes the old bound, its migration and compatibility behavior need planning. If a performance fixture previously used maximum-length titles, its dataset digest changes and old benchmark evidence may no longer apply.

## Preserve what remains valid

The task identity invariant and completion-state semantics can remain unchanged. Preserve their requirement and scenario IDs. Preserve prior accepted history. Still run the cumulative regression inventory on the final amended revision; unchanged text alone does not prove unchanged behavior.

## Defect-driven amendment

Now assume requirements did not change, but a later phase discovers that the previous accepted restore operation silently discarded records. This is a closure failure if the sealed phase already claimed complete restoration. Begin a new amendment with a defect reason and unchanged requirement digest. Revise the solution only where needed, regenerate affected phases, and preserve the prior failed claim as historical evidence.

Do not add a new requirement saying “restore shall not discard data” merely to make an existing violation look like new scope.

## Regenerate comparison

If the user requests a fresh full solution, use regenerate. Remove superseded active specs after archiving them; derive all solution sections again. Existing code and stored user data remain until explicit planned changes replace them. “Regenerate specifications” does not mean `rm -rf` the application or its data.
