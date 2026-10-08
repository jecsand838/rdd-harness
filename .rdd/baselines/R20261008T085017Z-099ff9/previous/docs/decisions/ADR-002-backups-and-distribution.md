# ADR-002: local APFS backups and local Mac package

Status: selected in regenerate run R20261008T061841Z-666065, 2026-10-08.

## Context and options

FR-019–023 require versioned unencrypted backups, whole-file replacement, full validation and atomic collection replacement. FR-020 explicitly rejects storage that cannot meet publication guarantees. The only supported reference environment is the current internal-SSD Mac. Ordinary path writes or truncation cannot satisfy replacement safety. Supporting external APFS volumes would require separate device qualification; network filesystems have differing failure guarantees and are outside this selected support boundary.

## Decision and rationale

Support ordinary internal-SSD APFS backup destinations only; reject network, external/removable, non-APFS, aliases and special files before existing-file modification. Native chooser selection creates narrowly scoped tokens; UI commands never receive filesystem authority. Use a same-directory temporary, validated complete JSON and synchronized writes followed by atomic publication; `filesystem-qualification.md` owns the exact qualified sequence and its limits. Reconcile uncertain publication using retained identity/digest rather than blindly publishing again. Retain the validated restore candidate in native memory so confirmation cannot substitute changed source bytes.

The coordinator asked an optional directional preference for internal SSD only versus also external APFS; no response arrived during independent work. The coordinator stated the internal-SSD assumption and proceeded under the user-authorized specification workflow. This is a selected mechanism, not claimed explicit user approval or a requirements amendment.

Deliver an ad-hoc-signed local `.app`, installed in the user's Applications directory on the one supported Mac. No Developer ID, notarization, external distribution, privileged install, updater or release publication is selected. Qualification packages are disposable generic probes, not the Todo release. Final installation, clean-profile runtime, offline/privacy and accessibility checks remain mandatory for the future delivered package.

## Evidence and consequences

Apple's source-backed publication semantics and actual internal APFS interruption probes are in `filesystem-qualification.md`; recorded host identity is in `reference-host.json`. Backup grammar, selected-file limits, token lifetimes and error semantics are in `solution.md`. Future external-drive or public-distribution support requires a specification/requirements impact decision and new applicable qualification.
