# Worked domain boundary review

Consider requirements for reserving and releasing a limited inventory quantity.

## Bad decomposition

- `ValidateQuantityModule` checks numeric bounds.
- `ReadAvailabilityModule` reads stock.
- `CreateReservationModule` writes a reservation.
- `ReduceAvailabilityModule` changes stock.
- A UI command calls these four modules in order.

Each module looks simple, but the invariant spans separate owners. Two concurrent calls can both read the same available quantity. Adding a mutex in the UI does not establish the invariant at the authoritative persistence boundary.

## Cohesive decomposition

The reservation owner exposes one operation whose semantics atomically decide and record a reservation. Its domain value types reject invalid state. A storage adapter implements the required atomic effect. A transport adapter validates the untrusted wire shape and calls the approved application boundary. The exact Rust crate split follows enforceable dependencies and compilation needs; it does not have to mirror each conceptual layer as a separate package.

## Boundary record

| Field | Example |
|---|---|
| Purpose | Accept or reject reservations while preserving quantity invariants |
| Owns | Reservation lifecycle and availability decision |
| Provides | Reserve; cancel; query reservation outcome |
| Consumes | Approved atomic persistence port and time source where required |
| Errors | Invalid request, unavailable quantity, unavailable storage, uncertain result |
| Forbidden | UI direct database writes; adapter duplication of reservation rules |
| Scenarios | Successful reserve; insufficient quantity; repeat cancellation; overlap; uncertain response |

The Protobuf request expresses field shape. Semantic validation decides that quantity is positive. The generated signature expresses the supported operation. The architecture check prevents unapproved direct calls. Real integration tests establish the specified atomic behavior under a bounded test model.

## Rejected generalization

A generic `RuleEngine<TPolicy, TEvent, TStore, TClock>` with plugin registration is not justified by two transitions. Prefer a concrete type with `reserve` and `cancel` methods and the smallest real external-effect boundary. Add generic machinery only when actual requirements need interchangeable policies.

## Review questions

Can one owner explain the invariant? Does each caller have a permitted operation? Are error and retry outcomes specified? Can an integration test exercise the real boundary? Are multiple crates necessary to enforce a meaningful dependency rule? If these answers are unclear, refine the specification before scheduling implementation.
