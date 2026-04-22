# Harness macOS App

This is the native macOS shell for local Harness operation.
The first slices are a menu-bar controller with runtime controls and summary counts, a first-run setup assistant, and an embedded dashboard window for full inspection.

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

## Onboarding

First launch opens the setup assistant.
It initializes app-managed config, logs, and SQLite state; asks for optional Launch at Login and notification permission; lets users select workspace folders; shows optional GitHub, Linear, and ingress/executor setup items; runs doctor; and opens the embedded dashboard.

The assistant renders `harness setup status --json` through `GuidedSetupStatusPayload`.
It reports app-owned facts back to the CLI with:

- `HARNESS_NOTIFICATION_PERMISSION`
- `HARNESS_LAUNCH_AT_LOGIN`
- `HARNESS_WORKSPACE_FOLDERS`

GitHub, Linear, and repair callback tokens entered in the assistant are saved through the app-managed secret boundary with stdin.
They are not persisted in Swift preferences.

## Dashboard

The dashboard opens inside the app from the menu bar.
It uses a narrow WebKit bridge to load the app-managed local dashboard routes:

- `/dashboard/tasks/`
- `/dashboard/verification/`
- `/dashboard/reconciliation/`
- `/dashboard/reviews/`

Closing the dashboard window does not stop the local Harness runtime.
Use "Open in Browser" or "Copy URL" from the dashboard toolbar for debugging.
