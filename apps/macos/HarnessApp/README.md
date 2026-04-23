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

The distributable packaging path is:

```bash
./script/package_macos_app.sh
```

That script stages a self-contained `Harness.app` and `Harness.dmg` under `dist/macos-release/` with a bundled `harness` runtime and prebuilt dashboard assets.

The app reads Harness through the local CLI and HTTP API contract. It must not read SQLite directly.

## Runtime Lifecycle

The app uses the local runtime CLI as the process boundary:

- `harness start`: start the backend as an app-managed process and wait for health.
- `harness stop`: stop the PID-backed backend process.
- `harness recover`: clear stale state, stop unhealthy PID-backed processes, handle port conflicts, and restart.

Launch at Login is controlled through `SMAppService`.
When enabled, macOS launches the app after login; the app then starts the local runtime if onboarding has been completed.
The backend is not installed as a separate LaunchAgent in this slice.

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

## Notifications

Notifications are optional and reversible from Settings.
The app asks for macOS notification permission during onboarding, but denial does not block setup, runtime startup, or dashboard use.

When notifications are enabled and authorized, the app schedules local alerts from canonical Harness attention/setup surfaces:

- manual review required
- repair dispatch failed when the API surfaces that attention type
- stale executor / active task with no recent canonical activity
- budget threshold crossed when the API surfaces that attention type
- integration credential attention from guided setup status

Notification clicks reopen the relevant surface: review and task attention opens the dashboard route, and integration credential attention opens the setup assistant.
The Swift app does not read SQLite to find notification events.

## Dashboard

The dashboard opens inside the app from the menu bar.
It uses a narrow WebKit bridge to load the app-managed local dashboard routes:

- `/dashboard/tasks/`
- `/dashboard/verification/`
- `/dashboard/reconciliation/`
- `/dashboard/reviews/`

Closing the dashboard window does not stop the local Harness runtime.
Use "Open in Browser" or "Copy URL" from the dashboard toolbar for debugging.
