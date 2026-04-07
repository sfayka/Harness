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
OpenClaw ingress is also intentionally narrow. It can submit task intent, provenance, and planning-ready work into Harness, but it cannot declare `executing` or `completed`, inject executor runtime telemetry, or claim completion on initial handoff. If OpenClaw wants to hand work off as `planned`, it must provide explicit planning-grade objective fields plus a concrete `plan_summary`, and it cannot declare unresolved conditions at the same time. If OpenClaw also supplies parent/dependency/capability structure, that structure must be canonical and non-self-referential before Harness will persist it. If unresolved ambiguity still exists, Harness now converts that upstream signal into canonical clarification and blocks the task instead of letting vague work look ready. Execution and completion truth must still come back through executor/reporting paths that Harness can verify.

The same boundary now applies to manual and Linear ingress. Those adapters may submit task intent, coordination metadata, and clarification blockers, but they cannot claim completion, assert acceptance, inject runtime facts, or attach repository execution artifacts such as PRs, commits, branches, or changed-file proofs on initial handoff.

That same boundary now applies to the canonical `POST /tasks` path as well. A brand-new task may carry intent, planning state, support artifacts, and clarification blockers, but it may not arrive already carrying execution truth. If a caller tries to create a new task with claimed completion, runtime facts, prevalidated completion evidence, execution attempts, advisory completion claims, reconciliation history, assignment truth, or runtime/terminal lifecycle truth, Harness rejects the request as invalid input instead of storing a polluted task snapshot.

That clarification rule also now applies across canonical submission, not just the OpenClaw adapter. If a caller submits unresolved conditions through `POST /tasks`, Harness records canonical clarification, moves the task to `blocked`, and preserves the caller's intended next lifecycle state as `clarification.resume_target_status` instead of pretending the task is already `planned` or `dispatch_ready`.
Harness also keeps new-task submission separate from persisted-task mutation. `POST /evaluate` may still evaluate a stored task, but it cannot mutate stored lifecycle, assignment, artifact, or completion-evidence truth through submission-style overlays. Existing tasks must use `POST /tasks/<task_id>/reevaluate` for persisted updates.
That same fail-closed rule now applies to the persisted-task helpers themselves. `POST /tasks/<task_id>/reevaluate` and `POST /tasks/<task_id>/completion-claims` reject submission-style mutation fields such as `task_envelope`, `task_status`, `assigned_executor`, and `linked_artifacts` instead of silently ignoring them.
Generic reevaluation is also no longer allowed to combine executor runtime telemetry with repository execution artifacts such as PRs, commits, branches, or changed-file proofs. If a caller is reporting executor-side execution evidence, it must use `POST /tasks/<task_id>/completion-claims`, where Harness records the execution attempt and applies executor-side contract validation before completion can proceed. Fact-only reevaluation can still attach externally synchronized repository artifacts without pretending they came from a fresh executor run.

## Governed Reconciliation

Harness distinguishes execution from completion.

Before completion claims reach reconciliation, Harness now validates whether a successful execution attempt is minimally trustworthy for the current run. For code-bearing executor attempts, that normally means current-run repository, branch, and commit context must be present and internally coherent. If repository and branch are present but commit SHA is still missing, Harness can allow reconciliation to resolve the branch head before escalating. Otherwise, invalid attempt shape is retried with a bounded budget and then failed explicitly rather than being treated as progress.

Harness also rejects executor-side contract violations mechanically. Delegated code-bearing completion evidence cannot use reserved shared branches such as `work`, cannot omit branch identity, and cannot rely on malformed or stale PR URLs as proof. A real GitHub pull request URL must be numeric and current-run-valid; compare URLs, PR creation pages, closed historical PRs, and unrelated branch/commit/PR chains do not satisfy completion evidence.

Executor-submitted completion claims also cannot self-certify support-artifact proof, pull-request proof, or commit proof. If a completion claim carries one of those artifact types already marked `verified`, Harness downgrades that artifact back to unverified, removes it from validated evidence, and requires canonical verification or reconciliation to earn trust again. When both PR and commit proof are missing or self-certified, Harness now chains the governed reconciliation handlers in order instead of trusting the caller-supplied proof. `verification_status=verified` on a caller payload is advisory input, not trust.

Harness also does not auto-complete on vague success conditions. If a task's required acceptance criteria are too generic to provide observable completion truth, verification escalates to `in_review` instead of pretending the executor proved the task is done.

Harness also canonicalizes missing-information blockers instead of leaving them as loose evaluator notes. When callers submit `unresolved_conditions` through `POST /tasks`, `POST /tasks/<task_id>/reevaluate`, or `POST /tasks/<task_id>/completion-claims`, Harness records a real `task.clarification` contract, moves the task into `blocked`, and exposes that blocker through the canonical read-model and timeline surfaces.

Harness also validates manual-review decisions mechanically. A serialized `review_decision` only counts if its outcome, target status, and follow-up action still match the original review request and canonical review policy, and if it resolves the currently active review gate for that task. Review gates are now derived from enforcement-recorded review requests only; caller-supplied `review_request` payloads do not create active review state by themselves, and future-dated review timestamps are rejected.

Reevaluation also cannot pre-satisfy completion evidence as a side channel. If a reevaluation is not itself a claimed completion, it may not set `completion_evidence.status=satisfied`, inject validated artifact IDs, or otherwise preload final evidence state before a canonical completion decision.

The same discipline now applies to repo-owned ingress helpers and spikes. Builder utilities that construct `POST /tasks` payloads refuse to emit completion truth, runtime telemetry, or code-execution artifacts on initial submission, and reevaluation builders refuse to preload satisfied evidence unless the same request is actually claiming completion.

Tasks only reach terminal success through artifact-backed reevaluation, not execution claims alone. For recoverable defects such as `missing_pr_after_execution` and `missing_commit_after_execution`, Harness spends automation before operator attention: it moves the task into `reconciling`, runs a bounded reconciliation handler, and then returns to canonical reevaluation.

If recovery succeeds, the task can proceed to canonical reevaluation. If recovery is blocked by a retryable provider problem, Harness moves the task to `blocked`. If recovery proves the execution proof chain is unusable, Harness marks the task `failed`. Only unresolved ambiguity or review-only judgment paths escalate to `in_review`. A historical or pre-attached PR artifact is not enough by itself; the PR has to validate against the current execution context, reruns or branch reuse require explicit task/run linkage rather than branch or task-name matching alone, commit association is discovery evidence rather than present-run proof when the PR head no longer matches the expected commit, a newly created PR is only trusted after Harness reads back the persisted GitHub record and revalidates it, and a missing commit SHA may be recovered from the current branch head before the handler gives up.

Recoverable defects should not require immediate human babysitting, but Harness does not assume all recovery cases are safe or automatic.

Harness also does not auto-dispatch work just because it is merely `planned`. Normal automatic dispatch begins from `dispatch_ready`, after planning and clarification boundaries have actually been satisfied. Even then, explicit blocking dependencies must already satisfy their required milestone before dispatch is allowed to proceed.

Governed reconciliation (current scope):

- Proven failure-path: KNO-174
  → recovery blocked → explicit escalation (`in_review`)

- Proven success-path: KNO-175
  → recovery succeeds → PR attached → reevaluation → `completed`

- Current implemented classes:
  → missing_pr_after_execution
  → missing_commit_after_execution

- Principle:
  → Harness spends automation before operator attention

## Governed Reconciliation Proofs

The repository now includes proof records for the `missing_pr_after_execution` reconciliation class:

- [`docs/demo/kno-174-missing-pr-after-execution/README.md`](docs/demo/kno-174-missing-pr-after-execution/README.md): governed failure-path proof. This shows safe escalation when recovery is blocked by external GitHub limitations and the task lands in `in_review` with structured reconciliation evidence.
- [`docs/demo/kno-175-missing-pr-success/README.md`](docs/demo/kno-175-missing-pr-success/README.md): success-path proof. This shows Harness creating and attaching the missing PR, then completing canonical reevaluation to `completed` without operator intervention.

These proofs are specific to `missing_pr_after_execution`. They do not claim that every reconciliation class is already automated or proven. `missing_commit_after_execution` is implemented as a bounded reconciliation class, but it is not part of this proof set yet.

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
- `POST /tasks` is an intake/planning submission path. It may create only fresh task truth, not pre-executed completion truth.
- Input-shape status overlays on `POST /tasks` and `POST /evaluate` are limited to intake/planning states such as `intake_ready`, `planned`, `dispatch_ready`, `assigned`, and `blocked`. Runtime and terminal states such as `executing`, `reconciling`, `completed`, `failed`, and `canceled` are not accepted through the top-level overlay shortcut.
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
