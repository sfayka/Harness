# macOS Daemon Lifecycle

Harness v1 uses an app-managed lifecycle, not a standalone LaunchAgent.

The decision is deliberate.
The first normal-user app needs reversible startup behavior, clear recovery actions, and observable failures.
Installing a second daemon manager before packaging and notarization would add operational friction without solving a current correctness problem.

## V1 Model

The macOS app owns the user-facing process lifecycle:

- `SMAppService.mainApp` registers or unregisters Launch at Login.
- macOS launches the Harness app after login when enabled.
- After launch, the app starts the backend with `harness start` if onboarding has been completed.
- The backend runs as an app-managed child process created by the local runtime CLI.
- The menu bar and Settings expose Start, Stop, Restart, Recover, Doctor, Logs, and Dashboard.

This gives users explicit control while still making Harness behave like local infrastructure after login.

## Runtime Commands

The app uses the local runtime contract instead of launching Python directly:

- `harness start`: initialize if needed, start `harness serve` in the background, wait for health, and return app-renderable JSON.
- `harness stop`: terminate the PID-backed backend process.
- `harness recover`: stop unhealthy PID-backed processes, clear stale PID files, detect port conflicts, start a fresh runtime, and wait for health.
- `harness status`: read health and PID state without mutating runtime state.
- `harness doctor`: report setup and remediation checks.

`harness serve` remains the foreground backend process used by `harness start`.
It is also useful for debugging.
Normal app controls should use `start`, `stop`, and `recover`.

## Startup After Login

Launch at Login starts the app, not the backend directly.
That matters because the app owns:

- onboarding completion state
- user-visible status
- recovery and logs
- optional permissions and workspace folder facts
- dashboard launch

If Launch at Login is enabled but onboarding is not complete, the app opens setup instead of starting a half-configured backend.
If onboarding is complete, the app calls `harness start`.
If the backend is already healthy, `start` exits successfully and the app avoids duplicate processes.

## Recovery Semantics

Recovery handles the common local failure cases:

- stale PID file: remove it and start fresh
- PID-backed process is alive but unhealthy: stop it, then start fresh
- configured port is already used by non-Harness process: fail with `status=port_conflict`
- backend exits before health: fail with `status=start_failed` and point the user to logs

The app should show the returned `message` and `next_action` rather than replacing it with a generic failure.

## Boundaries

The app-managed lifecycle does not change Harness truth boundaries.
The app supervises a local process; it does not read SQLite, mutate task truth, or bypass canonical APIs.

Future packaging work may revisit whether a helper, LaunchAgent, or privileged service is justified.
That should be decided only if the app-managed model fails a concrete release requirement such as restart after app crash while the user intentionally keeps the menu-bar app closed.
