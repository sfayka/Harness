# OpenClaw Local Bootstrap

This document covers one concrete local client implementation. Harness is not architecturally tied to OpenClaw. Hermes or a future desktop agent client can fill the same ingress or supervision role as long as it speaks the canonical Harness boundaries. This file keeps the OpenClaw name because the current repo-owned scripts, config template, and local bootstrap path are OpenClaw-specific.

For Harness-level configuration, use [Configure Harness](../howto/configure-harness.md). This file is only the current OpenClaw-shaped bridge setup.

This document defines a local-first, deterministic OpenClaw bring-up path for Harness.

The goal is not broad Harness ↔ OpenClaw integration yet. The goal is a reproducible macOS-oriented install and config scaffold for one current client implementation that avoids interactive onboarding, keeps config explicit, and gives future adapter work a stable base.

## Why Local-First

OpenClaw is not just a package import. It has installer behavior, state, config, and validation rules. That means an interactive happy-path install is not enough if we want repeatable Harness-side iteration.

This setup path exists so we can:

- install OpenClaw without a wizard
- keep config under repo control
- validate config strictly before future adapter work
- iterate locally on macOS before deciding whether any of this belongs in Codex Cloud

## What This Setup Includes

- [`config/openclaw/openclaw.template.json5`](../../config/openclaw/openclaw.template.json5): minimal repo-owned config template
- [`config/openclaw/.env.example`](../../config/openclaw/.env.example): optional local environment template
- [`scripts/openclaw-bootstrap.sh`](../../scripts/openclaw-bootstrap.sh): non-interactive local bootstrap
- [`scripts/openclaw-validate-local.sh`](../../scripts/openclaw-validate-local.sh): local validation helper

## What This Setup Intentionally Does Not Configure

- channel credentials or routing
- model/provider authentication
- daemon install or background service management
- production network exposure
- Harness runtime integration
- Codex Cloud execution support

This is a local bootstrap and validation scaffold only.

## Bootstrap Flow

The bootstrap script uses the documented OpenClaw CLI installer path and explicitly disables onboarding:

```bash
curl -fsSL --proto '=https' --tlsv1.2 https://openclaw.ai/install-cli.sh | bash -s -- --prefix "$OPENCLAW_INSTALL_PREFIX" --version "$OPENCLAW_VERSION" --no-onboard
```

Why this path:

- it is non-interactive
- it installs into a caller-controlled prefix instead of relying on global npm state
- it keeps onboarding out of the bring-up flow
- it is easy to re-run during local iteration

After install, the script renders a deterministic config file from the repo-owned template and validates it with:

```bash
openclaw --version
openclaw config file
openclaw config validate
```

## Local Setup On macOS

1. Copy the example env file and replace the absolute paths:

```bash
cp config/openclaw/.env.example config/openclaw/.env.local
```

2. Edit `config/openclaw/.env.local` so `OPENCLAW_CONFIG_PATH` and `OPENCLAW_WORKSPACE_PATH` point at your local Harness checkout.

3. Run the bootstrap:

```bash
bash scripts/openclaw-bootstrap.sh
```

4. Validate the install and config:

```bash
bash scripts/openclaw-validate-local.sh
```

If you want to run raw `openclaw ...` commands directly from the shell, add the install prefix to `PATH` first:

```bash
export PATH="$OPENCLAW_INSTALL_PREFIX/bin:$PATH"
```

## Config Location And Overrides

The repo-owned source of truth is the template:

- [`config/openclaw/openclaw.template.json5`](../../config/openclaw/openclaw.template.json5)

The rendered local config defaults to:

- `config/openclaw/openclaw.local.json5`

You can override the rendered config location with:

```bash
export OPENCLAW_CONFIG_PATH=/absolute/path/to/openclaw.local.json5
```

The bootstrap and validation scripts both honor:

- `OPENCLAW_ENV_FILE`
- `OPENCLAW_INSTALL_PREFIX`
- `OPENCLAW_VERSION`
- `OPENCLAW_STATE_DIR`
- `OPENCLAW_CONFIG_PATH`
- `OPENCLAW_WORKSPACE_PATH`
- `OPENCLAW_GATEWAY_BIND`
- `OPENCLAW_GATEWAY_PORT`
- `OPENCLAW_AGENT_ID`

If `OPENCLAW_ENV_FILE` is not set, both scripts automatically load `config/openclaw/.env.local` when it exists.

## Minimal Config Shape

The template keeps the local surface intentionally small:

- `gateway.mode: "local"`
- `gateway.bind: "loopback"`
- `gateway.auth.mode: "none"`
- `agents.defaults.model.primary: "openai-codex/gpt-5.4"`
- one explicit local agent
- workspace path pointed at the local Harness repo
- `skipBootstrap: true` to avoid implicit workspace bootstrap behavior during early setup work

That gives us a deterministic local base without prematurely choosing channels, daemon install, or production auth.

The default model is intentionally set to `openai-codex/gpt-5.4` so a machine already authenticated through Codex OAuth can run embedded local agent turns without adding a separate `OPENAI_API_KEY`.

## Validation Commands

The helper script runs:

```bash
openclaw --version
openclaw doctor --non-interactive
openclaw config file
openclaw config validate --json
openclaw status
```

If the gateway is already running, it also runs:

```bash
openclaw gateway status
openclaw health
```

If the gateway is not running yet, the helper skips those runtime checks and reports that clearly.

## Known Limitations

- This path assumes internet access to fetch the OpenClaw installer.
- The generated config is local-only and intentionally does not configure model credentials.
- `gateway.auth.mode` is set to `none` because the target is same-host local iteration on loopback, not remote access.
- The scripts validate install and config, but they do not install a background service or open any channels.
- This setup does not prove Harness runtime integration. It only proves that a stable, non-interactive OpenClaw local base exists.

## Manual Inputs Still Required Later

Nothing extra is required to bootstrap and validate the config itself beyond editing local paths in `.env.local`.

If you later want to do real agent execution rather than install/config validation, you will still need to supply:

- model/provider authentication
- any channel credentials
- any future Harness adapter wiring
