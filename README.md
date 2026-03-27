# Harness

> Linear tracks intended work, GitHub proves executed artifacts, Harness decides what is actually true.

Harness is a control plane and reliability layer for AI-assisted work. It sits underneath work surfaces such as Linear and ingress clients such as OpenClaw. It evaluates whether work is actually complete, evidence-backed, reconciled, and safe to accept.

## What Harness Is

Harness is a standalone service and library that:

- normalizes work into a canonical `TaskEnvelope`
- persists task state and append-only evaluation history
- validates evidence and external facts
- reconciles Harness state with Linear and GitHub
- enforces lifecycle transitions and manual-review outcomes
- exposes read-only inspection surfaces for operators and dashboards

## What Harness Is Not

Harness is not:

- a PM tool
- an agent runtime
- a chatbot UI
- a replacement for Linear's work-coordination surface
- a replacement for GitHub as the artifact system of record
- a place where agent-reported success is trusted by default

Harness does not try to make agents smarter. It makes agent-driven work auditable and enforceable.

## System Of Record Model

- Linear = intended work
- GitHub = execution artifacts
- Harness = lifecycle truth, verification, reconciliation, and enforcement

That split is deliberate:

- Linear remains the human and agent work surface
- GitHub remains the artifact and code-change surface
- Harness remains the control plane that decides whether completion is trustworthy

## Core System Model

The core product rule is simple:

> Work is not complete because an agent says it is complete. Work is complete only when policy allows it based on evidence, reconciliation, and lifecycle enforcement.

That means:

- agent-reported success is advisory only
- completion must be evidence-backed when policy requires it
- reconciliation mismatches must not be silently ignored
- review decisions must be explicit and auditable
- lifecycle state transitions are policy-enforced, not worker-defined

## Architecture Overview

At a high level:

1. an ingress client submits new work or updates
2. Harness normalizes that input into a canonical `TaskEnvelope`
3. Harness evaluates evidence, runtime facts, reconciliation facts, and review state
4. Harness persists task snapshots and append-only evaluation records
5. operators and the dashboard inspect canonical read-model and timeline APIs

Current implementation highlights:

- Python backend for control-plane evaluation, persistence, and API surfaces
- canonical `TaskEnvelope` and schema validation
- evidence, reconciliation, verification, lifecycle, and manual-review primitives
- stateful HTTP API with submission and reevaluation
- dashboard-friendly read-model and timeline endpoints
- Next.js read-only dashboard built on those canonical inspection APIs
- demo, simulator, OpenClaw-style spike, and goal-to-work helper flows

## Repository Layout

- `modules/`
  Python control-plane implementation, connectors, API, persistence, simulator, demo helpers, and goal-to-work flow.
- `app/`, `components/`, `lib/`
  Next.js dashboard and frontend wiring.
- `schemas/`
  Canonical machine-readable contracts, including `TaskEnvelope`.
- `tests/`
  Python backend and integration tests.
- `docs/architecture/`
  Architecture, contract, and boundary docs.
- `docs/demo/`
  Demo walkthrough guidance.
- `docs/integration/`
  Integration notes such as the OpenClaw boundary spike.
- `docs/setup/`
  Local development and run guidance.

## Run Modes

Harness supports three operational modes with the same control-plane behavior. Local and test flows can keep the file-backed store, while hosted backends can switch to durable Postgres persistence.

### Run Mode 1: Native Local Development

Use this mode for fast iteration, backend changes, frontend changes, and direct test execution.

Backend setup:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Frontend setup:

```bash
pnpm install --frozen-lockfile
cp .env.example .env.local
```

Set the dashboard proxy target:

```bash
HARNESS_API_BASE_URL=http://127.0.0.1:8000
```

Run the API:

```bash
.venv/bin/python -m modules.api --store-root .harness-store
```

To use durable Postgres-backed persistence instead of local files:

```bash
export HARNESS_STORE_BACKEND=postgres
export DATABASE_URL=postgresql://...
.venv/bin/python -m modules.api
```

By default the API now binds to `0.0.0.0` and uses `PORT` when it is set, which matches Render-style deployment expectations. Locally you can still reach it via `http://127.0.0.1:8000`.

Run the dashboard:

```bash
pnpm dev
```

Run the one-command demo bootstrap:

```bash
python -m modules.demo_bootstrap
```

Useful bootstrap variants:

```bash
python -m modules.demo_bootstrap --exit-after-seed
python -m modules.demo_bootstrap --json --exit-after-seed
python -m modules.demo_bootstrap successful_completion review_required_then_completed
```

### Run Mode 2: Docker

Use this mode for a clean environment, reproducible demos, and onboarding without local Python or Node setup drift.

Start the API and dashboard containers:

```bash
docker compose up --build
```

Seed the deterministic demo scenarios from inside the API container:

```bash
docker compose exec api python -m modules.demo_bootstrap --exit-after-seed
```

Docker mode details:

- dashboard: [http://127.0.0.1:3000](http://127.0.0.1:3000)
- API: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- persisted store: `./.docker-store`
- demo walkthrough artifacts: `./.docker-demo-output/walkthrough`
- dashboard container uses `HARNESS_API_BASE_URL=http://api:8000`
- the bootstrap command reuses the already-running Docker API and dashboard instead of starting duplicate processes

Reset Docker demo data:

```bash
docker compose down
rm -rf .docker-store .docker-demo-output
docker compose up --build
```

### Run Mode 3: Vercel

Vercel is frontend-only in this repository. The dashboard deploys independently, and the backend is not deployed there.

Requirements for Vercel:

- deploy the Next.js dashboard
- set `HARNESS_API_BASE_URL` to a reachable Harness backend
- for durable hosted state, configure the backend with `HARNESS_STORE_BACKEND=postgres` and `DATABASE_URL`
- expect clearly labeled sample or fallback behavior if no backend is reachable

`vercel.json` already forces Next.js detection so the repo is not treated as a Python-only project.

### Hosted Render + Supabase

For hosted durability without changing the API surface:

1. Create a Supabase project and copy the Postgres connection string into `DATABASE_URL`.
2. Run [`sql/postgres/001_harness_store.sql`](/Users/ssbob/Documents/Developer/Knox_Analytics/Harness/sql/postgres/001_harness_store.sql) through the Supabase SQL editor or `psql`.
3. Deploy the Python backend to Render with:
   `HARNESS_STORE_BACKEND=postgres`
   `DATABASE_URL=<Supabase Postgres connection string>`
4. Point Vercel at the Render backend with `HARNESS_API_BASE_URL=https://<render-service-url>`.

This keeps `/tasks`, `/tasks/<task_id>/read-model`, and `/tasks/<task_id>/timeline` backed by durable Postgres state, so redeploys do not clear hosted task history.

## Demo Walkthrough

Harness includes a deterministic seeded walkthrough for local product demos, screenshots, and operator narration.

Local/manual walkthrough commands:

```bash
python -m modules.demo_walkthrough reset --store-root .demo-store --output-dir demo-output/walkthrough
.venv/bin/python -m modules.api --host 127.0.0.1 --port 8000 --store-root .demo-store
pnpm dev
python -m modules.demo_walkthrough seed \
  --base-url http://127.0.0.1:8000 \
  --dashboard-url http://127.0.0.1:3000 \
  --output-dir demo-output/walkthrough
```

Docker walkthrough commands:

```bash
docker compose up --build
docker compose exec api python -m modules.demo_bootstrap --exit-after-seed
```

Seeded tasks include:

- `demo-successful-completion`
- `demo-missing-evidence-then-completed`
- `demo-contradictory-facts-blocked`
- `demo-review-required-then-completed`
- `demo-long-running-handoff`

## Environment Variables

- `HARNESS_API_BASE_URL`
  Required by the Next.js proxy route. In local mode it usually points to `http://127.0.0.1:8000`. In Docker it is set to `http://api:8000`. In Vercel it must point to a reachable external Harness backend.
- `HARNESS_DASHBOARD_URL`
  Optional helper used by Docker demo bootstrap reuse mode so `modules.demo_bootstrap` can seed against the already-running dashboard service.
- `HARNESS_DEMO_BOOTSTRAP_REUSE_SURFACES`
  Optional helper flag. When set, `modules.demo_bootstrap` reuses existing API and dashboard URLs from the environment instead of starting local processes.
- `HARNESS_STORE_ROOT`
  Optional helper for Docker bootstrap reuse mode and local file-backed runs. It points the bootstrap command at the same file-backed store the API container is serving.
- `HARNESS_STORE_BACKEND`
  Optional backend selector for the API process. Supported values are `file` and `postgres`. Default is `file`.
- `DATABASE_URL`
  Required when `HARNESS_STORE_BACKEND=postgres`. Harness uses Supabase as plain Postgres only and stores canonical task and evaluation payloads as JSONB.
- `HARNESS_DEMO_OUTPUT_DIR`
  Optional helper for Docker bootstrap reuse mode. It controls where demo walkthrough artifacts are written inside the container.

See [.env.example](.env.example) and [docs/setup/local-development.md](docs/setup/local-development.md).

## Data / Store Behavior

- native local API data defaults to `./.harness-store`
- native local demo bootstrap defaults to `./.demo-store`
- Docker API data persists in `./.docker-store`
- hosted durable API state can persist in Supabase Postgres when `HARNESS_STORE_BACKEND=postgres`
- Docker walkthrough artifacts persist in `./.docker-demo-output/walkthrough`
- resetting demo state deletes persisted task snapshots and evaluation history for that chosen store root

## High-Level API Surface

Health and inspection:

- `GET /health`
  Returns `status`, `store_backend`, `database_configured`, `database_host`, and `database_schema_ready` so operators can confirm whether the backend is using the file store or Postgres and whether the expected schema is present without exposing credentials.
- `GET /tasks`
- `GET /tasks/<task_id>`
- `GET /tasks/<task_id>/evaluations`
- `GET /tasks/<task_id>/read-model`
- `GET /tasks/<task_id>/timeline`

Submission and reevaluation:

- `POST /tasks`
- `POST /tasks/<task_id>/reevaluate`
- `POST /evaluate`
- `POST /ingress/linear`

Important behavior:

- `POST /tasks` is the canonical submission path for new work
- duplicate task IDs are rejected with `409 Conflict`
- reevaluation is explicit and uses `POST /tasks/<task_id>/reevaluate`
- read-model and timeline endpoints are the canonical inspection surfaces for the dashboard

## Integration Model

### Linear

Linear is the work surface and structured-work system of record.

Linear sends:

- issue identity
- title and description
- optional labels and priority
- optional linked artifacts or external references

Harness derives:

- canonical `TaskEnvelope`
- required artifacts
- verification expectations
- reconciliation expectations

Harness returns:

- current control-plane outcome
- evidence validation result
- reconciliation result
- required follow-up actions

### GitHub

GitHub is the source of truth for executed artifacts.

Harness consumes normalized GitHub facts rather than raw vendor payloads. GitHub-backed artifacts such as commits and pull requests can support verification and reconciliation, but they do not bypass policy enforcement on their own.

### OpenClaw And Other Ingress Clients

OpenClaw and similar clients are ingress surfaces, not control-plane owners.

Current state:

- the OpenClaw integration spike showed the API boundary is clean
- the remaining ingress friction is request construction ergonomics, not architecture failure
- the thin request-builder adapter exists to reduce payload verbosity without redesigning `POST /tasks`

See:

- [docs/integration/openclaw-harness-spike.md](docs/integration/openclaw-harness-spike.md)
- [docs/integrations/overview.md](docs/integrations/overview.md)

## Current Integration Status / Maturity

What is mature enough to use locally:

- canonical submission and reevaluation APIs
- persisted task snapshots and append-only evaluation history
- read-model and timeline inspection APIs
- dashboard read-only inspection
- simulator, demo bootstrap, and deterministic walkthroughs
- Linear-shaped ingress adapter
- thin OpenClaw-informed client spike

What remains intentionally narrow:

- no live GitHub polling or webhook integration
- no live Linear synchronization service
- no production auth or multi-tenant service layer
- no production-grade database backend
- no mutation UI in the dashboard

## What Is Real Today Vs Simulated Today

Real today:

- backend evaluator and enforcement primitives
- persistence store
- HTTP API
- dashboard read-model and timeline inspection
- deterministic demo walkthrough and seeded tasks
- request-builder and ingress adapters

Simulated or intentionally narrow today:

- OpenClaw-style client behavior is a spike, not a full runtime integration
- Linear ingress is an adapter/example flow, not live Linear API creation
- demo scenarios use canonical facts and seeded state, not live external systems
- preview fallback data is sample data only

Fallback data must always be clearly marked and must never silently impersonate live backend truth.

## Testing / Validation Commands

Backend:

```bash
.venv/bin/python -m unittest discover -s tests
```

Frontend:

```bash
pnpm lint
pnpm build
```

Focused examples:

```bash
.venv/bin/python -m unittest tests.test_api tests.test_read_model tests.test_demo_walkthrough
.venv/bin/python -m unittest tests.connectors.test_openclaw_harness_spike
```

## Troubleshooting

### Dashboard shows sample data instead of live tasks

- confirm the Python API is running
- confirm `HARNESS_API_BASE_URL` is set in `.env.local`
- confirm the task exists via `GET /tasks` or `GET /tasks/<task_id>`

### Docker containers start but the dashboard is empty

- run `docker compose exec api python -m modules.demo_bootstrap --exit-after-seed`
- confirm the API returns tasks at [http://127.0.0.1:8000/tasks](http://127.0.0.1:8000/tasks)
- confirm `./.docker-store` contains persisted task files

### Docker reports port conflicts

- confirm nothing else is already bound to `3000` or `8000`
- stop conflicting local processes or change the published ports in `docker-compose.yml`

### Docker rebuilds do not pick up changes

- rerun `docker compose up --build`
- if cached layers still cause confusion, run `docker compose build --no-cache`

### Docker demo state needs a full reset

- run `docker compose down`
- remove `./.docker-store` and `./.docker-demo-output`
- start again with `docker compose up --build`

### Vercel preview builds but shows no live backend data

- set `HARNESS_API_BASE_URL` in the preview environment
- if no backend is reachable, the dashboard should show clearly labeled sample data

### Vercel detects the repo as Python instead of Next.js

- this is handled by [vercel.json](vercel.json), which explicitly marks the repo as a Next.js deployment target

### Duplicate task submission fails

- this is expected behavior
- `POST /tasks` is create-only and duplicate IDs return `409 Conflict`
- use explicit reevaluation for an existing task instead

## Contributing / Development Notes

- start with the architecture docs before changing contracts or enforcement logic
- prefer canonical submission, reevaluation, read-model, and timeline paths over one-off helpers
- keep dashboard behavior read-only unless a task explicitly changes that product scope
- keep mock or sample data clearly labeled and only as fallback when the backend is unavailable
- update docs when changing contracts, invariants, or public API expectations

Useful references:

- [AGENTS.md](AGENTS.md)
- [CONTRIBUTING.md](CONTRIBUTING.md)
- [docs/architecture/system-context.md](docs/architecture/system-context.md)
- [docs/architecture/linear-harness-boundary.md](docs/architecture/linear-harness-boundary.md)
- [docs/architecture/task-envelope.md](docs/architecture/task-envelope.md)

## Architecture Docs

Core docs:

- [docs/architecture/system-context.md](docs/architecture/system-context.md)
- [docs/architecture/linear-harness-boundary.md](docs/architecture/linear-harness-boundary.md)
- [docs/architecture/task-envelope.md](docs/architecture/task-envelope.md)
- [docs/architecture/artifact-and-completion-evidence.md](docs/architecture/artifact-and-completion-evidence.md)
- [docs/architecture/reconciliation-rules.md](docs/architecture/reconciliation-rules.md)
- [docs/architecture/state-transition-enforcement.md](docs/architecture/state-transition-enforcement.md)
- [docs/architecture/operator-and-manual-review.md](docs/architecture/operator-and-manual-review.md)
- [docs/architecture/module-boundaries.md](docs/architecture/module-boundaries.md)

Supporting docs:

- [docs/setup/local-development.md](docs/setup/local-development.md)
- [docs/integrations/overview.md](docs/integrations/overview.md)
- [docs/demo/operator-walkthrough.md](docs/demo/operator-walkthrough.md)
- [docs/integration/openclaw-harness-spike.md](docs/integration/openclaw-harness-spike.md)

## License

Licensed under the Apache License 2.0. See [LICENSE](LICENSE).
