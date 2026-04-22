# macOS Menu-Bar Controller

The macOS menu-bar controller is the first native Harness app shell.
It gives daily operators a small status surface even when the full dashboard is closed.

## Scope

The v1 controller shows:

- runtime state: running, stopped, degraded, setup-required, or error
- active task count
- manual-review count
- failed, stale, retryable, or repair-needed attention count
- controls for start, stop, restart, refresh, doctor, dashboard, logs, settings, and quit

The dashboard remains the full detail surface.
The menu bar is for operational awareness and safe controls, not for editing task truth.

## Data Boundary

The app shell does not read SQLite.
It uses the same public local contract as any other app shell:

- `python3 -m modules.local_runtime --json status`
- `python3 -m modules.local_runtime --json doctor`
- `python3 -m modules.local_runtime --json open --print-url`
- `GET /tasks`
- `GET /supervision/queue`

Task counts are derived from canonical read-model projections returned by `GET /tasks`.
Attention counts use `GET /supervision/queue` so stale, retryable, invalid-proof, and repair-needed states come from Harness policy, not a duplicate Swift interpretation of the database.

## Runtime Controls

Start, stop, and restart call the existing local runtime CLI:

- start initializes local runtime state and launches `harness serve`
- stop calls `harness stop`
- restart stops, then starts

Issue #326 will own the final daemon/Launch-at-Login model.
This first controller intentionally keeps lifecycle control thin and delegates process semantics to the runtime contract already used by docs and tests.

## Project Shape

The first native app lives under:

```text
apps/macos/HarnessApp/
```

It is a SwiftPM GUI app with:

- `HarnessApp`: SwiftUI/AppKit menu-bar executable
- `HarnessAppCore`: testable parsing and summary logic
- `HarnessAppCoreTests`: Swift unit tests for menu-bar counts

The project-local run entrypoint is:

```bash
./script/build_and_run.sh
```

The script builds the SwiftPM app, stages a local `.app` bundle under ignored `dist/macos/`, and launches it with `HARNESS_REPO_ROOT` pointed at the repo checkout so development builds can run the existing Python runtime module.
