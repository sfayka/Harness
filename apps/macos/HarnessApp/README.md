# Harness macOS App

This is the native macOS shell for local Harness operation.
The first slices are a menu-bar controller with runtime controls and summary counts, plus an embedded dashboard window for full inspection.

## Targets

- `HarnessApp`: SwiftUI/AppKit menu-bar app.
- `HarnessAppCore`: testable runtime/API parsing and summary logic.
- `HarnessAppCoreCheck`: lightweight validation executable for environments where SwiftPM test frameworks are unavailable.

## Validate

```bash
swift build
swift run HarnessAppCoreCheck
```

The repo-level launch path is:

```bash
./script/build_and_run.sh --verify
```

The app reads Harness through the local CLI and HTTP API contract. It must not read SQLite directly.

## Dashboard

The dashboard opens inside the app from the menu bar.
It uses a narrow WebKit bridge to load the app-managed local dashboard routes:

- `/dashboard/tasks/`
- `/dashboard/verification/`
- `/dashboard/reconciliation/`
- `/dashboard/reviews/`

Closing the dashboard window does not stop the local Harness runtime.
Use "Open in Browser" or "Copy URL" from the dashboard toolbar for debugging.
