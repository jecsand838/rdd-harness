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

| Event | Required application behavior |
|---|---|
| First launch | Initialize only when there is no existing dataset |
| Storage unavailable | Preserve files and enter actionable retry/exit state |
| Second launch | Arbitrate before database ownership, activate existing window |
| Normal close with draft | Offer retain/discard without changing committed data |
| Normal close with mutation | Wait for a known outcome while displaying pending state |
| Resume or focus | Re-evaluate local date and refresh required derived state |
| Forced termination | Let next startup verify/recover the persisted state under the failure model |

The single-instance plugin is a starting point, not evidence that simultaneous first launches are safe. Verify initialization order, data-location identity, and behavior on all required operating systems. Build any test-only override of the data directory so it cannot become an unrestricted production command.

## Packaging evidence

Keep the required Windows x86_64, macOS arm64, and Linux x86_64 builds distinct. Pin and document prerequisites from current Tauri guidance. Test installation without Rust, Turso CLI, or a development server. Record the installed package's digest and build revision. Signing or notarization credentials are environment configuration; missing credentials must be reported as blocked delivery evidence, never substituted with a fabricated pass.

Test instrumentation and ordinary release artifacts are separate outputs. An embedded automation server may help a test build, but violates this baseline if left in the release. Inspect features, dependencies, symbols/configuration, and runtime behavior to establish removal.

## Primary references

Checked 2026-10-07.

Select primary sources tagged `tauri-application` in the [engineering source catalog](../../../../.rdd/sources/engineering.json).
