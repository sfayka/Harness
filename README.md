# Harness

Harness is a control plane and reliability layer for AI-assisted work.

It does not trust agent-reported completion on its own. It accepts or blocks lifecycle transitions only after evaluating canonical task state, evidence, reconciliation facts, and explicit review decisions.

## What Harness Is

- A Python control-plane backend that evaluates canonical `TaskEnvelope` submissions.
- A read-only Next.js dashboard over canonical inspection APIs.
- A persistence layer for task snapshots and append-only evaluation history.
- A thin integration boundary around Linear-shaped ingress and GitHub/Linear fact inputs.

Harness is not a PM tool, an agent runtime, or a chatbot UI.

## Current Architecture

### Frontend

- Next.js 16 app in [`app/`](app) with shared dashboard components in [`components/`](components).
- Root route redirects to `/tasks`.
- Main working views:
  - `/tasks`
  - `/verification`
  - `/reconciliation`
  - `/reviews`
- Frontend reads backend data through the Next proxy route at [`app/api/harness/[...path]/route.ts`](app/api/harness/[...path]/route.ts).
- The frontend requires `HARNESS_API_BASE_URL` to point at a reachable backend. If it is missing or unreachable, the UI shows an error; it does not silently switch to fake live data.

### Backend

- Minimal Python HTTP server in [`modules/api.py`](modules/api.py).
- Canonical evaluation and enforcement logic in [`modules/evaluation.py`](modules/evaluation.py) and [`modules/contracts/`](modules/contracts).
- Canonical inspection surfaces:
  - `GET /health`
  - `GET /tasks`
  - `GET /tasks/<task_id>`
  - `GET /tasks/<task_id>/evaluations`
  - `GET /tasks/<task_id>/read-model`
  - `GET /tasks/<task_id>/timeline`
- Canonical mutation surfaces:
  - `POST /tasks`
  - `POST /tasks/<task_id>/reevaluate`
- Integration helper surface:
  - `POST /ingress/linear`

### Persistence

- Store selection is controlled by `HARNESS_STORE_BACKEND`.
- Supported backends:
  - `file` for local JSON-backed development.
  - `postgres` for durable hosted state.
- Postgres storage is implemented in [`modules/store.py`](modules/store.py) and bootstrapped with [`sql/postgres/001_harness_store.sql`](sql/postgres/001_harness_store.sql).
- Current hosted deployment uses Supabase as plain Postgres. Harness stores canonical task and evaluation payloads as JSONB in `tasks` and `evaluation_records`.

## Hosted System

These URLs were verified against the live deployment on March 28, 2026.

- Frontend: [https://harness-mzus2ext1-sean-fays-projects.vercel.app/](https://harness-mzus2ext1-sean-fays-projects.vercel.app/)
- Backend: [https://harness-qeav.onrender.com](https://harness-qeav.onrender.com)
- Health: [https://harness-qeav.onrender.com/health](https://harness-qeav.onrender.com/health)

Current live health payload fields:

- `status`
- `store_backend`
- `database_configured`
- `database_host`
- `database_schema_ready`

The current hosted health response reports:

- `status: "ok"`
- `store_backend: "postgres"`
- `database_configured: true`
- `database_host: "aws-0-us-west-2.pooler.supabase.com"`
- `database_schema_ready: true`

## Key Views And Routes

Frontend routes:

- `/tasks`: broad task inventory and detail panel.
- `/verification`: tasks scoped and sorted around verification outcomes.
- `/reconciliation`: tasks scoped and sorted around mismatch and blocking reconciliation outcomes.
- `/reviews`: tasks with manual review activity.

Backend inspection routes:

- `GET /tasks`: dashboard list surface.
- `GET /tasks/<task_id>/read-model`: canonical detail surface for current task truth.
- `GET /tasks/<task_id>/timeline`: canonical audit timeline.

## Storage And Environment

Required frontend environment variable:

- `HARNESS_API_BASE_URL`
  - Local example: `http://127.0.0.1:8000`
  - Hosted example: `https://harness-qeav.onrender.com`

Backend storage environment variables:

- `HARNESS_STORE_BACKEND`
  - Supported values: `file`, `postgres`
  - Default in [`.env.example`](.env.example): `file`
- `DATABASE_URL`
  - Required when `HARNESS_STORE_BACKEND=postgres`
  - Expected to be a Postgres connection string
  - Used for Supabase/Postgres in the hosted deployment

Relevant supporting files:

- [`.env.example`](.env.example)
- [`sql/postgres/001_harness_store.sql`](sql/postgres/001_harness_store.sql)
- [`docs/setup/local-development.md`](docs/setup/local-development.md)
- [`docs/setup/render-supabase.md`](docs/setup/render-supabase.md)

## Local Development

Backend setup:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run the backend with the file store:

```bash
.venv/bin/python -m modules.api --store-root .harness-store
```

Run the backend with Postgres:

```bash
export HARNESS_STORE_BACKEND=postgres
export DATABASE_URL=postgresql://...
.venv/bin/python -m modules.api
```

The API binds to `0.0.0.0` by default and honors `PORT` when set. Local default access is `http://127.0.0.1:8000`.

Frontend setup:

```bash
pnpm install --frozen-lockfile
cp .env.example .env.local
```

Set:

```bash
HARNESS_API_BASE_URL=http://127.0.0.1:8000
```

Run the frontend:

```bash
pnpm dev
```

Validation commands:

```bash
.venv/bin/python -m unittest discover -s tests
pnpm lint
pnpm build
```

## Demo And Canonical Scenarios

### Local deterministic scenario pack

The canonical demo runner in [`modules/demo_runner.py`](modules/demo_runner.py) defines these scenarios:

- `successful_completion`
- `missing_evidence_then_completed`
- `wrong_target_corrected`
- `review_required_then_completed`
- `contradictory_facts_blocked`
- `long_running_handoff`

For local operator walkthroughs, the seeded demo task IDs are:

- `demo-successful-completion`
- `demo-missing-evidence-then-completed`
- `demo-contradictory-facts-blocked`
- `demo-review-required-then-completed`
- `demo-long-running-handoff`

Seed locally with:

```bash
python -m modules.demo_bootstrap --exit-after-seed
```

Or use the full walkthrough flow in [`docs/demo/operator-walkthrough.md`](docs/demo/operator-walkthrough.md).

### Current hosted examples

As of March 28, 2026, the hosted backend currently contains these useful example tasks:

- Happy path: `dryrun-e2e-test-kno-133-db-seed-v5`
  - current status: `completed`
  - verification outcome: `accepted_completion`
  - reconciliation outcome: `no_mismatch`
- Mismatch path: `dryrun-mismatch-kno-133-db-v1`
  - current status: `failed`
  - verification outcome: `terminal_invalid`
  - reconciliation outcome: `wrong_target`

These are live persisted tasks, not fixed seeded IDs, so they may change later.

## Health Diagnostics

`GET /health` is the operator check for backend readiness and storage configuration.

Current fields:

- `status`: overall service state for this probe.
- `store_backend`: `file` or `postgres`.
- `database_configured`: whether the process is configured for database-backed storage.
- `database_host`: parsed hostname only, without credentials.
- `database_schema_ready`: whether the required `tasks` and `evaluation_records` tables are present.

The health endpoint does not return raw `DATABASE_URL` values or credentials.

## Docs And Screenshots

Useful docs:

- [`docs/architecture/system-context.md`](docs/architecture/system-context.md)
- [`docs/architecture/module-boundaries.md`](docs/architecture/module-boundaries.md)
- [`docs/architecture/task-envelope.md`](docs/architecture/task-envelope.md)
- [`docs/demo/operator-walkthrough.md`](docs/demo/operator-walkthrough.md)
- [`docs/setup/local-development.md`](docs/setup/local-development.md)

Current screenshot assets:

- [`docs/demo/kno-133-happy-path/`](docs/demo/kno-133-happy-path)

## Known Limitations

- The dashboard is read-only. There is no mutation UI for submissions, reevaluation, or review actions.
- The frontend depends on a reachable backend via `HARNESS_API_BASE_URL`; it does not provide an offline sample-data mode in the current code path.
- Live Linear and GitHub synchronization are still thin integration layers rather than full background sync services.
- Review-required handling exists in evaluation, reevaluation, and dashboard summaries, but the hosted backend is not guaranteed to keep a review-required example task seeded at all times.
- Hosted example task IDs are operational data and may change independently of the local deterministic scenario pack.

## Repository Layout

- [`modules/`](modules): backend API, evaluation logic, persistence, demo tooling, connectors.
- [`app/`](app): Next.js routes and proxy handler.
- [`components/`](components): dashboard UI components.
- [`lib/`](lib): frontend API mapping and types.
- [`schemas/`](schemas): canonical machine-readable contracts.
- [`tests/`](tests): backend and integration tests.

## License

Licensed under the Apache License 2.0. See [`LICENSE`](LICENSE).
