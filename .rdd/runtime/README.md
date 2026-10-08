# Local runtime state

The rest of this directory is ignored. It holds transactional SQLite state, OS operation locks, leases, isolated worktrees, bounded worker packets, checkpoints and process logs. `./rdd status` and `./rdd resume` are the supported interfaces.

Never delete a dirty worktree to resolve a lease. Export completed/active run evidence before discarding a checkout. The active locator is `.rdd/run.json`, also ignored.
