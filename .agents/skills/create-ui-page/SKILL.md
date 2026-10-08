---
name: create-ui-page
description: Create or extend a Rust/WASM Tauri page or view with approved native API access, typed UI state, async feedback, draft protection, accessibility, and offline assets. Use for Todo views, editors, dialogs, query controls, and UI lifecycle tests.
---

# Create a UI view

Read the approved UI specification, Rust frontend choice, interaction states, requirement scenarios, and application API. Extend the existing page/component before adding a new route. New product behavior or an unavailable API is a specification blocker.

## Procedure

1. Map each user action to an approved native operation and each visible state to requirements. Distinguish loading, empty collection, no matches, draft, pending, rejected, uncertain, and committed state.
2. Keep first-party state/event logic in Rust. Use the selected framework's typed component patterns. Keep business rules native; UI validation provides prompt feedback using shared approved rules or consistency-tested adapters.
3. Represent state with enums and owning types. Keep editor drafts separate from stored task snapshots. Track query generations so an older response cannot overwrite newer filters or search.
4. Enforce draft protection on navigation, edit cancellation, restore, and normal close. Disable conflicting mutations while one is pending, while keeping viewing/focus responsive. Never show a saved acknowledgment before the native result commits.
5. Build semantic controls and text rendering. Associate labels and errors, provide visible focus and keyboard operation, manage dialog focus/return, and announce asynchronous outcomes. Do not render titles or notes as executable markup.
6. Bundle assets locally. Handle the required window size and 200 percent text scaling without hiding essential actions. Do not add remote fonts, analytics, unrequested animations, preferences, or persistence mechanisms.
7. Clean up subscriptions, pending view-only work, and listeners when the page leaves scope. Preserve admitted native mutation outcome tracking even if its initiating component disappears.

## Checks

Run component/state tests plus native-connected packaged journeys. Verify keyboard, screen-reader, contrast, resizing, draft and pending states, stale responses, empty/no-results differences, and malicious text rendering. Record automated and manual evidence separately for the phase gate.

Read [view patterns](references/view.md) for original code and state examples. Use `tauri-commands-events` for adapters.
