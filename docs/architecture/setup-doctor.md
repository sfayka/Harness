# Setup Doctor Contract

`harness doctor --json` is the local runtime setup report.
CLI tooling and any future packaging should render this JSON directly instead of parsing logs or backend exception text.
For user-facing onboarding steps, prefer `harness setup status --json`, which maps these checks into guided setup items and workflow-specific blockers.

The doctor is intentionally broader than `/health`.
`/health` reports whether the backend is alive.
`doctor` explains whether the local runtime is set up well enough for operators to understand what is missing and what to do next.

## Check Shape

Every check returns:

```json
{
  "code": "sqlite",
  "status": "pass",
  "message": "SQLite database is ready at /path/to/harness.db.",
  "impact": "Harness can persist local task and verifier state.",
  "next_action": "No action needed.",
  "details": {
    "path": "/path/to/harness.db"
  }
}
```

Status values:

- `pass`: the item is ready.
- `warn`: the item is incomplete, optional, or currently stopped, but Harness can still run.
- `fail`: the item is broken enough that setup or the selected workflow cannot be trusted.

The top-level payload includes a summary count:

```json
{
  "status": "ok",
  "summary": {
    "pass": 8,
    "warn": 4,
    "fail": 0
  },
  "checks": []
}
```

The doctor exits with `0` unless at least one check is `fail`.
Warnings are still important, but they should not block normal local runtime setup.

## Current Checks

The current doctor covers:

- `app_data_dir`: app data directory writability.
- `log_dir`: log directory writability.
- `config`: app-managed config presence and readability.
- `sqlite`: SQLite database availability and schema readiness.
- `api_health`: local API availability.
- `dashboard`: packaged dashboard asset availability and dashboard HTTP route reachability when the API is running.
- `github_connection`: GitHub credential setup state.
- `linear_connection`: Linear credential setup state.
- `execution_substrate`: Symphony-compatible execution-substrate availability.
- `ingress_executor`: legacy desktop-agent bridge setup state for the current OpenClaw-shaped adapter wiring, without making OpenClaw the product boundary.
- `notification_permission`: optional notification delivery state reported by a wrapper shell; unknown or disabled states are healthy for CLI/web usage.
- `launch_at_login`: optional startup-after-login state reported by a wrapper shell; unknown or disabled states are healthy for CLI/web usage.
- `workspace_folders`: configured local workspace folder availability.

## Optional Shell Inputs

Some checks can accept facts from an optional shell or wrapper. The native macOS shell is deprecated, but the CLI still reads these environment variables when present:

- `HARNESS_NOTIFICATION_PERMISSION`: `authorized`, `denied`, or `not_determined`.
- `HARNESS_LAUNCH_AT_LOGIN`: `enabled` or `disabled`.
- `HARNESS_WORKSPACE_FOLDERS`: `os.pathsep`-separated folder paths selected by the user.

Execution-substrate checks read:

- `HARNESS_SYMPHONY_BIN`
- `SYMPHONY_BIN`
- `symphony` on `PATH`
- the Knox Analytics `Infrastructure/symphony/elixir/bin/symphony` convention

When the execution substrate is found, the check reports `status=pass` and `details.mode=installed`. When it is not found, the check reports `status=warn` and `details.mode=unconfigured`. Both states must keep `details.live_dispatch_enabled=false`, `details.completion_authority=harness_verification`, and `details.runner_completion_is_truth=false`. The doctor confirms installation posture only; it does not authorize Harness to dispatch live Symphony work or trust runner completion.

Current legacy desktop-agent bridge checks read the existing adapter variables:

- `OPENCLAW_CONFIG_PATH`
- `OPENCLAW_STATE_DIR`
- `OPENCLAW_BIN`
- `OPENCLAW_BASE_URL`

Those names are adapter wiring, not the product boundary.
The UI should describe the execution-substrate setup item as a Symphony-compatible runner and the ingress/executor setup item as a legacy compatibility bridge.

## Safety Rules

- Do not return raw token values.
- Do not include stack traces in normal-user output.
- Do not mark optional integrations as `fail` just because they are not connected.
- Do fail configured-but-broken items, such as a selected workspace folder that no longer exists.
- Do not require notification permission or launch-at-login to use Harness.

## Guided Setup Mapping

`harness setup status --json` consumes this doctor payload.
It keeps default onboarding limited to the local runtime and marks GitHub, Linear, execution-substrate, and legacy ingress/executor setup as optional until a selected workflow requires them.

Use workflow gates when needed:

- `--workflow github-proof`
- `--workflow linear-sync`
- `--workflow repair-dispatch`

See [guided-integration-setup.md](guided-integration-setup.md).
