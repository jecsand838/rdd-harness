# Future application entry points

Preparation derives the Tauri desktop and Rust/WASM UI layout after specification chooses and qualifies the UI framework and build tools. No application entry point is preimplemented here.

Keep Tauri commands as validated adapters around domain operations. Events are notifications with explicit lifetime and consistency rules, not authority for persisted state. Follow the tauri-application, tauri-commands-events and create-ui-page skills.
