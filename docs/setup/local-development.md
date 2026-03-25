# Local Development

This guide is the practical local runbook for Harness.

## Prerequisites

- Python 3
- `pnpm`
- a local virtual environment for backend work

## Backend Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run the backend test suite:

```bash
.venv/bin/python -m unittest discover -s tests
```

## Frontend Setup

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

## Run The API

```bash
.venv/bin/python -m modules.api --host 127.0.0.1 --port 8000 --store-root .harness-store
```

## Run The Dashboard

```bash
pnpm dev
```

The dashboard is read-only and depends on the canonical inspection APIs:

- `GET /tasks`
- `GET /tasks/<task_id>/read-model`
- `GET /tasks/<task_id>/timeline`

## One-Command Demo Bootstrap

```bash
python -m modules.demo_bootstrap
```

That command prepares demo state, starts local services, seeds deterministic tasks, and prints direct URLs for operator walkthroughs.

## Manual Walkthrough Flow

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

## Local Vs Preview Behavior

Local mode should use a real backend whenever possible.

Preview mode may use clearly labeled sample data if no backend is reachable. That fallback must remain explicit and must never impersonate live control-plane truth.
