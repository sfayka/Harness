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

## Quickstart

If you want the fastest useful local run:

1. create a Python virtual environment and install backend deps
2. install frontend deps with `pnpm`
3. run the one-command demo bootstrap

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pnpm install --frozen-lockfile
python -m modules.demo_bootstrap
```

That command:

- clears demo state
- starts the local API
- starts the dashboard
- seeds deterministic demo tasks
- prints the dashboard URL and direct task links

See [docs/setup/local-development.md](docs/setup/local-development.md) for the full local workflow.

## Python Environment Setup

Harness backend commands assume a local virtual environment.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Backend validation typically uses:

```bash
.venv/bin/python -m unittest discover -s tests
```

## Frontend / Dashboard Setup

Install frontend dependencies:

```bash
pnpm install --frozen-lockfile
```

Create a local frontend env file:

```bash
cp .env.example .env.local
```

Set the backend URL in `.env.local`:

```bash
HARNESS_API_BASE_URL=http://127.0.0.1:8000
```

Run the dashboard:

```bash
pnpm dev
```

The dashboard is currently read-only. It is built on the canonical read-model and timeline APIs, not ad hoc frontend-only state.

## Running The API

Start the local API:

```bash
.venv/bin/python -m modules.api --host 127.0.0.1 --port 8000 --store-root .harness-store
```

The API is intentionally thin. It wraps the existing evaluator and persistence scaffolding rather than introducing a second enforcement path.

## Running The Dashboard

With the API running and `HARNESS_API_BASE_URL` configured:

```bash
pnpm dev
```

The dashboard uses a same-origin Next proxy at `/api/harness/*`, so browser code never needs to know the raw backend URL directly.

## Running The Demo Bootstrap

For the lowest-friction local demo path:

```bash
python -m modules.demo_bootstrap
```

Useful options:

```bash
python -m modules.demo_bootstrap --exit-after-seed
python -m modules.demo_bootstrap --json --exit-after-seed
python -m modules.demo_bootstrap successful_completion review_required_then_completed
```

## Demo Walkthrough

Harness includes a deterministic seeded walkthrough for local product demos, screenshots, and operator narration.

Key docs:

- [docs/demo/operator-walkthrough.md](docs/demo/operator-walkthrough.md)
- [docs/setup/local-development.md](docs/setup/local-development.md)

Key commands:

```bash
python -m modules.demo_walkthrough reset --store-root .demo-store --output-dir demo-output/walkthrough
.venv/bin/python -m modules.api --host 127.0.0.1 --port 8000 --store-root .demo-store
pnpm dev
python -m modules.demo_walkthrough seed \
  --base-url http://127.0.0.1:8000 \
  --dashboard-url http://127.0.0.1:3000 \
  --output-dir demo-output/walkthrough
```

Seeded tasks include:

- `demo-successful-completion`
- `demo-missing-evidence-then-completed`
- `demo-contradictory-facts-blocked`
- `demo-review-required-then-completed`
- `demo-long-running-handoff`

## Environment Variables

Current local/frontend variable surface:

- `HARNESS_API_BASE_URL`
  Required by the Next.js proxy route to reach a live backend.

See:

- [.env.example](.env.example)
- [docs/setup/local-development.md](docs/setup/local-development.md)

## High-Level API Surface

Health and inspection:

- `GET /health`
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
