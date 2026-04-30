# macOS Menu-Bar Controller

The macOS menu-bar controller is the first native Harness app shell.
It gives daily operators a small status surface even when the full dashboard is closed.

## Scope

The v1 controller shows:

- runtime state: running, stopped, degraded, setup-required, or error
- active task count
- manual-review count
- failed, stale, retryable, or repair-needed attention count
- controls for setup assistant, start, stop, restart, recover, refresh, doctor, embedded dashboard, logs, settings, and quit

The dashboard remains the full detail surface.
The menu bar is for operational awareness and safe controls, not for editing task truth.
The setup assistant is the first-run path for local runtime initialization and optional app setup.

## Data Boundary

The app shell does not read SQLite.
It uses the same public local contract as any other app shell:

- `python3 -m modules.local_runtime --json status`
- `python3 -m modules.local_runtime --json doctor`
- `python3 -m modules.local_runtime --json setup status`
- `python3 -m modules.local_runtime --json open --print-url`
- `GET /tasks`
- `GET /supervision/queue`

Task counts are derived from canonical read-model projections returned by `GET /tasks`.
Attention counts use `GET /supervision/queue` so stale, retryable, invalid-proof, and repair-needed states come from Harness policy, not a duplicate Swift interpretation of the database.

## Runtime Controls

Start, stop, restart, and recover call the existing local runtime CLI:

- start initializes local runtime state, launches `harness serve` as an app-managed child process, and waits for health
- stop calls `harness stop`
- restart stops, then starts
- recover stops unhealthy PID-backed processes, clears stale PID files, handles port conflicts explicitly, and starts a fresh runtime

The v1 daemon decision is intentionally small: macOS launches the Harness app with `SMAppService`, and the app supervises the backend through the app-managed CLI lifecycle.
Harness does not install a LaunchAgent in this slice.
That keeps the user-facing toggle reversible from Settings and avoids adding a second process manager before packaging/notarization work is finished.

## Project Shape

The first native app lives under:

```text
apps/macos/HarnessApp/
```

It is a SwiftPM GUI app with:

- `HarnessApp`: SwiftUI/AppKit menu-bar executable
- `HarnessAppCore`: testable parsing and summary logic
- `HarnessAppCoreCheck`: deterministic Swift validation executable for summary and route contracts

The project-local run entrypoint is:

```bash
./script/build_and_run.sh
```

The script builds the SwiftPM app, stages a local `.app` bundle under ignored `dist/macos/`, and writes the repo root into the development bundle metadata so local builds can run the existing Python runtime module.

## Dashboard Window

The dashboard window is a singleton app scene opened from the menu bar.
It starts the local runtime when needed, then embeds the packaged dashboard through a small WebKit bridge.

The window preserves the canonical local dashboard routes:

- `/dashboard/tasks/`
- `/dashboard/verification/`
- `/dashboard/reconciliation/`
- `/dashboard/reviews/`
- `/dashboard/execution/`

Closing the dashboard window does not stop the runtime.
The menu bar remains useful without the dashboard window open.

Browser fallback and copy-URL controls exist for debugging local route or asset problems without changing the app/runtime boundary.

## Setup Assistant

The setup assistant is a singleton app scene opened automatically on first launch and manually from the menu bar.
It keeps normal-user setup inside the app:

- initialize app-managed local runtime and SQLite
- request optional Launch at Login
- request optional notifications
- choose optional workspace folders through `NSOpenPanel`
- store optional GitHub, Linear, and repair callback secrets through the app-managed secret boundary
- run doctor and refresh guided setup status
- open the embedded dashboard when core onboarding is complete

The assistant reports app-owned facts to the setup doctor through environment overlays on the runtime command.
It does not change Harness task truth, read SQLite, or bypass canonical API/read-model/timeline surfaces.

Launch at Login and crash/stale-process recovery are implemented through the app-managed lifecycle contract.

## Notifications

The menu-bar app delivers optional local notifications when macOS permission and the app-level Settings toggle both allow delivery.
Notification denial is treated as a user preference, not a setup failure.

Notification candidates come from Harness surfaces the app already reads:

- `GET /supervision/queue` for task attention such as `review_required`, `repair_dispatch_failed`, `stale_active_task`, and `budget_threshold_crossed`
- guided setup status for integration credential attention after the local runtime is ready

The app stores delivered notification IDs in user defaults to avoid resending the same task/setup attention event on every poll.
It does not use SQLite, filesystem scans, or private backend internals to discover notification events.

Clicking a notification posts an in-app destination request:

- review and budget attention opens the dashboard review route
- repair and stale executor attention opens the dashboard task route
- integration credential attention opens the setup assistant
