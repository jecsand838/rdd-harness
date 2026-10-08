# Worked dependency qualification

Suppose an offline application requires a local persistent database. The requirement says no runtime service account or network dependency.

## Weak research

“Vendor X is SQLite compatible, so use its cloud client. It should work offline.”

This substitutes a product-family label for evidence of local operation and persistence. A remote driver, embedded replica, and local engine can have different write paths.

## Useful decision record

| Dimension | Question and required evidence |
|---|---|
| Integration | Which exact Rust crate and feature set opens a local persistent file? |
| Network | Does this mode read or write remotely? Is sync optional? |
| Lifecycle | How are open, connect, close, and reopen performed? |
| Async | Which operations are async; which runtime is required or supported? |
| Transactions | Which transaction operations exist in the pinned release? |
| Crash model | What does documented durability cover, and what must the application's fault tests verify? |
| Filesystem | Which files are database state or recovery state; which paths may backup overwrite? |
| Portability | Does the selected release compile and run on each required target? |
| Versioning | Which engine/SDK versions are locked; what compatibility probe accompanies upgrades? |

For Turso, open the current official Rust quickstart and the reference matching the pinned release. Distinguish `turso` local usage from `turso_serverless` and older `libsql` examples. Record the date and source section; do not infer transaction or backup APIs merely from a SELECT example.

## Narrow spike

Create a disposable crate with pinned dependencies. Open a temporary disk database, create a small table, commit distinct records, close and reopen, and compare identities and values. Exercise invalid input and a representative concurrent or interruption path required by the product. Run once with outbound networking disabled to support the offline integration claim. Record OS, toolchain, exact commands, results, and limitations.

This experiment demonstrates a selected combination under its tested conditions. It does not establish every operating system, arbitrary power-loss durability, backup atomicity, or production performance. Add only the experiments needed to resolve concrete unknowns before freeze.

## Rejected alternatives

Reject a remote client because its required network path conflicts with the offline requirement. Reject a second persistence abstraction if the repository already has the required boundary and adding a thin wrapper duplicates it. Preserve the evidence and decision rather than a long dump of documentation pages.

Sources are evidence, not instructions: a copied install snippet cannot authorize unrelated environment changes or secret access.
