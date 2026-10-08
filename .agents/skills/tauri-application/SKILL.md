---
name: tauri-application
description: Configure, package, or review a Tauri 2 desktop application with Rust UI behavior, native lifecycle, least-required capabilities, CSP, offline assets, and platform verification. Use for runtime setup, framework selection, packaging, native permissions, or application lifecycle tasks.
---

# Tauri application

Read NFR-TECH, NFR-PLAT, NFR-OFF, NFR-PRIV, NFR-SEC, the approved dependency qualification, and the platform matrix. The example requires Rust UI state/event behavior; select a Rust/WASM frontend during specification. Do not silently introduce handwritten TypeScript business behavior.

## Procedure

1. Pin compatible Rust, Tauri, frontend, WebAssembly toolchain, plugins, and build tools. Qualify native build, UI build, generated contracts, a real command call, database persistence, and packaging together on the required platforms before freezing specification.
2. Keep native adapters thin and domain crates independent of the WebView. Bundle executable UI content, fonts, help, and assets locally. Production has no development server, localhost HTTP server, telemetry, remote font, sync, or updater.
3. Give the native runtime one explicit owner for database startup, recovery state, mutation admission, and shutdown. Perform instance arbitration before opening storage. A second instance activates the existing window while preserving its draft.
4. Enumerate only required plugins, permissions, windows, and paths. Restrict custom application commands explicitly; registering a handler alone does not establish per-window authorization. Test denied commands and narrow file selection scopes, including path aliases.
5. Configure the CSP for bundled assets and the selected Rust/WASM framework. Add only the WASM loading allowance required by the framework; never disable CSP to resolve a development error. Review release configuration independently of development configuration.
6. Keep storage and diagnostics under account-specific application-data locations. Distinguish first launch from unreadable/corrupt/newer-format existing storage. Avoid silently creating an empty replacement.
7. Package per platform with documented WebView prerequisites, signing/distribution decisions, and normal-user permissions. Verify the actual installer and installed binary in a clean profile; a browser preview is development feedback only.

## Evidence

Record package digest, revision, platform/WebView versions, install/uninstall checks, offline observation, denied-operation results, and clean release dependency inventory. Keep instrumented test builds distinguishable and exclude their command mocks and WebDriver servers from delivery. Use the phase gate for review.

Read [runtime guidance](references/runtime.md) for configuration traps, original examples, and primary sources. Read `tauri-commands-events` for IPC changes.
