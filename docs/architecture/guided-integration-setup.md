# Guided Integration Setup

`harness setup status --json` is the local app onboarding contract.
It turns the lower-level setup doctor into user-facing setup items that a normal desktop app can render directly.

The setup contract is intentionally client-neutral.
Harness can integrate with OpenClaw, Hermes, Codex, or a future desktop-agent client, but Harness must not become architecturally tied to one of them.

## Command

From a packaged app, expose:

```bash
harness setup status
```

From a repo checkout, use:

```bash
python3 -m modules.local_runtime --json setup status
```

The command exits with `0` when onboarding can finish.
It exits with setup-required when a required item is missing for the selected workflow.

## Default Onboarding

Default onboarding only requires the local Harness runtime:

- writable app data and log directories
- app-managed runtime config
- SQLite schema readiness
- accessible selected workspace folders, if any were selected

Missing GitHub, Linear, execution-substrate, and legacy ingress/executor setup appears as incomplete optional work.
Those integrations become blockers only when the user selects a workflow that needs them.

Warnings for API stopped, dashboard assets, notifications, or Launch at Login are actionable, but they do not block runtime-only onboarding.
The app can start the API when live progress is needed, and notification/startup preferences remain user choices.

## Workflow Requirements

Use `--workflow` when a user selects a workflow that requires an external integration:

```bash
python3 -m modules.local_runtime --json setup status --workflow github-proof
python3 -m modules.local_runtime --json setup status --workflow linear-sync
python3 -m modules.local_runtime --json setup status --workflow repair-dispatch
```

Current workflow gates:

- `github-proof` requires GitHub artifact verification.
- `linear-sync` requires Linear coordination.
- `repair-dispatch` requires the execution substrate.

Multiple `--workflow` flags can be passed when the app needs to validate a combined workflow.

## Setup Items

Each item reports:

- `id`
- `title`
- `category`
- `required`
- `status`
- `blocks_onboarding`
- `purpose`
- `what_user_needs`
- `how_harness_validates`
- `next_action`
- `setup_actions`
- `validation`
- `execution_transport` for the `execution_substrate` item only

Item status values:

- `complete`: the item is ready.
- `incomplete`: the item is missing or optional until a selected workflow requires it.
- `blocked`: the item is configured badly enough that the selected setup cannot be trusted.

The top-level payload includes:

- `status`: `ready` or `setup_required`
- `onboarding_complete`
- `runtime_ready`
- `selected_workflows`
- `available_workflows`
- `required_blockers`
- `optional_incomplete`
- `optional_attention`
- `doctor_summary`

## Integration Boundaries

GitHub and Linear credentials must be stored through the app-managed secret boundary.
The setup contract names the secret to store and exposes the redacted validation status.
It must not ask normal users to edit env files.

Current secret names:

- `github_token`
- `linear_api_key`
- `repair_callback_bearer_token`

CLI fallback examples use stdin so tokens do not land in shell history:

```bash
printf '%s' "$TOKEN" | python3 -m modules.local_runtime --json secrets set github_token --value-stdin
printf '%s' "$TOKEN" | python3 -m modules.local_runtime --json secrets set linear_api_key --value-stdin
```

The execution-substrate item should name Symphony as the preferred runner without giving it completion authority.
It also exposes a normalized `execution_transport` object with `preferred_runner`, `mode`, `live_dispatch_enabled`, `completion_authority`, and `runner_completion_is_truth`. `live_dispatch_enabled` must remain `false` until Harness has an explicit live Symphony transport policy.
The legacy ingress/executor item must stay client-neutral in UI copy.
It should describe the connection as a compatibility desktop-agent bridge for OpenClaw, Hermes, Codex, or a future equivalent.
The current doctor still recognizes OpenClaw-shaped adapter variables because that is existing bridge wiring, not the Harness product boundary.

## Validation Source

Guided setup does not create a second validation system.
It consumes `harness doctor --json` and maps existing checks into onboarding items.

Current mapping:

- Local runtime: `app_data_dir`, `log_dir`, `config`, `sqlite`, `api_health`, `dashboard`, `notification_permission`, `launch_at_login`, `workspace_folders`
- GitHub: `github_connection`
- Linear: `linear_connection`
- Execution substrate: `execution_substrate`
- Legacy ingress/executor: `ingress_executor`

This keeps the app, CLI, and docs aligned around one diagnostic source.
