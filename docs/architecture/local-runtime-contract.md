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
- `harness start`
- `harness serve`
- `harness status`
- `harness doctor`
- `harness setup status`
- `harness open`
- `harness stop`
- `harness recover`
- `harness secrets status`
- `harness secrets set <name> --value-stdin`
- `harness secrets delete <name>`

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
GitHub, Linear, and ingress/executor credentials move through the app-managed secret store.

The first schema stores:

- local API host and port
- SQLite database path
- data, dashboard asset, runtime, PID, and log paths

`harness start` and `harness serve` apply the config to the backend process through environment variables before startup:

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
- app-managed secrets, when present, mapped to their backend environment variables

This is what removes the need for Docker, Node, `pnpm`, or repo-local shell exports for the backend runtime.

## Secret Store

macOS v1 stores local app secrets in Keychain. The stable Harness secret names are:

- `github_token`, mapped to `GITHUB_TOKEN`
- `linear_api_key`, mapped to `LINEAR_API_KEY`
- `repair_callback_bearer_token`, mapped to `OPENCLAW_REPAIR_BEARER_TOKEN`

From a repo checkout, use:

```bash
python3 -m modules.local_runtime --json secrets status
python3 -m modules.local_runtime --json secrets status --require github_token
printf '%s' "$GITHUB_TOKEN" | python3 -m modules.local_runtime --json secrets set github_token --value-stdin
python3 -m modules.local_runtime --json secrets delete github_token
```

Secret status output is redacted. It reports configured, missing, unavailable, and error states without returning token values.
Existing environment variables win over Keychain values so native developer `.env.local` workflows still work.

See [app-managed-secrets.md](app-managed-secrets.md).

## Guided Setup

`harness setup status --json` is the app-renderable onboarding contract.
It converts `harness doctor --json` into setup items with purpose, requirements, validation status, and next actions.

Default onboarding requires only the local Harness runtime.
Missing GitHub, Linear, and ingress/executor setup appears as incomplete optional work unless the app selects a workflow that requires one of them:

```bash
python3 -m modules.local_runtime --json setup status
python3 -m modules.local_runtime --json setup status --workflow github-proof
python3 -m modules.local_runtime --json setup status --workflow linear-sync
python3 -m modules.local_runtime --json setup status --workflow repair-dispatch
```

The current workflow gates are:

- `github-proof`: requires GitHub artifact verification.
- `linear-sync`: requires Linear coordination.
- `repair-dispatch`: requires a desktop-agent ingress/executor bridge.

Setup items use the app-managed secret boundary.
The GitHub and Linear items tell the app which named secret to store and how Harness validates it; they do not ask normal users to edit env files.
The ingress/executor item stays client-neutral and describes the bridge as compatible with OpenClaw, Hermes, Codex, or future desktop-agent clients.

See [guided-integration-setup.md](guided-integration-setup.md).

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
  "impact": "Harness can persist local task and verifier state.",
  "next_action": "No action needed."
}
```

Current checks cover:

- app data directory writability
- log directory writability
- config presence and validity
- SQLite schema readiness
- local API health
- dashboard asset and route availability
- GitHub credential setup state
- Linear credential setup state
- ingress/executor bridge setup state
- notification permission state reported by the app shell
- Launch at Login state reported by the app shell
- selected workspace folder availability

The local API check is a warning when the runtime is stopped.
A stopped runtime is a valid setup state; it is not a corrupted install.
Optional integrations also report warnings rather than failures when they are missing.
Configured-but-broken setup, such as a missing selected workspace folder, reports `fail`.

See [setup-doctor.md](setup-doctor.md).

## Exit Codes

- `0`: command succeeded or desired state is already true.
- `1`: runtime is initialized but not currently healthy.
- `2`: setup is missing or config is unreadable.
- `3`: runtime error that requires remediation.

All CLI failures should produce operator-readable messages. Stack traces are not part of the user-facing contract.

## Process Lifecycle

`harness start` is the app-facing lifecycle command.
It initializes the runtime if needed, starts `harness serve` as an app-managed background process, waits for `/health`, and then returns JSON the app can render.
If the runtime is already healthy, `start` exits successfully without launching a duplicate process.
If the PID file is stale, `start` removes it and starts a fresh runtime.
If the configured port is already owned by a non-Harness process, `start` fails with `status=port_conflict` and an explicit next action.

`harness serve` runs the backend in the foreground, writes a PID file, appends runtime output to `harness.log`, and removes the PID file on clean exit.
It is still useful for foreground debugging and for the background process launched by `harness start`.

`harness stop` reads the PID file and sends `SIGTERM`.
Missing or stale PID files are treated as already stopped because the desired state is satisfied.

`harness recover` is the app-facing repair action for crashed, stale, or degraded runtime state.
It stops an unhealthy PID-backed process when possible, clears stale PID files, starts a fresh runtime, waits for health, and reports the same user-facing JSON shape as `start`.

The local API binds to loopback by default. Network exposure is out of scope for the local app v1 contract.

`harness open` should open the dashboard URL by default:

```text
http://127.0.0.1:<runtime-port>/dashboard
```
