# Worked preparation example

This example changes an existing transport adapter. It demonstrates ordering without selecting Todo architecture.

## Initial plan

| Task | Category | Requires | Produces |
|---|---|---|---|
| T101 | tests | Existing adapter fixture | Failing replacement behavior checks |
| T102 | addition | T101 | Replacement adapter |
| T103 | modification | T102 | Callers use replacement |
| T104 | deletion | T103 | Old adapter removed |
| T105 | documentation | T104 | Updated integration guide |

Putting every task into P01 is invalid under the requested category order. `T102 -> T103` runs addition before modification; `T103 -> T104` runs modification before deletion. Deleting either dependency hides a real prerequisite. Relabeling T102 as modification hides the nature of the change.

## Valid partition

| Phase | Outcome | Work and evidence |
|---|---|---|
| P01 | Replacement exists behind its approved boundary; current callers remain functional | New failing tests, adapter addition, parity and failure checks, docs |
| P02 | Callers use the replacement and preserve specified behavior | New integration RED, caller modification, cumulative regressions, docs |
| P03 | Old unused path is removed | Removal-safety tests, deletion, build/registration checks, docs |

Each phase has tests and its own complete acceptance. P01 cannot claim production migration has finished. P03 cannot remove historical persistence migrations merely because their runtime adapter was removed.

The actual plan needs distinct test/documentation task IDs per phase; the table summarizes outcomes rather than supplying a machine manifest. The controller schema determines the exact fields.

## Shells and task projections

An absent Rust file may contain only a generated phase marker during preparation. It is not yet an implemented or imported module. A JSON capability document uses a sidecar so the preparation pass does not create invalid JSON or prematurely grant permissions. A frozen generated `.rs` interface is a read/check input. An implementation task may write its consumer test, but may not make the generated file writable by assigning a sidecar.

A projection resembles `RDD:P01:T101` with the exact controller format. Removing it manually causes marker reconciliation to fail while T101 remains unresolved. Completing T101 requires relevant RED evidence; the controller then updates the projection.

## Hidden dependency review

Check how tests compile before the adapter exists, whether registration is planned, whether changed error behavior is already specified, and whether the benchmark includes caller overhead. A missing error contract is a specification blocker. A missing task to update a documented caller is a preparation correction before the plan freezes.
