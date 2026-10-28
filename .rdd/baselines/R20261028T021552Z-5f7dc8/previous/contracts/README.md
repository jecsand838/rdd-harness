# Canonical Protobuf contracts

`rdd/v1/harness.proto` is a qualification fixture for the included message/local-service generator. The specification workflow derives the actual Todo module boundaries and local public API under separate application packages.

Run `./rdd contracts generate --bootstrap-lock --target wasm32-unknown-unknown` in the active specification workflow, inspect and commit real outputs/lockfiles, then run the read-only contract checks and freeze exact inventories.

The generator enforces local unary provider signatures without introducing a network transport. Real architecture/consumer/provider checks must prove that application modules use those shapes and obey ownership rules. A contract shape change is forbidden in implementation and requires a specification amendment.
