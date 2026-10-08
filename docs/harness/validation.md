# Harness validation record

This record describes the boilerplate harness on the Linux authoring host. It does not claim Todo application completion. Native Windows/macOS CI is configured but was not executed here.

| Verification | Result |
| --- | --- |
| Complete portable controller regression suite | **173 passed; 0 skipped** with the optional installed-Codex smoke enabled |
| Repo-local skill structural validation | **24 passed** |
| Skill local links and JSON/TOML configuration | Parsed/checked successfully |
| Supplied Todo requirements | Exact byte comparison passed; SHA-256 below |
| Native goal objective | **3,579 characters**, below the 4,000-character limit |
| Installed Codex client | **0.159.2**: actual help and bundled model/effort catalog checked |
| Paid model invocation/account entitlement | Not exercised |
| Real GitHub PR publication or hosted Actions run | Not exercised; adapters and CI use explicit offline protocol fixtures |
| Rust generator compilation, Buf generation and host/WASM signature proofs | Not executed here because Cargo, rustc and Buf were unavailable; first local qualification must pass before freeze |
| Production Todo code or application acceptance | Not generated or claimed |

The suite executes real Git repositories, worktrees, commits, SQLite state transitions, source hashing, process deadlines, behavioral RED/GREEN, benchmark calculations, draft qualification, phase closure and checkpoint recovery. The lifecycle fixtures label their fake Protobuf and GitHub boundaries explicitly. The separate generator orchestration tests verify safety/rollback and prerequisite failures; they are not compiler evidence.

The optional installed-client smoke checks advertised client support only. It does not spend a model turn or establish your account's entitlement. Ordinary `./rdd selftest` runs the same suite with that single optional client test skipped unless `RDD_CODEX_SMOKE` points to a real installed binary.

The final suite used a private test temporary directory because the authoring workspace synchronizes ordinary scratch files. This avoids transport writes racing with the intentionally strict clean-tree checks. Local users normally use system temp; `RDD_TEST_TMPDIR` can select a private writable directory if their workspace has a similar synchronization layer. No verification checks were weakened to accommodate this environment.

Full successful output: `docs/harness/selftest.txt`. Machine-readable scope and source hashes: `docs/harness/validation.json`.

Requirements SHA-256:

```text
9ae99124fef79f4ea5f56f7a7ffd5fe17f75160b9db3b16d9d5c57fbaf6d12f6
```

The final ZIP also carries `MANIFEST.sha256` for the delivered files. Runtime databases, worker worktrees, private process state, Cargo build outputs and temporary fixtures are excluded.
