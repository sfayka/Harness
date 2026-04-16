# Harness

Harness is a control plane and reliability layer for AI-assisted work.

It does not trust agent-reported completion on its own. It accepts or blocks lifecycle transitions only after evaluating canonical task state, evidence, reconciliation facts, and explicit review decisions.

## Reset Slice

The repo now also carries a narrower reset-oriented path alongside the broader TaskEnvelope control plane.

That reset slice is the current fastest path to something operationally useful:

- OpenClaw owns intake, PRD generation, decomposition, Linear issue creation, and Codex dispatch.
- Harness owns verification contracts, GitHub proof validation, retry budgeting, and Linear truth updates.
- Linear is the operator UI for V1.
- GitHub is the proof source for code-bearing completion.

The reset routes live under:

- `POST /reset/contracts`
- `GET /reset/contracts`
- `GET /reset/contracts/<contract_id>`
- `POST /reset/contracts/<contract_id>/claims`
- `POST /reset/tick`

These routes intentionally coexist with the older TaskEnvelope routes so the narrower verifier path can ship without first deleting the broader control-plane code.

In hosted Vercel runtimes, the reset slice is not allowed to take the whole backend down if its file-backed store cannot be created. Canonical task APIs must still boot. The hosted fallback now uses writable temp storage for the reset slice, and if even that cannot be created, `/reset/*` fails explicitly instead of crashing `/backend/health` and `/backend/tasks` during import.

## What Harness Is

- A Python control-plane backend that evaluates canonical `TaskEnvelope` submissions.
- A read-only Next.js dashboard over canonical inspection APIs.
- A persistence layer for task snapshots and append-only evaluation history.
- A thin integration boundary around Linear/manual/OpenClaw ingress and GitHub/Linear fact inputs.
- An operational reconciliation path that can enter `reconciling`, repair missing PR artifacts, and then delegate back into canonical reevaluation.

Harness is not a PM tool, an agent runtime, or a chatbot UI.
OpenClaw ingress is also intentionally narrow. It can submit task intent, provenance, and planning-ready work into Harness, but it cannot declare `executing` or `completed`, inject executor runtime telemetry, or claim completion on initial handoff. If OpenClaw wants to hand work off as `planned`, it must provide explicit planning-grade objective fields plus a concrete `plan_summary`, and it cannot declare unresolved conditions at the same time. If OpenClaw also supplies parent/dependency/capability structure, that structure must be canonical and non-self-referential before Harness will persist it. If unresolved ambiguity still exists, Harness now converts that upstream signal into canonical clarification and blocks the task instead of letting vague work look ready. Execution and completion truth must still come back through executor/reporting paths that Harness can verify.

On the inspection side, Harness now also exposes a canonical supervision queue at `GET /supervision/queue`. That queue is a read-only projection for OpenClaw-style supervisors: it surfaces tasks that currently need attention because they are in review, blocked on clarification, retryable, carrying invalid execution proof, waiting on canonical GitHub sync, or stale. It does not authorize actions on its own and it does not replace canonical reevaluation, dispatch, completion-claim, or GitHub sync paths.

On the execution side, Harness now also contains a real Codex Cloud adapter boundary in addition to the stub dispatch path. That adapter projects canonical dispatch input into a Codex Cloud request shape and enforces the repo/bootstrap preflight contract before it will emit a successful advisory completion signal. Live runtime transport is still a separate integration step, but the proof gate is now encoded at the adapter boundary instead of left to convention.

The same boundary now applies to manual and Linear ingress. Those adapters may submit task intent, coordination metadata, and clarification blockers, but they cannot claim completion, assert acceptance, inject runtime facts, or attach repository execution artifacts such as PRs, commits, branches, or changed-file proofs on initial handoff.

If you are introducing a new ingress such as Hermes, target the canonical `POST /tasks` contract first. The `/ingress/manual`, `/ingress/linear`, and `/ingress/openclaw` routes are translator helpers for those specific payload families, not the universal ingress contract. The source-of-truth ingress shape, prohibited initial-submission fields, and a copyable planning-only example now live in [`docs/api/agent-api-usage.md`](docs/api/agent-api-usage.md) under `Ingress Client Contract`.

That same boundary now applies to the canonical `POST /tasks` and one-shot new-task `POST /evaluate` paths as well. A brand-new task may carry intent, planning state, support artifacts, and clarification blockers, but it may not arrive already carrying execution truth. If a caller tries to create a new task with claimed completion, runtime facts, prevalidated completion evidence, execution attempts, advisory completion claims, reconciliation history, assignment truth, or runtime/terminal lifecycle truth, Harness rejects the request as invalid input instead of storing a polluted task snapshot. Even when initial support artifacts are allowed, Harness strips any caller-submitted `verification_status=verified` before persisting the task so new work cannot begin with pre-certified artifact truth.

That clarification rule also now applies across canonical submission, not just the OpenClaw adapter. If a caller submits unresolved conditions through `POST /tasks`, Harness records canonical clarification, moves the task to `blocked`, and preserves the caller's intended next lifecycle state as `clarification.resume_target_status` instead of pretending the task is already `planned` or `dispatch_ready`. When later reevaluation clears those required inputs, Harness now resumes the task back to that recorded lifecycle target. If the target is `dispatch_ready`, it immediately runs the same automatic-dispatch policy used after ingestion so “ready next” turns into a real execution attempt instead of a passive label. If the target is `assigned`, Harness restores the active assignment instead of leaving the task blocked behind a resolved clarification.
Harness also keeps new-task submission separate from persisted-task mutation. `POST /evaluate` may still evaluate a stored task, but it cannot mutate stored lifecycle, assignment, artifact, or completion-evidence truth through submission-style overlays. Existing tasks must use `POST /tasks/<task_id>/reevaluate` for persisted updates.
That same fail-closed rule now applies to the persisted-task helpers themselves. `POST /tasks/<task_id>/reevaluate` and `POST /tasks/<task_id>/completion-claims` reject submission-style mutation fields such as `task_envelope`, `task_status`, `assigned_executor`, and `linked_artifacts` instead of silently ignoring them.
Generic reevaluation is also no longer allowed to combine executor runtime telemetry with repository execution artifacts such as PRs, commits, branches, or changed-file proofs. If a caller is reporting executor-side execution evidence, it must use `POST /tasks/<task_id>/completion-claims`, where Harness records the execution attempt and applies executor-side contract validation before completion can proceed. Fact-only reevaluation can still attach externally synchronized repository artifacts without pretending they came from a fresh executor run.

For GitHub-backed sync specifically, Harness now also exposes `POST /sync/github` as a thin wrapper over canonical reevaluation. That helper accepts a GitHub-shaped payload plus `task_id`, derives normalized `external_facts.github_facts`, and may attach trusted `github/api` branch, commit, pull-request, and changed-file artifacts. The caller still cannot claim completion, assert acceptance, attach completion evidence, or carry executor runtime telemetry. When Harness already has an unresolved advisory completion claim for the same task, the sync bridge may resume that persisted completion context and advance validated artifact evidence from the newly trusted GitHub sync artifacts.

Evaluation and reevaluation also cannot self-certify newly attached support artifacts. If a caller sends review notes, handoff artifacts, or other non-execution artifacts already marked `verification_status=verified`, Harness downgrades the artifact back to `unverified`, strips it from validated evidence, and forces canonical verification to re-attest it before it counts. Caller-claimed provenance such as `github/api` or `harness/manual_review` is still caller input, not trust for support artifacts. Canonical GitHub-backed code-artifact overlays remain a separate path for normalized external sync.

## Governed Reconciliation

Harness distinguishes execution from completion.

Before completion claims reach reconciliation, Harness now validates whether a successful execution attempt is minimally trustworthy for the current run. For code-bearing executor attempts, that normally means current-run repository, branch, and commit context must be present and internally coherent. Only code-execution artifacts and code-execution artifact references are allowed to contribute to that proof; support artifacts like review notes can be stored for audit, but they cannot make a run look executed. If repository and branch are present but commit SHA is still missing, Harness can allow reconciliation to resolve the branch head before escalating. Otherwise, invalid attempt shape is retried with a bounded budget and then failed explicitly rather than being treated as progress.

Harness also rejects executor-side contract violations mechanically. Delegated code-bearing completion evidence cannot use reserved shared branches such as `work`, cannot omit branch identity, and cannot rely on malformed or stale PR URLs as proof. A real GitHub pull request URL must be numeric and current-run-valid; compare URLs, PR creation pages, closed historical PRs, and unrelated branch/commit/PR chains do not satisfy completion evidence.

Executor-submitted completion claims also cannot self-certify support-artifact proof, pull-request proof, commit proof, branch proof, or changed-file proof. If a completion claim carries one of those artifact types already marked `verified`, Harness downgrades that artifact back to unverified, removes it from validated evidence, and requires canonical verification or reconciliation to earn trust again. When both PR and commit proof are missing or self-certified, Harness now chains the governed reconciliation handlers in order instead of trusting the caller-supplied proof. `verification_status=verified` on a caller payload is advisory input, not trust.
Support artifacts such as review notes or handoff markers also do not count as repository, branch, or commit proof for execution-attempt validation, even if a caller decorates them with GitHub-looking context fields.

When Harness strips caller-submitted artifacts out of `validated_artifact_ids`, it also clears any caller-supplied `completion_evidence.status`, `validated_at`, and `validator` fields that no longer have real backing. A task should not carry “satisfied” evidence metadata after its purported proof has been invalidated.

Harness also does not auto-complete on vague success conditions. If a task's required acceptance criteria are too generic to provide observable completion truth, verification escalates to `in_review` instead of pretending the executor proved the task is done.

When reconciliation resolves repository and branch context across multiple sources, Harness also avoids synthesizing a current-run commit identity from a weaker source just because it happens to match the branch name. If execution metadata established the branch but not the commit, Harness now prefers a missing commit over caller-supplied commit backfill unless the execution attempt itself proved that commit.

Harness also canonicalizes missing-information blockers instead of leaving them as loose evaluator notes. When callers submit `unresolved_conditions` through `POST /tasks`, `POST /tasks/<task_id>/reevaluate`, or `POST /tasks/<task_id>/completion-claims`, Harness records a real `task.clarification` contract, moves the task into `blocked`, and exposes that blocker through the canonical read-model and timeline surfaces.

Harness also validates manual-review decisions mechanically. A serialized `review_decision` only counts if its outcome, target status, and follow-up action still match the original review request and canonical review policy, and if it resolves the currently active review gate for that task. Review gates are now derived from enforcement-recorded review requests only; caller-supplied `review_request` payloads do not create active review state by themselves, future-dated review timestamps are rejected, and a `reviewed_at` timestamp cannot predate the persisted `requested_at` for the gate it resolves.

That rule also applies to reconciliation-driven escalation. If `POST /tasks/<task_id>/completion-claims` cannot safely prove the reported GitHub execution state and moves the task into `in_review`, Harness now persists a real reconciliation review request and matching evaluation record instead of treating `in_review` as an unstructured status flag. The resulting gate is visible on the canonical read-model, timeline, history, and task-list surfaces, and later manual review must resolve that exact persisted request. Once that review resolves, the projected `reconciliation_summary` also resolves; it no longer keeps presenting the old gate as still active.

The same projection rule now applies to verification. Once explicit manual review resolves a pending review gate, the canonical read-model and task-list `verification_summary` no longer keep reporting the older `review_required` or `verification_deferred` state as if it were still current.

That resolved verification projection also has to match the current task evidence. If manual review resolves the gate without accepting completion, inspection surfaces no longer keep projecting stale `claimed_completion=true` or `evidence_is_sufficient=true` from the old pre-review verification attempt.

That same rule applies when manual review resolves the gate by authorizing follow-up work. If `authorize_redispatch`, `authorize_retry`, or `authorize_replan` leads to a later non-review outcome, the canonical `verification_summary` must still stay resolved; inspection surfaces should not fall back to `verification_deferred` or `review_required` after the manual gate has already been cleared.

If a manual-review follow-up is attempted but lifecycle policy rejects it, Harness keeps the review gate active and records that attempt honestly. The timeline exposes that as `review_decision_rejected` instead of projecting the gate as resolved.

That rejected attempt also must not strand the task. Later manual review decisions still resolve the original persisted review request; a failed follow-up attempt does not consume the gate.

While that gate remains active, the canonical `verification_summary` must also stop advertising stale completion safety from the rejected path. Inspection surfaces should not keep projecting `claimed_completion=true`, `evidence_is_sufficient=true`, or `automatic_completion_safe=true` after a rejected manual-review follow-up leaves the task in `in_review`.

The same precedence rule applies if a later governed step reopens review after an earlier decision was already resolved. A newer active `review_request` must outrank the older resolved decision on inspection surfaces; `verification_summary` and `reconciliation_summary` should follow the current active gate instead of falling back to stale `verification_deferred` or otherwise pre-review state from the earlier branch.

The same fail-closed rule now applies to other rejected late follow-up. If reevaluation or completion-claim input hits a forbidden transition against already-settled task truth, Harness records the rejected attempt in evaluation history and timeline without letting that rejected action replace the current lifecycle, verification, reconciliation, or failure projection for the task. New external facts may still be persisted when they represent real synchronized state; the rejected transition itself is what does not become canonical task truth.

If manual review resolves the gate without accepting completion, Harness also clears any previously satisfied completion evidence back to deferred. A replan, retry, blocked, failed, canceled, or clarification outcome must not leave stale validated proof behind that can auto-complete the task later without a new governed execution or explicit acceptance.

That same current-truth rule applies to assignment. If manual review moves a task into a non-active state like `planned` or `blocked`, Harness clears `assigned_executor` instead of leaving stale active-assignment state attached after work has been explicitly paused or sent back for replanning.

The operator surfaces follow that same rule for active review. When a task is `in_review` with an unresolved review gate, the canonical read-model and task-list views do not project `assigned_executor` as if work were still actively routed, even if the persisted task still retains prior assignment context for later policy-driven follow-up.

If that manual-review outcome is `require_clarification`, Harness now records a real canonical `task.clarification` contract at the same time. The task does not just become generically `blocked`; operators can see the explicit clarification blocker, its `resume_target_status`, and the required input through the task, read-model, list, and timeline surfaces.

When manual review explicitly authorizes redispatch, Harness now performs that redispatch automatically instead of leaving the task parked in `dispatch_ready` with a resolved review record and no follow-up execution.

Reevaluation also cannot pre-satisfy completion evidence as a side channel. If a reevaluation is not itself a claimed completion, it may not set `completion_evidence.status=satisfied`, inject validated artifact IDs, or otherwise preload final evidence state before a canonical completion decision.

The same discipline now applies to repo-owned ingress helpers and spikes. Builder utilities that construct `POST /tasks` payloads refuse to emit completion truth, runtime telemetry, or code-execution artifacts on initial submission, and reevaluation builders refuse to preload satisfied evidence unless the same request is actually claiming completion.

Tasks only reach terminal success through artifact-backed reevaluation, not execution claims alone. For recoverable defects such as `missing_pr_after_execution` and `missing_commit_after_execution`, Harness spends automation before operator attention: it moves the task into `reconciling`, runs a bounded reconciliation handler, and then returns to canonical reevaluation.

If recovery succeeds, the task can proceed to canonical reevaluation. If recovery is blocked by a retryable provider problem, Harness moves the task to `blocked`. If recovery proves the execution proof chain is unusable, Harness marks the task `failed`. Only unresolved ambiguity or review-only judgment paths escalate to `in_review`. A historical or pre-attached PR artifact is not enough by itself; the PR has to validate against the current execution context, reruns or branch reuse require explicit task/run linkage rather than branch or task-name matching alone, commit association is discovery evidence rather than present-run proof when the PR head no longer matches the expected commit, a newly created PR is only trusted after Harness reads back the persisted GitHub record and revalidates it, and a missing commit SHA may be recovered from the current branch head before the handler gives up.

Recoverable defects should not require immediate human babysitting, but Harness does not assume all recovery cases are safe or automatic.

Harness also does not auto-dispatch work just because it is merely `planned`. Normal automatic dispatch begins from `dispatch_ready`, after planning and clarification boundaries have actually been satisfied. Even then, explicit blocking dependencies must already satisfy their required milestone before dispatch is allowed to proceed. When a reevaluation triggers automatic dispatch, the API response now reports the post-dispatch canonical task outcome rather than the intermediate `dispatch_ready` hop, so operators see the real result of the follow-up attempt immediately.

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
  - `GET /supervision/queue`
- Canonical mutation surfaces:
- `POST /tasks`
- `POST /tasks/<task_id>/reevaluate`
- `POST /sync/github`
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
- The default hosted deployment target is Neon-backed Postgres attached through Vercel. Harness stores canonical task and evaluation payloads as JSONB in `tasks` and `evaluation_records`.

## Hosted Deployment Target

Harness now prefers a single hosted project on Vercel Services.

Default hosted shape:

- `web` service for the Next.js dashboard
- `api` service for the Python backend
- Neon-backed Postgres provided through Vercel
- optional Vercel Blob only for real file-like hosted outputs

The hosted backend health endpoint is expected at:

- `GET /backend/health`

The dashboard derives its backend route automatically from the Vercel deployment URL and the `/backend` route prefix. Hosted deployments should not require a manually configured `HARNESS_API_BASE_URL` when both services live inside the same Vercel project.

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
- `GET /supervision/queue`: canonical autonomous-supervision triage surface.

For triage surfaces, `review_required` stays distinct from terminal failure. If a task is in `in_review`, the projected `failure_summary.state` and `execution_summary.failure_state` remain `review_required` rather than collapsing into `failed`.

Within `execution_summary`, `attempt_count` is the number of recorded canonical execution attempts. `total_attempts` may be higher when retry/evaluation history exists without a new execution-attempt record, but it must never undercount the recorded execution attempts already attached to the task.

That same chronology rule applies to the projected latest-attempt fields. `execution_summary.latest_attempt`, `latest_status`, and related latest-attempt details follow the newest recorded execution attempt by `recorded_at`; they do not trust raw list append order when stored attempt arrays arrive out of sequence.

That chronology rule also applies to current-run binding outside the read model. When reconciliation or replay logic needs the active execution attempt and there is no explicit completion-claim `attempt_id` binding, Harness selects the newest recorded execution attempt by `recorded_at` rather than whichever attempt happened to be appended last.

## Storage And Environment

Required frontend environment variable:

- `HARNESS_API_BASE_URL`
  - Local example: `http://127.0.0.1:8000`
  - Hosted use: local override only; same-project Vercel deployments always derive the backend route automatically and ignore stale hosted overrides

Backend storage environment variables:

- `HARNESS_STORE_BACKEND`
  - Supported values: `file`, `postgres`
  - Default in [`.env.example`](.env.example): `file`
  - Hosted Vercel deployments auto-select `postgres` when managed Postgres connection variables are present
- Postgres connection string
  - Harness resolves this in order from `DATABASE_URL`, `POSTGRES_URL`, `POSTGRES_URL_NON_POOLING`, `POSTGRES_PRISMA_URL`, then `POSTGRES_URL_NO_SSL`
  - `DATABASE_URL` remains the explicit portable override
  - Vercel-managed Neon deployments should normally work from the injected `POSTGRES_URL` without any extra remapping
- `BLOB_READ_WRITE_TOKEN`
  - Auto-injected when a Vercel Blob store is connected to the project
  - Not required for canonical task state today; Postgres remains the source of truth

Reset-slice verifier environment variables:

- `GITHUB_TOKEN`
  - Used by the reset verifier to validate branch, commit SHA, and PR proof against GitHub
- `LINEAR_API_KEY`
  - Used by the reset verifier to move Linear issues and leave canonical Harness comments
- `OPENCLAW_BASE_URL`
  - Optional HTTP fallback used when the reset verifier requests OpenClaw repair through a remote callback endpoint
- `OPENCLAW_REPAIR_ENDPOINT`
  - Optional override for the OpenClaw repair callback path

For native local development, `backend.server` now auto-loads both repo-root `.env.local` and `config/openclaw/.env.local`. When the OpenClaw local config exports `OPENCLAW_CONFIG_PATH` or `OPENCLAW_STATE_DIR`, Harness prefers a local `openclaw agent --local` repair dispatch over the HTTP callback path.

Relevant supporting files:

- [`.env.example`](.env.example)
- [`sql/postgres/001_harness_store.sql`](sql/postgres/001_harness_store.sql)
- [`docs/setup/local-development.md`](docs/setup/local-development.md)
- [`docs/setup/openclaw-local.md`](docs/setup/openclaw-local.md)
- [`docs/setup/vercel-neon.md`](docs/setup/vercel-neon.md)
- [`docs/demo/hosted-dryrun-operator-flow.md`](docs/demo/hosted-dryrun-operator-flow.md)

## Local Development

Backend setup:

```bash
python3 -m pip install -r requirements.txt
```

Codex Cloud assumes system Python is available as `python`. On local machines where only `python3` is available, use `python3` for local commands. Do not assume or require a `.venv`.

Run the backend with the file store:

```bash
python3 -m uvicorn backend.server:app --host 127.0.0.1 --port 8000
```

`backend.server` now auto-loads repo-root `.env.local` and `config/openclaw/.env.local` for native local development. That means the backend can pick up `GITHUB_TOKEN`, `LINEAR_API_KEY`, and the repo-owned OpenClaw config/state paths without manual shell export steps.

Run the backend with Postgres:

```bash
export HARNESS_STORE_BACKEND=postgres
export DATABASE_URL=postgresql://...
python3 -m uvicorn backend.server:app --host 127.0.0.1 --port 8000
```

For a local environment pulled from a Vercel-managed Neon project, `POSTGRES_URL` also works without additional remapping:

```bash
export HARNESS_STORE_BACKEND=postgres
export POSTGRES_URL=postgresql://...
python3 -m uvicorn backend.server:app --host 127.0.0.1 --port 8000
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

### Reset-Slice Smoke Path

Once the backend is running and `.env.local` contains `GITHUB_TOKEN`, `LINEAR_API_KEY`, and `OPENCLAW_BASE_URL`, the narrow verifier path is available through:

- `POST /reset/contracts`
- `POST /reset/contracts/<contract_id>/claims`
- `POST /reset/tick`

Use this path when you want Harness to verify GitHub proof for a Linear issue and push canonical truth back into Linear without depending on the dashboard.

For a deterministic local proof of the new slice without touching real Linear or GitHub state, run:

```bash
python3 -m modules.reset_dryrun success
python3 -m modules.reset_dryrun review
```

These dry runs start a temporary local FastAPI app, exercise the `/reset/*` routes over HTTP, and prove the two core paths:

- invalid proof followed by successful repair and verified completion
- invalid proof that exhausts the retry budget and escalates to `In Review`

## Test Execution

Install backend and frontend dependencies first:

```bash
python3 -m pip install -r requirements.txt
pnpm install --frozen-lockfile
```

Run only the dedicated end-to-end runtime scenario suite:

```bash
python3 -m unittest discover -s tests/e2e -p 'test_*.py'
```

Run the full Python test suite:

```bash
python3 -m unittest discover -s tests
```

Run the controlled autonomous dry run that exercises:

- canonical task creation through `POST /evaluate`
- OpenClaw-style retry supervision through `GET /supervision/queue` and redispatch
- Codex Cloud adapter proof validation
- post-dispatch GitHub-backed sync through `POST /sync/github` that closes the missing changed-file evidence gap

```bash
python -m unittest tests.test_autonomous_dryrun
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
- each scenario also compares the task's presence or absence in `GET /supervision/queue` to the canonical expectation
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
