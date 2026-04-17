# Local Development

This guide covers the practical local and container runbook for Harness.

## Prerequisites

- Python 3
- `pnpm`
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
```

### Run The API

```bash
python3 -m uvicorn backend.server:app --host 127.0.0.1 --port 8000
```

`backend.server` now auto-loads repo-root `.env.local` during native local startup. It also loads `config/openclaw/.env.local` when present so local OpenClaw config and state paths do not need to be duplicated into the shell environment.

For the reset verifier slice, put these in repo-root `.env.local`:

- `GITHUB_TOKEN`
- `LINEAR_API_KEY`
- optional `OPENCLAW_BASE_URL`
- optional `OPENCLAW_REPAIR_ENDPOINT`
- optional `HARNESS_RESET_POLL_SECONDS`

`HARNESS_RESET_POLL_SECONDS` controls how long Harness waits before `/reset/tick` asks OpenClaw to retry a contract already in `retrying`. The production default is `900` seconds. For deterministic local test loops, set it to `0`.

When `config/openclaw/.env.local` provides `OPENCLAW_CONFIG_PATH` or `OPENCLAW_STATE_DIR`, the reset verifier prefers local OpenClaw CLI dispatch over the HTTP callback. `OPENCLAW_BASE_URL` and `OPENCLAW_REPAIR_ENDPOINT` remain the fallback for remote OpenClaw receivers.

That loopback-style fallback is only appropriate for native local development. Do not copy `OPENCLAW_BASE_URL=http://127.0.0.1:...` into hosted Vercel environments, because the reset verifier will not be able to reach your laptop from a serverless runtime.

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
- trigger OpenClaw repair on invalid proof
- escalate to `In Review` after the retry budget is exhausted

### Reset Verifier Dry Runs

The repo now includes deterministic local dry runs for the reset verifier slice:

```bash
python3 -m modules.reset_dryrun success
python3 -m modules.reset_dryrun review
```

These commands:

- start a temporary local FastAPI app
- hit the `/reset/*` routes through the thin OpenClaw-style HTTP client
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
- keeps OpenClaw simulated so the only live systems are Harness, Linear, and GitHub

### Run The Dashboard

```bash
pnpm dev
```

The dashboard is read-only and depends on the canonical inspection APIs:

- `GET /tasks`
- `GET /tasks/<task_id>/read-model`
- `GET /tasks/<task_id>/timeline`

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

Use native local mode when you need fast edit-run-debug loops.

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
