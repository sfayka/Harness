# Local Development

This guide covers the practical local and container runbook for Harness.

For a reader-facing install and validation path, start with [Local Quickstart](../howto/local-quickstart.md), [Use Harness](../howto/use-harness.md), and [Test And Validate Harness](../howto/test-and-validate.md).

## Prerequisites

- Python 3
- `pnpm`, when developing or rebuilding the dashboard
- Docker, if you want the containerized mode

## Native Local Development

### Backend Setup

```bash
python3 -m pip install -r requirements.txt
```

Codex Cloud assumes system Python is available as `python`. On local machines where only `python3` is present, use `python3` for local commands. Do not assume or require a `.venv`.

Run the dedicated runtime scenario suite:

```bash
python3 -m unittest discover -s tests/e2e -p 'test_*.py'
```

Run the full backend test suite:

```bash
python3 -m unittest discover -s tests
```

### Frontend Setup

```bash
pnpm install --frozen-lockfile
cp .env.example .env.local
```

Set:

```bash
HARNESS_API_BASE_URL=http://127.0.0.1:8000
```

Frontend validation:

```bash
pnpm lint
pnpm build
pnpm build:dashboard:local
pnpm test:frontend
```

### Run The API

```bash
python3 -m uvicorn backend.server:app --host 127.0.0.1 --port 8000
```

`backend.server` now auto-loads repo-root `.env.local` during local startup. It also loads `config/openclaw/.env.local` when present so the current repo-owned desktop-agent config and state paths do not need to be duplicated into the shell environment.

For the reset verifier slice, put these in repo-root `.env.local`:

- `GITHUB_TOKEN`
- `LINEAR_API_KEY`
- optional `OPENCLAW_BASE_URL`
- optional `OPENCLAW_REPAIR_ENDPOINT`
- optional `OPENCLAW_REPAIR_BEARER_TOKEN`
- optional `HARNESS_RESET_POLL_SECONDS`

The `OPENCLAW_*` names remain because the current repair receiver adapter in the repo is OpenClaw-shaped. They are operational names, not the architectural boundary.

`HARNESS_RESET_POLL_SECONDS` controls how long Harness waits before `/reset/tick` asks the configured repair receiver to retry a contract already in `retrying`. The production default is `900` seconds. For deterministic local test loops, set it to `0`.

When `config/openclaw/.env.local` provides `OPENCLAW_CONFIG_PATH` or `OPENCLAW_STATE_DIR`, the reset verifier prefers the current repo-owned OpenClaw CLI dispatch over the HTTP callback. `OPENCLAW_BASE_URL` and `OPENCLAW_REPAIR_ENDPOINT` remain the fallback for remote repair receivers.

If the remote repair receiver is bearer-protected, set `OPENCLAW_REPAIR_BEARER_TOKEN`. Harness will send it as `Authorization: Bearer <token>` on the HTTP repair callback path.

That loopback-style fallback is only appropriate for local development. Do not copy `OPENCLAW_BASE_URL=http://127.0.0.1:...` into hosted Vercel environments, because the reset verifier will not be able to reach your laptop from a serverless runtime.

To run the backend against SQLite local persistence:

```bash
export HARNESS_STORE_BACKEND=sqlite
export HARNESS_SQLITE_PATH="$HOME/Library/Application Support/Harness/harness.db"
python3 -m uvicorn backend.server:app --host 127.0.0.1 --port 8000
```

SQLite mode is the intended persistence base for self-contained local CLI/web usage. It creates the database and schema automatically, enables WAL mode and foreign keys, and stores canonical tasks, evaluation records, and reset verifier contracts in one local database.

If `HARNESS_SQLITE_PATH` is unset, Harness uses the platform local-data default: `~/Library/Application Support/Harness/harness.db` on macOS, `$XDG_DATA_HOME/harness/harness.db` on Linux, or `~/.local/share/harness/harness.db` when `XDG_DATA_HOME` is unset.

### Run The Local Runtime Contract

A future packaged CLI can expose this contract as `harness`. From a repo checkout, use the module entry point:

```bash
python3 -m modules.local_runtime --json init
python3 -m modules.local_runtime --json status
python3 -m modules.local_runtime --json start
python3 -m modules.local_runtime serve
python3 -m modules.local_runtime --json doctor
python3 -m modules.local_runtime --json setup status
python3 -m modules.local_runtime --json secrets status
python3 -m modules.local_runtime --json recover
python3 -m modules.local_runtime --json stop
```

The runtime contract uses app-managed config, SQLite state, PID files, dashboard assets, and logs. A future packaged CLI should not require Docker, Node, `pnpm`, or repo-local shell exports.
Use `start` and `recover` for local background lifecycle control.
Use `serve` only when you intentionally want a foreground backend for debugging.

Default macOS paths:

- `~/Library/Application Support/Harness/config.json`
- `~/Library/Application Support/Harness/harness.db`
- `~/Library/Application Support/Harness/dashboard/`
- `~/Library/Application Support/Harness/runtime/harness.pid`
- `~/Library/Logs/Harness/harness.log`

Local CLI/web secrets use the app-managed secret store instead of `.env.local`:

```bash
printf '%s' "$GITHUB_TOKEN" | python3 -m modules.local_runtime --json secrets set github_token --value-stdin
printf '%s' "$LINEAR_API_KEY" | python3 -m modules.local_runtime --json secrets set linear_api_key --value-stdin
python3 -m modules.local_runtime --json secrets status
```

Secret status output is redacted. Use `--require <secret-name>` when a selected workflow cannot run without that credential.
Developer mode can still use repo-root `.env.local`.

Run setup doctor to get machine-readable setup status:

```bash
python3 -m modules.local_runtime --json doctor
```

Doctor checks report `status`, `impact`, and `next_action` for runtime health, SQLite, dashboard assets, GitHub and Linear credentials, desktop-agent bridge wiring, notifications, launch-at-login, and configured workspace folders. Warnings are actionable but do not block the local runtime. Failures indicate configured setup that cannot be trusted.

Run guided setup for user-facing onboarding items:

```bash
python3 -m modules.local_runtime --json setup status
python3 -m modules.local_runtime --json setup status --workflow github-proof
python3 -m modules.local_runtime --json setup status --workflow linear-sync
python3 -m modules.local_runtime --json setup status --workflow repair-dispatch
```

Default onboarding only requires the local runtime. GitHub, Linear, and ingress/executor setup appears as incomplete optional work until the selected workflow needs it. The ingress/executor setup copy should stay client-neutral: OpenClaw, Hermes, Codex, and future desktop-agent clients are all treated as compatible bridges, not Harness architecture dependencies.

To run the same backend against Postgres instead of the file-backed store:

```bash
export HARNESS_STORE_BACKEND=postgres
export DATABASE_URL=postgresql://...
python3 -m uvicorn backend.server:app --host 127.0.0.1 --port 8000
```

If you pull environment variables from a Vercel-managed Neon project, `POSTGRES_URL` also works directly:

```bash
export HARNESS_STORE_BACKEND=postgres
export POSTGRES_URL=postgresql://...
python3 -m uvicorn backend.server:app --host 127.0.0.1 --port 8000
```

The backend defaults to `http://127.0.0.1:8000` in the local runbook above. Hosted deployments use the Vercel `api` service rather than a separate Render process.

### Reset Verifier Endpoints

The narrow verifier slice is exposed alongside the older TaskEnvelope routes:

- `POST /reset/contracts`
- `GET /reset/contracts`
- `GET /reset/contracts/<contract_id>`
- `POST /reset/contracts/<contract_id>/claims`
- `POST /reset/tick`

Use this path when you want Harness to:

- register a Linear issue verification contract
- verify GitHub proof for a claimed completion
- trigger repair dispatch on invalid proof
- escalate to `In Review` after the retry budget is exhausted

### Reset Verifier Dry Runs

The repo now includes deterministic local dry runs for the reset verifier slice:

```bash
python3 -m modules.reset_dryrun success
python3 -m modules.reset_dryrun review
```

These commands:

- start a temporary local FastAPI app
- hit the `/reset/*` routes through the current thin desktop-agent HTTP client implementation
- avoid mutating real Linear or GitHub state
- prove the two operator-critical paths:
  - retryable invalid proof that later verifies successfully
  - retryable invalid proof that exhausts retries and lands in `In Review`

### Live Reset Smoke

The repo also includes a gated live smoke for Set 2 of the reset redesign:

```bash
HARNESS_RUN_LIVE_RESET_TESTS=1 python3 -m unittest tests.test_reset_live_smoke -v
```

That live smoke:

- creates throwaway issues in the real Linear `HARNESS-DRYRUN` project
- creates real branches, commits, and pull requests in `sfayka/HARNESS-DRYRUN`
- runs the happy path first
- then runs real GitHub-backed unhappy paths for missing PR linkage and wrong SHA review escalation
- keeps the desktop-agent repair side simulated so the only live systems are Harness, Linear, and GitHub

### Next Reset Verifier Test Steps

The next staged test sequence is documented in:

- [`docs/superpowers/plans/2026-04-18-reset-verifier-next-test-steps.md`](../superpowers/plans/2026-04-18-reset-verifier-next-test-steps.md)

That plan moves in five stages:

- deterministic local reset baseline
- local live smoke against Linear and GitHub
- hosted callback reachability proof
- hosted end-to-end remote repair proof
- generic desktop-agent contract smoke through canonical `/tasks` and `/supervision/queue`

### Run The Dashboard

```bash
pnpm dev
```

The dashboard is read-only and depends on the canonical inspection APIs:

- `GET /tasks`
- `GET /tasks/<task_id>/read-model`
- `GET /tasks/<task_id>/timeline`

### Build The Packaged Local Dashboard

For the self-contained local CLI/web path, build static dashboard assets instead of running a Node dashboard server:

```bash
pnpm build:dashboard:local
```

This writes:

```text
dist/local-dashboard/
```

The local bundle is served by the Python backend at `/dashboard` and calls the same-origin Harness API directly.
It does not use the Next proxy route and it does not fall back to sample data.

Smoke it from a checkout:

```bash
HARNESS_DASHBOARD_ASSETS_DIR="$PWD/dist/local-dashboard" \
python3 -m uvicorn backend.server:app --host 127.0.0.1 --port 8765
```

Then open:

```text
http://127.0.0.1:8765/dashboard/
```

The normal hosted/developer dashboard still uses `pnpm dev` or `pnpm build` and the Next proxy route.

### Deprecated macOS Package Path

The native macOS package path is deprecated. Do not use `./script/package_macos_app.sh`, Developer ID signing, notarization, or DMG output as the normal Harness validation or release path unless a future task explicitly reopens the native app decision.

The reusable packaging work that remains relevant is the static dashboard bundle plus the local runtime contract above.

### One-Command Demo Bootstrap

```bash
python3 -m modules.demo_bootstrap
```

That command prepares demo state, starts local services, seeds deterministic tasks, and prints direct URLs for operator walkthroughs.

### Manual Walkthrough Flow

Reset:

```bash
python3 -m modules.demo_walkthrough reset --store-root .demo-store --output-dir demo-output/walkthrough
```

Start API:

```bash
HARNESS_STORE_ROOT=.demo-store python3 -m uvicorn backend.server:app --host 127.0.0.1 --port 8000
```

Start dashboard:

```bash
pnpm dev
```

Seed walkthrough tasks:

```bash
python3 -m modules.demo_walkthrough seed \
  --base-url http://127.0.0.1:8000 \
  --dashboard-url http://127.0.0.1:3000 \
  --output-dir demo-output/walkthrough
```

Use local mode when you need fast edit-run-debug loops.

## Docker Mode

Start the API and dashboard:

```bash
docker compose up --build
```

Seed the deterministic demo scenarios:

```bash
docker compose exec api python -m modules.demo_bootstrap --exit-after-seed
```

Docker mode uses:

- dashboard on `http://127.0.0.1:3000`
- API on `http://127.0.0.1:8000`
- persisted store at `./.docker-store`
- walkthrough artifacts at `./.docker-demo-output/walkthrough`
- bootstrap reuse variables are injected by `docker-compose.yml` so `docker compose exec api python -m modules.demo_bootstrap --exit-after-seed` targets the running API store instead of a second local store

Reset Docker state:

```bash
docker compose down
rm -rf .docker-store .docker-demo-output
```

Use Docker mode when you want a reproducible demo or clean onboarding environment.

## Vercel Preview / Hosted Frontend

Harness now prefers a single-project hosted deployment on Vercel `Services`.

That hosted shape is:

- dashboard served by the `web` service
- backend served by the `api` service
- Postgres provided by Neon through Vercel

See [`docs/setup/vercel-neon.md`](vercel-neon.md) for the default hosted runbook.

## Local Vs Hosted Behavior

Local frontend development can still use `HARNESS_API_BASE_URL` as an explicit override.

Hosted deployments running behind the same Vercel project derive the backend route automatically from the deployment URL and the `/backend` route prefix.

If the backend is unreachable or the route cannot be derived, the frontend shows an explicit proxy error instead of silently substituting sample data.
