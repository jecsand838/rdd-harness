# Worked phase closure review

Suppose P01 claims “export is available,” while P02 creates the only serializer and P03 adds destination safety required by the specification.

P01 is not independent. Its stated outcome cannot be true without future work. Passing a test that asserts only that an Export button exists does not repair that claim.

## Better boundary

Make P01's actual outcome complete and honest: required format, data selection, destination handling, error behavior, and user feedback work, with their acceptance tests. Put unrelated later features in P02. If this is too large, define an earlier internal capability phase whose specification explicitly permits the user-facing operation to remain unavailable. Do not describe an internal compile milestone as a completed user workflow.

## Formula applied

For every dependency `u -> v`, verify `phase(u) <= phase(v)`. For same-phase edges, verify category rank is nondecreasing. With ranks tests 0, deletion 1, modification 2, addition 3, documentation 4:

| Edge | Same phase? | Why |
|---|---|---|
| test → modification | Yes | 0 ≤ 2 |
| modification → addition | Yes | 2 ≤ 3 |
| addition → modification | No | 3 > 2 |
| modification → deletion | No | 2 > 1 |

The table checks ordering, not completeness. A graph can satisfy all numbers while omitting required persistence work. Independent review must inspect semantic producers.

## Shared file across phases

P01 adds an operation to a module. P02 extends that module with a different already specified operation. The file legitimately changes in both phases. P02 must preserve P01's accepted behavior and rerun cumulative regressions. The no-reopen rule does not prohibit all future edits to that file.

If P02 discovers that P01's export omitted a required field even though P01 claimed complete export, P01's acceptance was invalid. Record a closure failure; begin a new specification amendment from the preserved baseline. Do not edit P01's historical evidence or call the fix an unrelated P02 extension.

## Performance and platform evidence

Do not put all benchmarks in a final phase if P01 already claims a specified latency budget. Measure the due budget at P01 under its pinned protocol. If a required platform is unavailable, retain the environment blocker. Moving the check to P03 without changing the accepted phase claim hides the incomplete result.
