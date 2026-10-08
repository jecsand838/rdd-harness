# Worked specification example

This reservation example explains method. It is not a proposed Todo application design.

## Starting obligations

- `FR-R1`: Accept a reservation only when requested quantity is available.
- `FR-R2`: Cancelling an accepted reservation restores its reserved quantity once.
- `NFR-R1`: Concurrent requests cannot reserve more quantity than available.

A weak specification says “make a reservation service with a reserve endpoint and unit tests.” It misses the decision boundary, duplicate requests, ownership, failure outcomes, and concurrent evidence.

## A complete semantic slice

The inventory owner controls availability and reservation state in one atomic operation. `Reserve` accepts an item identity, positive quantity, and request identity. Accepted results contain one stable reservation identity. A confirmed rejection changes no committed quantity. Repeating the same request identity returns its established result. An uncertain commit requires reconciliation before blindly retrying a different request identity.

These semantics are examples of decisions that must be justified by the actual requirements. Do not silently add request-id behavior if it changes required API or user outcomes; resolve it in specification.

## Scenario inventory

| ID | Initial state and stimulus | Oracle | Requirement |
|---|---|---|---|
| S-R1 | Availability 3; reserve 2 | Accepted; availability 1; one reservation | FR-R1 |
| S-R2 | Availability 3; reserve 4 | Rejected; availability remains 3 | FR-R1 |
| S-R3 | Cancel the same reservation twice | Quantity restored exactly once | FR-R2 |
| S-R4 | Availability 3; two overlapping requests of 2 | At most one accepted; never negative | NFR-R1 |
| S-R5 | Interrupt between durable commit and response | Reconciliation observes one whole committed outcome | Design decision tied to failure requirements |

Do not classify S-R4 as a golden path. It tests concurrency. Do not derive “arbitrary hardware failure safe” from S-R5's process interruption experiment.

## Contract review

`uint32 quantity` permits zero, so schema compilation cannot enforce positivity. A generated `ReserveRequest` also does not ensure the caller actually invokes the authoritative owner. The specification must define native validation, the generated callable signature, dependency restrictions, and real boundary tests.

The contract experiment compiles the proposed source and checks a small consumer against the generated signature. If a required error variant or optional field cannot be represented, fix the contract before freeze. A later implementor is not authorized to add a field because it is convenient.

## Coverage and size review

An independent reviewer checks that all three obligations are covered by the semantic slice and scenario inventory. It rejects a separate module for every endpoint because the same atomic invariant would become fragmented. It also rejects a generic workflow engine because none of these obligations requires it. These are design judgments grounded in this example's scope, not universal module-count rules.
