# Worked vertical graph

This example delivers data export from an existing application.

| ID | Category | Requires | Produces |
|---|---|---|---|
| T201 | tests | Existing collection fixture | Failing complete-export assertions |
| T202 | modification | T201 | Existing collection query exposes required snapshot behavior |
| T203 | addition | T202 | Export writer using the approved format |
| T204 | documentation | T203 | User export instructions |
| T205 | tests | Existing error fixture | Failing destination-protection assertions |
| T206 | modification | T205 | Existing path validation rejects protected destinations |
| T207 | addition | T206 | Export boundary integrates destination validation |

Two verticals share the export outcome:

- Complete data: T201 → T202 → T203 → T204.
- Protected destination: T205 → T206 → T207, then the phase acceptance that also requires T203.

The graph must include any real relationship between T203 and T207. If both write the same new file, either combine them as one addition task with both prerequisites or assign one owner and integrate sequentially. Merely placing them in different worktrees cannot prevent a semantic overlap.

## Missing-producer detection

If T203 assumes a consistent snapshot but T202 only returns a mutable iterator, the needed capability has no producer. The planner must inspect the approved semantics and either add the missing task before freeze or return a missing atomicity decision to specification. Marking `snapshot` as “baseline” without a path/test is not a solution.

## Cycle detection

Suppose T203 requires an error enum from T207 while T207 requires a writer type from T203. A cycle exists. It may be a false task split, resolved by combining related additions in one coherent task. If it reflects cyclic module contracts, specification must fix the design. Assigning both tasks to P01 does not eliminate the cycle.

## Category compatibility

The test/modification/addition order in this example can fit one phase if each test can be authored against the approved boundary before production behavior exists. If a modification actually requires a newly added implementation, that edge must cross a phase boundary. Distinguish using a frozen generated type from using a working feature: the former can be a preparation baseline capability, while the latter needs its producing task.

## Output

Preserve explicit prerequisite IDs, capability evidence, vertical membership, and write ownership in the machine plan. A pretty diagram supplements this data and cannot replace it.
