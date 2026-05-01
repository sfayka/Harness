# Configure Proofline

Proofline has two configuration paths: local runtime configuration for CLI/web usage, and repo-root `.env.local` for developer and CI-style runs.

Use Proofline-named commands and environment variables where this guide lists them. Harness-named variables, paths, service names, and stored evidence fields remain compatibility surfaces during the staged rename and should not be removed until the migration guide says they are safe to retire.

## Local Runtime Configuration

The local runtime writes non-secret runtime configuration to:

```text
~/Library/Application Support/Harness/config.json
```

Secrets do not belong in that file. Store local credentials through the runtime-managed secret boundary exposed by the CLI.

Stable compatibility secret names:

- `github_token`, mapped to `GITHUB_TOKEN`
- `linear_api_key`, mapped to `LINEAR_API_KEY`
- `repair_callback_bearer_token`, mapped to `OPENCLAW_REPAIR_BEARER_TOKEN`

From a checkout, the same contract is available through the CLI:

```bash
python3 -m modules.proofline_runtime --json secrets status
printf '%s' "$GITHUB_TOKEN" | python3 -m modules.proofline_runtime --json secrets set github_token --value-stdin
python3 -m modules.proofline_runtime --json secrets status --require github_token
```

Secret status output is redacted. It should never print token values.

## Developer Environment Variables

For repo checkout work, use repo-root `.env.local`.

Common local variables:

- `GITHUB_TOKEN`
- `LINEAR_API_KEY`
- `PROOFLINE_API_BASE_URL=http://127.0.0.1:8000`
- `HARNESS_API_BASE_URL=http://127.0.0.1:8000`
- `PROOFLINE_STORE_BACKEND=file`
- `PROOFLINE_STORE_BACKEND=sqlite`
- `PROOFLINE_SQLITE_PATH=/absolute/path/to/harness.db`
- `PROOFLINE_STORE_BACKEND=postgres`
- `HARNESS_STORE_BACKEND=file`
- `HARNESS_SQLITE_PATH=/absolute/path/to/harness.db`
- `DATABASE_URL`
- `POSTGRES_URL`

`PROOFLINE_API_BASE_URL` is preferred for the dashboard/backend proxy override. `HARNESS_API_BASE_URL` remains a compatibility fallback for existing local files and deployments. Hosted same-project Vercel deployments still derive the backend route automatically and ignore either explicit override.

`PROOFLINE_STORE_BACKEND`, `PROOFLINE_STORE_ROOT`, and `PROOFLINE_SQLITE_PATH` are preferred for local/backend storage selection. `HARNESS_STORE_BACKEND`, `HARNESS_STORE_ROOT`, and `HARNESS_SQLITE_PATH` remain compatibility fallbacks.

## Desktop-Agent Bridge Wiring

The current concrete repair receiver is still OpenClaw-shaped, so some operational variables retain `OPENCLAW_*` names:

- `OPENCLAW_BASE_URL`
- `OPENCLAW_REPAIR_ENDPOINT`
- `OPENCLAW_REPAIR_BEARER_TOKEN`
- `OPENCLAW_CONFIG_PATH`
- `OPENCLAW_STATE_DIR`

Those names are implementation details. Proofline itself should stay client-neutral: OpenClaw, Hermes, Codex, or a future desktop agent can fill the same role if it speaks the canonical acceptance-layer API boundaries.

For hosted repair dispatch, `OPENCLAW_BASE_URL` must point at a receiver reachable from the hosted runtime. A loopback value such as `http://127.0.0.1:18789` only works for local development.

## Storage Choices

Use SQLite for self-contained local CLI/web state:

```bash
export PROOFLINE_STORE_BACKEND=sqlite
export PROOFLINE_SQLITE_PATH="$HOME/Library/Application Support/Harness/harness.db"
```

Use Postgres for hosted or team deployments:

```bash
export PROOFLINE_STORE_BACKEND=postgres
export POSTGRES_URL=postgresql://...
```

Use file storage only for local development, deterministic demos, and tests.
