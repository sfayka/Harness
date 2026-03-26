# Local Development

This guide covers the practical local and container runbook for Harness.

## Prerequisites

- Python 3
- `pnpm`
- a local virtual environment for backend work
- Docker, if you want the containerized mode

## Native Local Development

### Backend Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run the backend test suite:

```bash
.venv/bin/python -m unittest discover -s tests
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
.venv/bin/python -m modules.api --store-root .harness-store
```

The API defaults to binding `0.0.0.0` and will honor the `PORT` environment variable when one is provided by a host such as Render. For local development, access it through `http://127.0.0.1:8000`.

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
python -m modules.demo_bootstrap
```

That command prepares demo state, starts local services, seeds deterministic tasks, and prints direct URLs for operator walkthroughs.

### Manual Walkthrough Flow

Reset:

```bash
python -m modules.demo_walkthrough reset --store-root .demo-store --output-dir demo-output/walkthrough
```

Start API:

```bash
.venv/bin/python -m modules.api --host 127.0.0.1 --port 8000 --store-root .demo-store
```

Start dashboard:

```bash
pnpm dev
```

Seed walkthrough tasks:

```bash
python -m modules.demo_walkthrough seed \
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

Vercel is frontend-only for this repo. It hosts the Next.js dashboard and requires a reachable backend URL through `HARNESS_API_BASE_URL`.

The backend remains a separate Harness process and is not deployed by `vercel.json`.

## Local Vs Preview Behavior

Local mode should use a real backend whenever possible.

Preview mode may use clearly labeled sample data if no backend is reachable. That fallback must remain explicit and must never impersonate live control-plane truth.
