# macOS Onboarding Assistant

The macOS onboarding assistant is the first-run path for normal users.
It exists so a user can get to a healthy local Harness runtime without terminal commands, Docker, Python setup, Node, `pnpm`, repo cloning, or env-file editing.

## Scope

The assistant covers:

- what Harness does
- app-managed local runtime initialization
- SQLite readiness
- Launch at Login prompt
- notification permission prompt
- optional workspace folder selection
- optional GitHub, Linear, and ingress/executor setup items
- setup doctor validation
- opening the embedded dashboard

The menu bar can reopen the assistant at any time through `Setup Assistant`.
First launch opens it automatically until the user finishes core local setup and opens the dashboard.

## Source Of Truth

The assistant does not create a second setup system.
It renders the same guided setup contract used by CLI and docs:

```bash
python3 -m modules.local_runtime --json setup status
```

The Swift app decodes that payload through `GuidedSetupStatusPayload`.
The payload maps doctor checks into setup items and keeps the default onboarding rule explicit: only the local runtime blocks first-run completion.
GitHub, Linear, and ingress/executor setup remain optional until a selected workflow requires them.

## Runtime Boundary

The assistant initializes and validates runtime through the local runtime CLI:

- `init` creates app-managed config, logs, and SQLite state.
- `serve` starts the local API when the user wants live status or the dashboard.
- `doctor` provides the diagnostic summary.
- `setup status` drives setup item rendering.

The Swift app does not read SQLite directly and does not reconstruct Harness task truth.
The embedded dashboard remains the full inspection surface.

## App-Owned Setup Facts

Some doctor checks depend on state owned by the native app shell.
The assistant reports those facts to the runtime command environment before validation:

- `HARNESS_NOTIFICATION_PERMISSION`
- `HARNESS_LAUNCH_AT_LOGIN`
- `HARNESS_WORKSPACE_FOLDERS`

Notification state comes from `UserNotifications`.
Launch at Login state comes from `SMAppService`.
Workspace folders come from the standard macOS folder picker.

Warnings for notifications and Launch at Login do not block core onboarding.
Selected workspace folders are different: if the user configured a folder and it later disappears or is unreadable, setup blocks because Harness can no longer trust workflows that depend on that folder.

## Permissions

Launch at Login and notifications are optional but recommended.

Launch at Login is requested through the native login-item API.
When enabled, macOS starts the Harness app after login.
If onboarding has been completed, the app then starts the local runtime through `harness start`.
The backend remains an app-managed child process, not a separate LaunchAgent.

Notifications are requested through the native notification authorization prompt.
Notification event delivery is permission-aware and can be disabled later from Settings without affecting core app usage.

The assistant records and validates permission state.
The menu-bar app then delivers attention notifications from canonical Harness queue/setup surfaces when delivery is enabled:

- manual-review alerts
- repair-dispatch failures when surfaced by the API
- stalled executor alerts
- budget threshold alerts when surfaced by the API
- integration credential attention

## Integrations

Optional integrations are shown as setup items, not blockers.

- GitHub verifies artifact proof such as repos, branches, commits, PRs, and changed files.
- Linear coordinates structured work state when a workflow needs it.
- Ingress/executor connects OpenClaw, Hermes, Codex, or a future desktop-agent bridge without making Harness depend on one agentic desktop solution.

GitHub and Linear tokens entered in the assistant are stored through the app-managed secret boundary by piping the value into `harness secrets set ... --value-stdin`.
The token remains in view state only long enough to save it.
The UI never writes the token to config files or logs and never displays terminal fallback commands to normal users.

## Validation Rules

After each configured item, the assistant refreshes `setup status`.
That applies after:

- runtime initialization
- runtime start
- notification permission request
- Launch at Login changes
- workspace folder selection or removal
- secret save
- doctor run

The user can finish onboarding when `onboarding_complete=true`.
In the default path, that means the local runtime, SQLite state, and selected workspace folders are healthy.

## Development Validation

Use the SwiftPM app checks plus the backend setup/runtime tests:

```bash
cd apps/macos/HarnessApp
swift build
swift run HarnessAppCoreCheck
cd ../../..
python3 -m unittest tests.test_local_runtime tests.test_local_setup -v
./script/build_and_run.sh --verify
```

`HarnessAppCoreCheck` decodes the setup payload, verifies menu summary logic, and verifies dashboard route mapping in environments where SwiftPM test frameworks are unavailable.
