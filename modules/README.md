# Future application modules

Preparation derives the Rust module/crate layout from the frozen domain ownership and dependency map, lists exact target paths, and creates empty/comment-only shells with task markers.

No Todo implementation is shipped here. Avoid one-crate-per-entity by default; use the domain-boundaries, create-module and rust-domain-types skills. Real provider interfaces must implement the frozen generated contracts.
