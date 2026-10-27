# Tauri runtime and packaging guidance

## Application boundary

Tauri hosts packaged web content in a system WebView. A Rust frontend compiles its UI behavior to WebAssembly and still needs approved generated interop. Keep domain rules and storage native; a WASM UI must not gain database credentials, arbitrary filesystem operations, or raw SQL commands.

The baseline does not require a particular Rust frontend framework. Compare official support, accessibility, maintenance, WASM toolchain, Tauri invocation, bundle compatibility, and testability during specification. Capture the exact versions and proof of packaging; a dependency name alone is not qualification.

## Capabilities and CSP

Bad configuration pattern:

```json
{
  "app": {
    "security": { "csp": null },
    "windows": [{ "label": "main", "url": "https://example.invalid/app" }]
  }
}
```

This is incompatible with the offline and bundled-content requirements. Do not retain development configuration as a production shortcut.

Better release configuration procedure:

1. Point `frontendDist` to the approved built asset output and verify it is populated by a clean build.
2. Explicitly reference the small set of production capability identifiers.
3. Restrict each capability to named application windows and actual needed permissions.
4. Generate custom application-command permissions using `tauri_build::AppManifest::commands` where appropriate, then allow only approved operations.
5. Configure `default-src`, `script-src`, `connect-src`, resource directives, and approved internal IPC URLs for the selected framework. Tauri's CSP guide calls for `'wasm-unsafe-eval'` when needed by WebAssembly; this does not justify general `'unsafe-eval'`, wildcard origins, or remote content.
6. Test the built artifact. A configuration file passing its JSON schema does not establish that denied operations are actually denied.

Capabilities can accumulate when a window belongs to several files. Explicitly enabling selected capability identifiers prevents an unrelated file from unintentionally expanding the release surface. Custom Rust code must still validate input and selected-path authority; capability declarations do not inspect arbitrary native code.

## Lifecycle choices

Derive startup, close, focus and failure tests from the [requirements](../../../../requirements/requirements.md) and frozen scenarios, rather than maintaining a second lifecycle inventory here.

The single-instance plugin is a starting point, not evidence that simultaneous first launches are safe. Verify initialization order, data-location identity, and behavior on all required operating systems. Build any test-only override of the data directory so it cannot become an unrestricted production command.

## Packaging evidence

Use the [package procedure and evidence inventory](../SKILL.md#procedure) for the platforms selected by NFR-PLAT-001 and the frozen specification. Pin prerequisites from current Tauri guidance. Signing or notarization credentials are environment configuration; missing required credentials block delivery evidence, never justify a fabricated pass.

## Primary references

Checked 2026-10-07.

Select primary sources tagged `tauri-application` in the [engineering source catalog](../../../../.rdd/sources/engineering.json).
