# Harness Local App Design

## Status

Design gate for [#316](https://github.com/sfayka/Harness/issues/316).

Parent epic: [#315](https://github.com/sfayka/Harness/issues/315).

This document defines the product and technical contract for the first self-contained Harness local app. It does not implement the app.

## Goal

Ship Harness as a self-contained macOS app that a normal operator can install and use without cloning the repo, installing Docker, installing Python, installing Node, running `pnpm`, or editing environment files.

The app should make Harness feel like local infrastructure:

- always available when the user wants it
- visible in the menu bar
- inspectable through a full dashboard window
- backed by durable local SQLite state
- able to guide setup without requiring a computer science degree

Linux support remains a product requirement, but macOS ships first. The macOS shell may use macOS-native APIs, but Harness core, runtime contract, SQLite schema, dashboard assets, and integration semantics must remain portable.

## Product Thesis

Harness should become a local-first control plane with hosted deployment as an option, not a requirement.

For individual operators, the simplest credible stack is:

- local Harness runtime
- local SQLite database
- local macOS app shell
- replaceable ingress/executor integration such as OpenClaw, Hermes, Codex, or a future desktop agent client
- direct API connections to systems of record such as GitHub and Linear

Docker is useful for reproducible demos and developer isolation. It should not be the normal-user path. Hosted Vercel/Postgres remains useful for shared/team operation. It should not be required for a single operator to trust local AI-assisted work.

## Non-Developer Bar

The v1 local app must satisfy this bar:

- no repo clone
- no terminal setup
- no Docker install
- no Python install
- no Node or `pnpm` install
- no manual `.env.local` editing
- no GitHub CLI or Linear CLI requirement
- no Xcode or command-line tools requirement for basic verification

If a feature requires an external account, folder, or token, the app must explain why, ask at the right time, validate immediately, and show the next fix when validation fails.

## V1 Product Shape

The first macOS app has two surfaces.

### Menu-Bar Controller

The menu bar is the always-available operational surface.

It should show:

- Harness running/stopped/error state
- local API health
- local DB health
- active task count
- review-needed count
- repair-needed or stalled count when available
- integration setup warnings

It should expose:

- start Harness
- stop Harness
- restart Harness
- open dashboard
- run doctor
- open logs
- open settings
- quit app

The menu bar reads status through Harness API/status surfaces. It must not inspect or mutate the SQLite database directly.

### Embedded Dashboard Window

The dashboard window is for full progress and detail.

It should reuse the existing Harness web dashboard inside the app rather than rebuilding a native dashboard in v1. The dashboard remains read-only unless a future product decision explicitly adds governed mutation surfaces.

The window should open from the menu bar and display the local dashboard against the app-managed local Harness API. Closing the dashboard window must not stop the local runtime.

## High-Level Architecture

```text
Harness.app
  macOS shell
    menu-bar controller
    onboarding/setup assistant
    settings
    embedded dashboard window
    notification bridge
    launch-at-login integration
    Keychain integration
    runtime process supervisor

  bundled Harness runtime
    Python backend/API
    static or packageable dashboard assets
    SQLite migrations
    doctor checks
    CLI/process contract

Local state
  ~/Library/Application Support/Harness/
    harness.db
    config.json
    runtime/
    migrations/

  ~/Library/Logs/Harness/
    harness.log
    app.log

External systems
  GitHub API
  Linear API
  ingress/executor client API or local bridge
```

Harness core remains the control plane. The app shell is an operator-facing wrapper and supervisor. It controls local process lifecycle, configuration, onboarding, and display, but canonical task truth still flows through Harness APIs.

## Runtime Boundary

The app should control a stable runtime contract, not internal Python modules.

The target runtime commands are:

- `harness init`
- `harness start`
- `harness serve`
- `harness status`
- `harness doctor`
- `harness open`
- `harness stop`
- `harness recover`

The app may call an internal executable or bundled launcher rather than a user-installed shell command, but the behavior should match the same contract. A CLI shim can be installed later for power users.

The runtime must expose:

- stable local API base URL
- health endpoint
- status endpoint suitable for menu-bar polling
- doctor endpoint or CLI output suitable for UI rendering
- graceful shutdown path
- deterministic exit codes
- operator-readable startup failures

The runtime must not depend on a developer checkout. Developer mode may still point at a repo checkout for local engineering work, but normal mode must run from the installed app bundle and app-managed data directories.

## Persistence

SQLite is the default local app store.

Default macOS path:

```text
~/Library/Application Support/Harness/harness.db
```

SQLite requirements:

- `HARNESS_STORE_BACKEND=sqlite`
- WAL mode
- foreign keys enabled
- schema migrations with recorded schema version
- explicit transaction boundaries
- append-only evaluation history preserved
- local reset verifier contracts persisted in SQLite or through a SQLite-backed equivalent store
- clear startup error when the DB is missing, locked, corrupted, or requires an unsupported migration

The app shell and ingress/executor clients must never write SQLite directly. All canonical writes go through Harness APIs.

Postgres remains the hosted/team backend. The existing JSON file store should remain available for development fixtures and tests, but it should no longer be the default serious local persistence mode once SQLite lands.

## Dashboard Packaging

The app should not require Node or `pnpm` on the user's machine.

The preferred v1 path is to make the dashboard packageable as prebuilt assets served by the local Harness runtime or embedded app shell. If the current Next.js dashboard requires server-side runtime behavior that blocks static packaging, issue [#319](https://github.com/sfayka/Harness/issues/319) must decide between:

- refactoring the dashboard into a static/local-app-friendly bundle
- bundling a minimal Node runtime
- introducing a separate local dashboard server process

The preferred decision is static/local-app-friendly assets. Bundling Node is acceptable only if it is the smallest reliable path and remains invisible to users.

The dashboard must keep the existing integrity rule: if the local backend is unavailable, show a clear error. Do not silently switch to sample data.

## Onboarding

The first-run setup assistant should get the user to a healthy local runtime first, then guide optional integrations.

Flow:

1. Welcome: explain that Harness runs locally and verifies AI-assisted work.
2. Local runtime: create app directories, initialize SQLite, start the local API.
3. Run at Login: optional but encouraged.
4. Notifications: optional but encouraged.
5. Workspace folder access: optional; ask only when local repo/workspace inspection is enabled.
6. Connect tools: GitHub, Linear, and ingress/executor client setup as separate items.
7. Doctor check: validate configured components.
8. Open dashboard: show the first successful local state.

The user must be able to complete onboarding with only a healthy local Harness runtime. GitHub, Linear, and executor setup can remain incomplete setup items until a workflow needs them.

Every setup item should follow this pattern:

- what this does
- what the user needs
- action button
- validation result
- exact fix when validation fails

Normal setup must not tell users to edit env files.

## Permissions

The app should ask for the minimum permissions that map to real user value.

### Launch at Login

Ask during onboarding. It is optional but encouraged.

The user should be able to enable or disable it later from Settings.

### Notifications

Ask during onboarding. It is optional but encouraged.

Initial notification events:

- manual review needed
- repair dispatch failed
- executor appears stalled
- budget threshold crossed
- integration credential expired or disconnected

Notification denial must not block core app usage.

### Folder Access

Do not request broad Full Disk Access in v1.

When Harness needs to inspect local repos, artifacts, or logs outside app-owned directories, ask the user to select the relevant folder through the standard macOS picker. Store scoped access only for selected folders.

### Keychain

Use macOS Keychain for secrets.

This should be presented as part of setup, but it should not feel like a scary permission grab. The app should explain that tokens are stored securely and are not written to config files or logs.

## Configuration And Secrets

Non-secret config lives under:

```text
~/Library/Application Support/Harness/config.json
```

Secrets live in Keychain.

Initial secret classes:

- GitHub token or OAuth credential
- Linear token or OAuth credential
- ingress/executor API tokens or local bridge credentials
- repair callback bearer token if configured

The runtime needs a stable app-provided configuration interface so it can read required secrets without plaintext env files. Developer mode may continue supporting `.env.local`, but the app path must not depend on it.

## Integrations

Harness remains client-neutral.

The app can guide setup for specific current implementations, but the architecture should describe roles:

- GitHub: artifact evidence source
- Linear: work coordination surface and structured-work system of record
- ingress/executor: OpenClaw, Hermes, Codex, or future desktop agent client

Ingress/executor integrations may submit intent, completion claims, and repair responses through canonical Harness API boundaries. They may not bypass Harness by writing the DB, changing lifecycle truth directly, or asserting completion without verification.

## Doctor Checks

Doctor checks are a product surface, not just debug output.

Initial checks:

- app directories exist and are writable
- SQLite DB exists, opens, and is on the expected schema
- Harness runtime starts
- local API health endpoint responds
- dashboard assets are available
- menu bar can read status
- notifications permission state is known
- Launch at Login state is known
- GitHub credential validates when configured
- Linear credential validates when configured
- ingress/executor connection validates when configured
- selected workspace folders remain accessible

Each check must return:

- status: pass, warn, fail, skipped
- impact in plain language
- next action
- machine-readable code for UI routing and support

Normal user surfaces should never show raw stack traces as the primary failure message.

## Packaging

The v1 macOS app should be self-contained enough for normal users.

Package contents should include:

- macOS app shell
- bundled Harness Python runtime or equivalent packaged executable runtime
- required Python dependencies
- packaged dashboard assets or dashboard runtime
- SQLite migrations
- doctor checks
- default configuration templates
- app icons and metadata

The package must not require:

- user-installed Python
- user-installed Node
- user-installed Docker
- user-installed GitHub CLI
- user-installed Linear CLI
- Xcode
- command-line tools for basic use

Signing and notarization are required before external distribution. Internal development builds may be unsigned or ad-hoc signed, but the release path must be documented and reproducible.

## Updates And Migration

App updates must preserve local state.

Update requirements:

- run DB migrations before serving requests that require the new schema
- back up or checkpoint the SQLite DB before destructive migrations
- show clear recovery instructions if migration fails
- keep user config and Keychain secrets intact
- record app/runtime version for support

Automatic updates are not required for the first implementation slice, but the packaging design should avoid blocking a future update channel.

## Logging And Support

Logs live under:

```text
~/Library/Logs/Harness/
```

At minimum:

- app shell log
- Harness runtime log
- doctor run log
- packaging/update log when relevant

The app should include an "Open Logs" action and a "Copy Diagnostic Summary" action that excludes secrets.

## Security And Privacy

Security defaults:

- bind the local API to loopback only by default
- do not expose local Harness over the network unless explicitly configured later
- store secrets in Keychain
- redact tokens from logs and doctor output
- do not grant broad filesystem access by default
- do not make notification content leak sensitive task details unnecessarily
- do not let dashboard fallback/sample data impersonate live local truth

The app shell is not a privileged bypass. It does not directly mutate lifecycle truth, DB rows, verification results, reconciliation results, or evaluation history.

## Linux Portability Boundary

macOS ships first, but these pieces must stay portable:

- Python Harness runtime
- SQLite schema and migrations
- CLI/process contract
- API contract
- dashboard assets
- doctor check model
- integration semantics

macOS-specific adapters should sit behind replaceable boundaries:

| macOS v1 | Linux later |
| --- | --- |
| Keychain | Secret Service/libsecret or encrypted local config fallback |
| Launch at Login / LaunchAgent / SMAppService | systemd user service or desktop autostart |
| UserNotifications | freedesktop notifications |
| `.app` bundle / installer | AppImage, deb, rpm, or tarball |
| Finder folder picker | XDG portal or toolkit-native folder picker |

Do not rewrite Harness core in Swift. A native macOS shell is acceptable, but the control-plane runtime must remain portable.

## Repo Strategy

Keep the work in the Harness repo for v1.

Reasons:

- SQLite store, runtime CLI, dashboard packaging, and app shell all need to move together initially.
- Splitting now would force cross-repo coordination before the boundaries are proven.
- The source-of-truth docs and issues already live in Harness.

A separate repo can be reconsidered after the local runtime contract stabilizes and if installer/release mechanics become large enough to justify isolation.

## Issue Mapping

Implementation should proceed in this order:

1. [#317 Add SQLite-backed Harness store for default local persistence](https://github.com/sfayka/Harness/issues/317)
2. [#318 Add local runtime CLI and process contract](https://github.com/sfayka/Harness/issues/318)
3. [#319 Make the dashboard packageable for embedded local app use](https://github.com/sfayka/Harness/issues/319)
4. [#320 Add app-managed configuration and Keychain-backed secrets](https://github.com/sfayka/Harness/issues/320)
5. [#321 Add guided GitHub, Linear, and ingress/executor setup](https://github.com/sfayka/Harness/issues/321)
6. [#322 Add setup doctor checks and user-friendly remediation](https://github.com/sfayka/Harness/issues/322)
7. [#323 Build macOS menu-bar controller and status summary](https://github.com/sfayka/Harness/issues/323)
8. [#324 Embed the Harness dashboard in the macOS app](https://github.com/sfayka/Harness/issues/324)
9. [#325 Build first-run onboarding setup assistant](https://github.com/sfayka/Harness/issues/325)
10. [#326 Add Launch at Login and local daemon lifecycle management](https://github.com/sfayka/Harness/issues/326)
11. [#327 Add macOS notifications for Harness attention events](https://github.com/sfayka/Harness/issues/327)
12. [#328 Package a self-contained macOS app with bundled Harness runtime](https://github.com/sfayka/Harness/issues/328)
13. [#329 Define Linux portability contract for the local Harness runtime](https://github.com/sfayka/Harness/issues/329)

Some work can run in parallel after #317, #318, and #319 establish the runtime and packaging base. The macOS shell should not be built against ad hoc runtime assumptions.

## Validation Strategy

Each implementation slice needs validation appropriate to its boundary.

Backend/runtime:

- store behavior tests across file, SQLite, and Postgres where relevant
- migration tests
- process lifecycle tests for start/status/stop
- doctor output tests

Dashboard:

- `pnpm lint`
- `pnpm build`
- embedded/local asset smoke
- backend-unavailable error state

macOS shell:

- app launches on a clean macOS user account
- first-run onboarding completes with no integrations configured
- SQLite DB is created in Application Support
- runtime starts and survives dashboard window close
- menu bar can start, stop, restart, recover, and run doctor
- dashboard opens inside the app
- Launch at Login can be enabled and disabled
- notifications permission denial does not block app use
- logs and diagnostic summary exclude secrets

Packaging:

- install on a machine without repo checkout
- no user-installed Python, Node, pnpm, Docker, GitHub CLI, or Linear CLI required
- signing/notarization path documented
- upgrade preserves DB, config, and Keychain secrets

## Definition Of Done For Local App V1

Harness Local App V1 is done when a normal macOS user can:

1. Install Harness.
2. Open the app.
3. Complete first-run setup without terminal commands.
4. Start the local runtime.
5. See healthy menu-bar status.
6. Open the embedded dashboard.
7. Persist task/evaluation state in SQLite across restarts.
8. Connect GitHub and Linear through guided setup when ready.
9. Connect a supported ingress/executor path when ready.
10. Run doctor and understand any missing setup item.

If any step requires a developer toolchain, repo clone, Docker, Python, Node, `pnpm`, or env-file editing, v1 has missed the product bar.
