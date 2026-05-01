# Configure Harness

Harness has two configuration paths: local runtime configuration for CLI/web usage, and repo-root `.env.local` for developer and CI-style runs.

## Local Runtime Configuration

The local runtime writes non-secret runtime configuration to:

```text
~/Library/Application Support/Harness/config.json
```

Secrets do not belong in that file. Store local credentials through the runtime-managed secret boundary exposed by the CLI.

Stable Harness secret names:

- `github_token`, mapped to `GITHUB_TOKEN`
- `linear_api_key`, mapped to `LINEAR_API_KEY`
- `repair_callback_bearer_token`, mapped to `OPENCLAW_REPAIR_BEARER_TOKEN`

From a checkout, the same contract is available through the CLI:

```bash
python3 -m modules.local_runtime --json secrets status
printf '%s' "$GITHUB_TOKEN" | python3 -m modules.local_runtime --json secrets set github_token --value-stdin
python3 -m modules.local_runtime --json secrets status --require github_token
```

Secret status output is redacted. It should never print token values.

## Developer Environment Variables

For repo checkout work, use repo-root `.env.local`.

Common local variables:

- `GITHUB_TOKEN`
- `LINEAR_API_KEY`
- `HARNESS_API_BASE_URL=http://127.0.0.1:8000`
- `HARNESS_STORE_BACKEND=file`
- `HARNESS_STORE_BACKEND=sqlite`
- `HARNESS_SQLITE_PATH=/absolute/path/to/harness.db`
- `HARNESS_STORE_BACKEND=postgres`
- `DATABASE_URL`
- `POSTGRES_URL`

## Desktop-Agent Bridge Wiring

The current concrete repair receiver is still OpenClaw-shaped, so some operational variables retain `OPENCLAW_*` names:

- `OPENCLAW_BASE_URL`
- `OPENCLAW_REPAIR_ENDPOINT`
- `OPENCLAW_REPAIR_BEARER_TOKEN`
- `OPENCLAW_CONFIG_PATH`
- `OPENCLAW_STATE_DIR`

Those names are implementation details. Harness itself should stay client-neutral: OpenClaw, Hermes, Codex, or a future desktop agent can fill the same role if it speaks the Harness API boundaries.

For hosted repair dispatch, `OPENCLAW_BASE_URL` must point at a receiver reachable from the hosted runtime. A loopback value such as `http://127.0.0.1:18789` only works for local development.

## Storage Choices

Use SQLite for self-contained local CLI/web state:

```bash
export HARNESS_STORE_BACKEND=sqlite
export HARNESS_SQLITE_PATH="$HOME/Library/Application Support/Harness/harness.db"
```

Use Postgres for hosted or team deployments:

```bash
export HARNESS_STORE_BACKEND=postgres
export POSTGRES_URL=postgresql://...
```

Use file storage only for local development, deterministic demos, and tests.
