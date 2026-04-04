# Harness

Harness is a control plane and reliability layer for AI-assisted work.

It does not trust agent-reported completion on its own. It accepts or blocks lifecycle transitions only after evaluating canonical task state, evidence, reconciliation facts, and explicit review decisions.

## What Harness Is

- A Python control-plane backend that evaluates canonical `TaskEnvelope` submissions.
- A read-only Next.js dashboard over canonical inspection APIs.
- A persistence layer for task snapshots and append-only evaluation history.
- A thin integration boundary around Linear/manual/OpenClaw ingress and GitHub/Linear fact inputs.
- An operational reconciliation path that can enter `reconciling`, repair missing PR artifacts, and then delegate back into canonical reevaluation.

Harness is not a PM tool, an agent runtime, or a chatbot UI.

## Governed Reconciliation

Harness distinguishes execution from completion.

Tasks only reach terminal success through artifact-backed reevaluation, not execution claims alone. For recoverable defects such as `missing_pr_after_execution`, Harness spends automation before operator attention: it moves the task into `reconciling`, runs a bounded reconciliation handler, and then returns to canonical reevaluation.

If recovery succeeds, the task can proceed to `completed` through normal reevaluation. If recovery fails or is blocked, Harness escalates explicitly to `in_review` instead of silently accepting the task as done.

Recoverable defects should not require immediate human babysitting, but Harness does not assume all recovery cases are safe or automatic.

Governed reconciliation (current scope):

- Proven failure-path: KNO-174
  → recovery blocked → explicit escalation (`in_review`)

- Proven success-path: KNO-175
  → recovery succeeds → PR attached → reevaluation → `completed`

- Current implemented class:
  → missing_pr_after_execution

- Principle:
  → Harness spends automation before operator attention

## Governed Reconciliation Proofs

The repository now includes proof records for the `missing_pr_after_execution` reconciliation class:

- [`docs/demo/kno-174-missing-pr-after-execution/README.md`](docs/demo/kno-174-missing-pr-after-execution/README.md): governed failure-path proof. This shows safe escalation when recovery is blocked by external GitHub limitations and the task lands in `in_review` with structured reconciliation evidence.
- [`docs/demo/kno-175-missing-pr-success/README.md`](docs/demo/kno-175-missing-pr-success/README.md): success-path proof. This shows Harness creating and attaching the missing PR, then completing canonical reevaluation to `completed` without operator intervention.

These proofs are specific to `missing_pr_after_execution`. They do not claim that every reconciliation class is already automated or proven.

## Planned Capabilities

The repository also carries planning-only scaffolds for two future capabilities:

- the Harness Evolution Engine (HEE), an advisory subsystem for diagnosing recurring failures and proposing reviewed improvements
- an OpenClaw executor adapter, a future execution boundary that would keep completion truth, verification, and lifecycle enforcement inside Harness

See:

- [`docs/architecture/harness-evolution-engine.md`](docs/architecture/harness-evolution-engine.md)
- [`docs/architecture/openclaw-executor-adapter.md`](docs/architecture/openclaw-executor-adapter.md)
- [`docs/architecture/completion-interception-and-artifact-validation-boundary.md`](docs/architecture/completion-interception-and-artifact-validation-boundary.md)

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
- Completion-claim interception helper (delegates into canonical reevaluation semantics):
  - `POST /tasks/<task_id>/completion-claims`
- Integration helper surface:
  - `POST /ingress/linear`
  - `POST /ingress/manual`
  - `POST /ingress/openclaw`

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
- [`docs/setup/openclaw-local.md`](docs/setup/openclaw-local.md)
- [`docs/setup/render-supabase.md`](docs/setup/render-supabase.md)

## Local Development

Backend setup:

```bash
pip install -r requirements.txt
```

Harness and Codex Cloud assume system Python is available as `python`. Do not assume or require a `.venv`.

Run the backend with the file store:

```bash
python -m modules.api --store-root .harness-store
```

Run the backend with Postgres:

```bash
export HARNESS_STORE_BACKEND=postgres
export DATABASE_URL=postgresql://...
python -m modules.api
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

## Test Execution

Install backend and frontend dependencies first:

```bash
pip install -r requirements.txt
pnpm install --frozen-lockfile
```

Run only the dedicated end-to-end runtime scenario suite:

```bash
python -m unittest discover -s tests/e2e -p 'test_*.py'
```

Run the full Python test suite:

```bash
python -m unittest discover -s tests
```

Run frontend validation:

```bash
pnpm lint
pnpm build
```

## Unattended Dry-Run Runner

Use [`scripts/run_unattended_dryruns.py`](scripts/run_unattended_dryruns.py) to repeatedly execute the three canonical runtime scenarios against the hosted backend:

- `happy_path`
- `mismatch`
- `review_required`

The runner reuses the same scenario builders used by the runtime E2E suite instead of maintaining a second set of hand-built payloads.

Expected environment:

```bash
pip install -r requirements.txt
```

Optional configuration:

```bash
export HARNESS_DRYRUN_BASE_URL=https://harness-qeav.onrender.com
export HARNESS_DRYRUN_OUTPUT_DIR=runs
export HARNESS_DRYRUN_INTERVAL_SECONDS=300
export HARNESS_DRYRUN_ITERATIONS=0
export HARNESS_DRYRUN_MAX_RETRIES=2
export HARNESS_DRYRUN_DIAGNOSTICS_ENABLED=true
export HARNESS_DRYRUN_MAX_E2E_SUITE_RUNS=1
```

Run once:

```bash
python scripts/run_unattended_dryruns.py --iterations 1
```

Run unattended in tmux:

```bash
tmux new -s harness-dryruns 'python scripts/run_unattended_dryruns.py --interval-seconds 300'
```

Stop or restart:

- stop with `Ctrl-C` in the tmux pane
- restart by rerunning the same command

Inspect logs and raw responses:

```bash
tail -f runs/log.jsonl
find runs/reports -type f | sort
find runs/raw -type f | sort
```

Self-heal behavior:

- each scenario compares its actual outcome to the canonical expected outcome
- transient transport and backend availability failures are retried up to the bounded retry limit
- runtime regressions can trigger the local E2E suite once per runner session
- unexpected failures write structured reports under `runs/reports/`

Disable retry and diagnostics:

```bash
python scripts/run_unattended_dryruns.py --max-retries 0 --disable-diagnostics --max-e2e-suite-runs 0
```

## Demo And Canonical Scenarios

### Local deterministic scenario pack

The canonical demo runner in [`modules/demo_runner.py`](modules/demo_runner.py) defines these scenarios:

- `successful_completion`
- `missing_evidence_then_completed`
- `wrong_target_corrected`
  - starts blocked while target facts are corrected, then completes after reevaluation with aligned facts
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

`review_required_then_completed` now uses the explicit `in_review` lifecycle state. A review-required evaluation does not leave the task in `completed`; manual review is what resolves it back to a terminal or follow-up state.

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
- [`docs/demo/review-needed/`](docs/demo/review-needed)

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
