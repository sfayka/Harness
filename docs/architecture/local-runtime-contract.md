# Local Runtime Contract

Harness local app builds control the Python backend through a stable runtime contract.
The app shell should not import backend internals, write SQLite directly, or depend on repo-local shell exports.

## Command Surface

Packaged builds should expose these commands as `harness`. In a repo checkout, run the same contract with:

```bash
python3 -m modules.local_runtime <command>
```

Commands:

- `harness init`
- `harness serve`
- `harness status`
- `harness doctor`
- `harness open`
- `harness stop`

The CLI supports `--json` for app-shell consumption. JSON output is the contract the macOS menu-bar app should use.

## App-Managed Paths

Default macOS paths:

- Data: `~/Library/Application Support/Harness/`
- Config: `~/Library/Application Support/Harness/config.json`
- SQLite: `~/Library/Application Support/Harness/harness.db`
- Dashboard assets: `~/Library/Application Support/Harness/dashboard/`
- PID: `~/Library/Application Support/Harness/runtime/harness.pid`
- Logs: `~/Library/Logs/Harness/harness.log`

Default Linux paths:

- Data: `$XDG_DATA_HOME/harness/`, or `~/.local/share/harness/`
- Config: `<data-dir>/config.json`
- SQLite: `<data-dir>/harness.db`
- Dashboard assets: `<data-dir>/dashboard/`
- PID: `<data-dir>/runtime/harness.pid`
- Logs: `$XDG_STATE_HOME/harness/logs/harness.log`, or `~/.local/state/harness/logs/harness.log`

Developer and test runs may override paths with `--data-dir`, `--log-dir`, `HARNESS_APP_DATA_DIR`,
or `HARNESS_APP_LOG_DIR`.
Normal app usage should rely on app-managed defaults.

## Runtime Config

`harness init` writes non-secret config to `config.json` and initializes the SQLite schema.
Secrets do not belong in this file.
GitHub, Linear, and ingress/executor credentials should move through the app-managed secret store in later slices.

The first schema stores:

- local API host and port
- SQLite database path
- data, dashboard asset, runtime, PID, and log paths

`harness serve` applies the config to the backend process through environment variables before startup:

- `HARNESS_STORE_BACKEND=sqlite`
- `HARNESS_SQLITE_PATH=<app-data>/harness.db`
- `HARNESS_RUNTIME_MODE=local-app`
- `HARNESS_RUNTIME_CONFIG_PATH=<app-data>/config.json`
- `HARNESS_RUNTIME_DATA_DIR=<app-data>`
- `HARNESS_RUNTIME_LOG_PATH=<logs>/harness.log`
- `HARNESS_RUNTIME_HOST=127.0.0.1`
- `HARNESS_RUNTIME_PORT=8765`
- `HARNESS_RUNTIME_BASE_URL=http://127.0.0.1:8765`
- `HARNESS_DASHBOARD_ASSETS_DIR=<app-data>/dashboard`

This is what removes the need for Docker, Node, `pnpm`, or repo-local shell exports for the backend runtime.

## Dashboard Assets

The local app dashboard is a prebuilt static bundle served by the Python backend.
It is not a second server process and it is not a Node runtime embedded in the app package.

Developer builds produce the local bundle with:

```bash
pnpm build:dashboard:local
```

Packaged builds should copy that bundle into `dashboard_assets_dir`, or set `HARNESS_DASHBOARD_ASSETS_DIR` to the installed bundle path before starting `harness serve`.

When the configured directory contains `index.html`, the backend mounts it at:

- `GET /dashboard/`
- `GET /dashboard/tasks/`
- `GET /dashboard/verification/`
- `GET /dashboard/reconciliation/`
- `GET /dashboard/reviews/`

The dashboard calls the same-origin local Harness API. If the backend is unavailable, it should display the API error rather than substituting sample data.

## Status And Health

The backend exposes two app-shell-safe probes:

- `GET /health`: canonical backend and storage health.
- `GET /runtime/status`: local app runtime status envelope that includes mode, API base URL,
  store backend, schema readiness, and app-managed paths.

`harness status --json` calls the local health endpoint and returns:

- `status=running` when the local API is healthy.
- `status=stopped` when no health endpoint responds.
- `status=uninitialized` when config has not been created.
- `status=degraded` when the API responds but reports degraded health.

## Doctor Checks

`harness doctor --json` returns checks with this shape:

```json
{
  "code": "sqlite",
  "status": "pass",
  "message": "SQLite database is ready.",
  "next_action": "No action needed."
}
```

Initial checks cover:

- app data directory writability
- log directory writability
- config presence and validity
- SQLite schema readiness
- local API health

The local API check is a warning when the runtime is stopped.
A stopped runtime is a valid setup state; it is not a corrupted install.

## Exit Codes

- `0`: command succeeded or desired state is already true.
- `1`: runtime is initialized but not currently healthy.
- `2`: setup is missing or config is unreadable.
- `3`: runtime error that requires remediation.

All CLI failures should produce operator-readable messages. Stack traces are not part of the user-facing contract.

## Process Lifecycle

`harness serve` runs the backend in the foreground, writes a PID file, appends runtime output to `harness.log`,
and removes the PID file on clean exit.

`harness stop` reads the PID file and sends `SIGTERM`.
Missing or stale PID files are treated as already stopped because the desired state is satisfied.

The local API binds to loopback by default. Network exposure is out of scope for the local app v1 contract.

`harness open` should open the dashboard URL by default:

```text
http://127.0.0.1:<runtime-port>/dashboard
```
