# CLI And Web As The Supported Operator Surface

- title: CLI and web as the supported operator surface
- status: accepted
- date: 2026-04-30

## Context

Harness briefly pursued a native macOS shell for local operation: menu bar, first-run onboarding, notifications, Launch at Login, embedded dashboard window, and DMG packaging.

That direction added a second product surface and a second maintenance stack. It created work around SwiftUI, AppKit, signing, notarization, packaging, macOS permissions, and desktop lifecycle behavior. Those concerns do not strengthen Harness's core value as a verification and reliability layer.

The operational loop Harness needs to support is simpler:

- CLI/runtime commands for setup, status, doctor, start, stop, recovery, dry runs, and local automation
- backend APIs as the canonical control-plane boundary
- web dashboard for inspection, review, and verification state
- Linear and GitHub as external work/proof systems
- Symphony-like execution substrates beneath Harness, not inside the operator UI

## Decision

Harness will treat CLI + API + web dashboard as the supported operator surface.

The native macOS app and packaging scripts are not active product surfaces and have been removed from the active tree.

Do not add new native macOS app features, packaging work, signing/notarization work, notification behavior, Launch at Login behavior, or Swift onboarding flows unless this decision is explicitly reopened.

## Implications

- New operator flows should be expressed through `modules.local_runtime`, backend APIs, and the web dashboard.
- Local static dashboard packaging remains useful, but it should not imply a native app requirement.
- Setup and troubleshooting docs should lead with CLI/web, not DMG or first-run app flows.
- Runtime contracts must stay portable and must not depend on Swift, AppKit, `.app` bundle layout, macOS notifications, or Launch at Login.
- Existing macOS architecture notes are historical context unless a future task explicitly reactivates that surface.

## Consequences

This reduces maintenance burden and keeps Harness closer to its durable control-plane role.

The tradeoff is less native desktop polish. That is acceptable because Harness's strategic risk is not lack of a menu-bar app; it is accidentally duplicating execution/runtime/product surfaces that stronger platform-native tools will absorb.

## Follow-Up

Future cleanup should archive historical macOS design and release notes once no active documentation depends on them.
