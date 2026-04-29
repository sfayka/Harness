# Symphony Execution Substrate

## Purpose

Define how Harness should respond to OpenAI's Symphony project without weakening Harness's source-of-truth boundary.

Symphony validates the need for a daemonized execution substrate that keeps Codex working on structured tasks. It does not replace Harness. Harness remains the control plane, verification layer, and lifecycle authority. A Symphony-like service may run work, retry work, preserve per-issue workspaces, and report execution facts. It must not decide whether work is complete.

References:

- [OpenAI Symphony repository](https://github.com/openai/symphony)
- [Symphony service specification](https://github.com/openai/symphony/blob/main/SPEC.md)
- [Symphony Elixir reference implementation](https://github.com/openai/symphony/blob/main/elixir/README.md)
- [OpenAI Symphony announcement](https://openai.com/index/open-source-codex-orchestration-symphony/)
- [OpenAI Harness engineering post](https://openai.com/index/harness-engineering/)

## Decision

Harness should wrap a Symphony-like runner as an execution substrate.

Harness should not build a duplicate low-level daemon whose only purpose is to poll Linear, create workspaces, launch Codex, and keep attempts moving. Symphony's public spec is now the right shape for that lower layer.

Local setup now reflects that decision. The `repair-dispatch` workflow requires an `execution_substrate` setup item, with Symphony as the preferred runner. The old `ingress_executor` setup item remains as a compatibility bridge for older OpenClaw/Hermes/Codex repair paths, but it is no longer the primary execution-scheduling requirement.

Harness should also not collapse into Symphony. Symphony is a runner and tracker reader. Harness is the source of verified lifecycle truth.

The intended stack is:

```text
Ambiguous product or software idea
        |
Clarification and PRD/spec generation
        |
Harness planning and decomposition
        |
Linear project, issue, and dependency graph
        |
Harness dispatch policy and execution budgets
        |
Symphony-like execution substrate
        |
Codex / Codex Cloud / future workers
        |
GitHub commits, pull requests, CI, reviews, artifacts
        |
Harness verification, reconciliation, manual review, completion authority
```

This preserves the current source-of-truth model:

- Linear is the source of truth for intended and structured work.
- GitHub is the source of truth for executed code artifacts.
- Executors are replaceable workers.
- A Symphony-like runner is an execution scheduler.
- Harness is the source of truth for verified lifecycle state.

## What Symphony Validates

Symphony validates the parts of the Harness thesis that were most likely to become operational bottlenecks:

- Work should be represented in a structured work surface before agents execute it.
- Long-running agent execution should be daemonized instead of driven by manual terminal supervision.
- Each unit of work should get an isolated workspace.
- Execution policy should be repo-owned and versioned, similar to `WORKFLOW.md`.
- Multiple agent runs require bounded concurrency, retry state, and operator-visible runtime status.
- Execution summaries are not enough; systems need artifacts, logs, and handoff states.

The important strategic implication is that Harness should spend less effort on bespoke executor scheduling and more effort on the things Symphony intentionally does not own: clarification, decomposition, verification, reconciliation, lifecycle policy, manual review, and project-level completion.

## What Harness Should Borrow

Harness should adopt these Symphony concepts either directly or through compatible abstractions:

- Repo-owned execution workflow contract, initially `WORKFLOW.md` or a Harness-specific profile that can generate one.
- Per-issue or per-task deterministic workspace roots.
- Bounded concurrency by repository, project, executor class, and risk level.
- Poll/reconcile loop for eligible Linear issues.
- Stop active runs when Linear state, dependency state, or Harness policy makes the issue ineligible.
- Retry queue with attempt count, retry reason, due time, and exponential backoff.
- Stall and timeout detection based on heartbeats and progress facts.
- Runtime snapshot with running sessions, retrying sessions, rate-limit state, token usage, and seconds running.
- App Server style integration for Codex where available, instead of terminal scraping.
- Dynamic tool exposure for privileged integrations so worker sessions do not receive raw broad-scope tokens.
- Workflow prompt construction that receives issue context, attempt context, and prior handoff context.

These are execution-substrate concerns. They should feed Harness with advisory events and artifact references, not canonical lifecycle decisions.

## What Harness Must Not Copy

Harness must not copy the parts of a high-trust Symphony deployment that assume the runner and agents can mutate truth safely.

Do not copy:

- Agent-authored Linear state as completion truth.
- Agent-authored acceptance criteria changes after PRD/spec approval without Harness or human review.
- Automatic move to `Done` as a runner success state.
- Auto-merge as a default behavior.
- Unbounded retry loops.
- In-memory runner state as durable Harness truth.
- Broad raw Linear or GitHub mutation tools inside worker sessions without Harness-owned audit and policy boundaries.
- Runner success summaries as completion evidence.
- Silent recovery from external mismatches.

The safe rule is simple: the runner may reach a handoff state; Harness decides whether the handoff is acceptable.

## Boundary Model

### Symphony-Like Runner Owns

- Polling for eligible work when delegated by Harness policy.
- Creating or reusing isolated workspaces.
- Launching Codex or another selected executor.
- Passing workflow prompts and attempt context.
- Observing heartbeats, stalls, timeouts, and worker exits.
- Scheduling execution-level retries within Harness-provided budgets.
- Emitting normalized execution events and artifact references.
- Cleaning up or preserving workspaces according to configured policy.

### Harness Owns

- Clarification interviews and missing-information handling.
- PRD or PRD-like spec approval state.
- Decomposition into epics, issues, dependencies, checkpoints, and validation tasks.
- Dispatch policy and execution budgets.
- Canonical `TaskEnvelope` meaning.
- Lifecycle transitions.
- Verification policy.
- GitHub artifact readback and validation.
- Linear reconciliation.
- Sticky manual review gates.
- Project-level completion rollups.
- Operator-facing truth.

### Linear Owns

- Visible work coordination.
- Projects, issues, dependencies, labels, assignees, priorities, and workflow status.
- Human and agent collaboration around intended work.

Linear does not decide whether artifact-backed completion should be trusted.

### GitHub Owns

- Branches, commits, pull requests, changed files, CI status, reviews, and merge state.

GitHub stores artifact facts. It does not decide Harness lifecycle state.

## Runner Event Contract

The runner integration should emit advisory events into Harness. These events should be append-only and attempt-scoped.

The first in-code contract lives in [`modules/contracts/execution_substrate.py`](../../modules/contracts/execution_substrate.py). It intentionally models runner events as advisory input, not as lifecycle authority.

Harness accepts these events through `POST /tasks/<task_id>/execution-substrate-events`. That endpoint appends validated runner events to `observability.execution_metadata.execution_substrate_events` and projects them into the read-model and timeline. It does not run verification, mutate Linear or GitHub, or authorize a lifecycle transition.

The deterministic local dry run lives in [`modules/execution_substrate_dryrun.py`](../../modules/execution_substrate_dryrun.py). It simulates a Symphony-style event stream against a disposable local task and proves that runner handoff remains advisory until Harness verification runs. It also includes an intent-consumer dry run that creates a local retryable task, polls the execution-substrate intent queue, and records advisory runner events without starting Symphony or touching live work.

Run the two local substrate dry runs with:

```bash
python3 -m modules.execution_substrate_dryrun event-stream
python3 -m modules.execution_substrate_dryrun intent-consumer
```

Both commands write a JSON summary to stdout. They use disposable local stores, do not start Symphony, do not read live Linear or GitHub state, and do not authorize task completion. They exist to make the execution-substrate boundary testable before Harness connects a real Symphony runner.

The supervision queue now also exposes `execution_substrate_intent` for attention items that should be continued by a Symphony-compatible runner. This is the replacement for Harness pretending to be the runner in the normal path. A supervisor can submit that intent to Symphony, and Symphony reports back through `POST /tasks/<task_id>/execution-substrate-events`. Harness also exposes `GET /execution-substrate/intents` as a runner-facing filtered projection of those intents. The old direct `/tasks/<task_id>/dispatch` behavior remains only as a compatibility and deterministic-test path.

Initial event family:

- `dispatch_requested`
- `dispatch_started`
- `workspace_prepared`
- `runner_session_started`
- `run_heartbeat`
- `progress_reported`
- `artifact_reported`
- `handoff_reported`
- `run_stalled`
- `run_timed_out`
- `run_failed`
- `retry_scheduled`
- `retry_started`
- `run_cancelled`
- `run_completed_by_executor`

These names are intentionally execution-facing. None of them mean Harness has accepted completion.

Required event fields:

- `event_id`
- `task_id`
- `attempt_id`
- `runner_kind`
- `runner_session_id`
- `executor_kind`
- `workspace_id`
- `timestamp`
- `event_type`
- `payload`
- `provenance`

Required artifact reference fields when the runner reports artifacts:

- `artifact_type`
- `repository`
- `branch`
- `commit_sha`
- `pr_url`
- `source_attempt_id`
- `reported_by`
- `reported_at`
- `verification_status`

Runner-reported artifact references start as unverified unless they come from a separate trusted sync path, such as Harness-controlled GitHub API readback.

## TaskEnvelope Impact

Harness should add a canonical execution-substrate surface to `TaskEnvelope`, or formalize the same shape under existing observability fields before schema expansion.

Proposed `execution` section:

```json
{
  "execution": {
    "substrate": {
      "kind": "symphony",
      "implementation": "symphony-compatible",
      "version": null
    },
    "dispatch_policy_id": "policy.default.code-change",
    "workspace_id": "repo/KNO-123",
    "runner_session_id": "session_...",
    "current_attempt_id": "attempt_...",
    "attempt_count": 1,
    "handoff_state": "human_review",
    "runner_claims": [],
    "budgets": {
      "max_attempts": 3,
      "max_wall_clock_seconds": 7200,
      "max_idle_seconds": 900,
      "max_token_budget": null
    }
  }
}
```

Rules:

- `execution` stores dispatch and runtime facts, not completion truth.
- `runner_claims` are advisory and must not authorize lifecycle transitions.
- Attempt history should remain append-only, either inside execution records or linked audit records.
- `assigned_executor` remains the current active assignment, not an execution ledger.
- GitHub artifact truth still belongs under canonical artifact/evidence surfaces after validation.

Do not add this schema field casually before Phase 1 proves the minimum data needed. The first implementation may project these fields into `observability.execution_metadata` while the docs settle.

## Linear Integration Impact

Harness should treat Symphony's Linear usage as scheduling input, not lifecycle authority.

Recommended Linear model:

- Harness-created or Harness-approved issues are executable.
- Agent-created follow-up issues enter `proposed` or `needs_triage` until accepted.
- Runner may move issues to a handoff state such as `Human Review`.
- Runner may add PR links and progress comments.
- Runner may not mark work as Harness-verified complete.
- Runner may not rewrite accepted acceptance criteria without review.
- Harness writes back verification status separately, either as labels, comments, custom fields, or a dedicated status convention.

Linear dependencies should gate runner dispatch. A runner should not start a dependent issue simply because it appears active if Harness or Linear blockers are unresolved.

## Retry Model Impact

Harness should split retry causes instead of treating all continuation as the same loop.

Retry classes:

- `runner_retry`: process crash, transient transport failure, stalled Codex session, timeout.
- `repair_retry`: missing PR, missing commit, stale branch readback, CI status unavailable.
- `spec_retry`: unclear task, missing acceptance criteria, contradictory scope.
- `verification_retry`: GitHub, Linear, CI, or review facts unavailable.
- `policy_retry`: allowed redispatch after manual review or Harness recovery.

Each class needs separate budgets:

- max attempts
- max wall-clock duration
- max idle duration
- max token or spend budget when available
- max artifact churn
- escalation target after exhaustion

Budget exhaustion must stop automatic continuation. It may move the task to `blocked`, `failed`, or `in_review` depending on class and evidence. It must not silently keep the daemon alive.

## Dashboard Impact

The dashboard should expose execution state without blurring it into verification state.

Add an execution-substrate section or view that shows:

- active runner sessions
- retry queue
- stalled sessions
- attempt counts
- workspace identifiers
- runner handoff state
- current Linear state
- reported artifacts
- GitHub verification state
- Harness lifecycle state
- blocking mismatch reasons
- budget consumption

The UI copy and read-model contract should preserve this distinction:

- `Executor says done` means advisory handoff.
- `Artifacts verified` means GitHub/CI/review facts satisfy the relevant evidence contract.
- `Harness complete` means lifecycle acceptance passed verification and reconciliation.

No dashboard surface should display a runner handoff as final project completion.

## Verification Model Impact

Runner handoff should trigger reevaluation. It should not complete work.

For code-bearing work, Harness must independently fetch and validate:

- repository
- branch
- commit SHA
- pull request URL
- pull request head SHA
- changed files
- CI checks
- review state
- merge state
- required evidence policy

Completion can be accepted only when:

- acceptance criteria are satisfied or explicitly waived through review
- required artifacts are present and coherent
- required checks pass
- manual review gates are resolved
- Linear state and Harness state do not have a blocking mismatch
- dependency and project rollup gates are satisfied

Project-level `done` is stricter than task-level completion. A project may report done only when all required child tasks, validation tasks, dependencies, and review gates are complete.

## Safety Rules

These rules apply before any live Symphony-style runner is enabled against real work.

1. No live work execution in Phase 0.
2. No automatic merge in Phase 1 or Phase 2.
3. No agent-written Linear completion truth.
4. No unbounded retries.
5. No runner state as Harness canonical state.
6. No broad raw mutation tokens inside worker sessions unless mediated, scoped, and audited.
7. No silent mock or fallback data in dashboard execution state.
8. No acceptance criteria rewrites after approval without explicit review.
9. No worker-created issues entering the executable DAG without Harness or human acceptance.
10. No executor summary accepted without independent artifact verification.

## Phase 0: Documentation And Design Only

Goal: align architecture before implementation.

Allowed work:

- Add this document.
- Cross-link existing architecture docs.
- Define the runner event contract.
- Define TaskEnvelope impact as a proposal.
- Define no-live-work safety constraints.
- Identify duplicated scheduler/runner code for later removal or wrapping.

Not allowed:

- Installing Symphony.
- Running Symphony against live work.
- Creating Linear issues.
- Creating GitHub PRs from a runner.
- Adding auto-merge.
- Giving worker sessions broad Linear or GitHub mutation authority.

Exit criteria:

- The architecture boundary is documented.
- The next disposable-repo trial is specified.
- Future implementation agents can tell which code belongs in Harness and which belongs in the runner layer.

## Phase 1: Local Dry Run / Disposable Repo Trial

Goal: prove the runner/Harness boundary without operational risk.

Scope:

- Use a disposable repository.
- Use fake Linear data or a non-production test project.
- Run a Symphony-like loop locally or simulate its event stream.
- Capture runner events into Harness as advisory execution facts.
- Exercise workspace creation, session start, heartbeat, handoff, stall, timeout, and retry events.
- Verify that Harness refuses to convert runner success into completion without GitHub artifact readback.

Required proof:

- A runner handoff triggers Harness reevaluation.
- Missing artifacts block completion.
- Valid GitHub readback can satisfy evidence policy.
- Retry budget exhaustion stops automatic continuation.
- Dashboard separates execution status from verification status.

Still not allowed:

- Live production work.
- Auto-merge.
- Agent-authored completion truth.

## Phase 2: Limited Linear/GitHub Integration

Goal: connect the execution substrate to real systems with tight limits.

Scope:

- One selected repository.
- One selected Linear project or label.
- Harness-approved executable issues only.
- Runner may move issues to a handoff state, not `Done`.
- Runner may attach PR links and progress comments.
- Harness independently reads GitHub artifacts.
- Harness writes verified status back to Linear.
- Manual approval required before merge.

Required controls:

- Per-task attempt budget.
- Per-project concurrency cap.
- Kill switch for the runner.
- Pause switch for project and issue.
- Read-only dashboard visibility.
- Audit log for every external mutation.

Exit criteria:

- Real Linear issue can be executed into a PR handoff.
- Harness blocks completion when proof is missing or contradictory.
- Harness accepts completion only after evidence and reconciliation pass.
- No runner path can mark Harness task `completed` directly.

## Phase 3: Productionized Harness Execution Substrate

Goal: make Symphony-like execution a replaceable substrate under Harness.

Scope:

- Hardened runner adapter.
- Persisted dispatch, attempt, retry, and event state in Harness.
- Project-level DAG orchestration from approved specs into Linear.
- Repair dispatch when verification fails.
- Operator controls for pause, resume, cancel, redispatch, and quarantine.
- Policy profiles for low-risk, normal, and high-risk work.

Possible future auto-merge:

Auto-merge should remain off by default. It may become a policy-gated capability only for explicitly low-risk work after Harness proves:

- required CI checks pass
- review requirements pass or are waived by policy
- PR branch and commit match the current execution attempt
- no blocking Linear/GitHub/Harness mismatch exists
- rollback or repair path is defined
- audit trail records the reason merge was allowed

## Duplicative Harness Areas To Revisit

After Phase 0 is merged, review these areas for code that should wrap a Symphony-like substrate instead of duplicating one:

- low-level execution loop mechanics
- executor retry scheduling
- workspace lifecycle assumptions
- Codex-specific dispatch glue
- stale supervision loops that only keep workers busy
- dashboard runtime status that lacks runner/session semantics

Do not remove verification, reconciliation, completion-claim interception, manual review, TaskEnvelope validation, or GitHub artifact validation. Those are Harness core.

## Recommended Next Implementation PR

After this design PR merges, the next PR should be a dry-run runner-event ingestion slice:

- Add a small `ExecutionSubstrateEvent` contract.
- Add tests proving runner completion events are advisory only.
- Add a local fixture that simulates Symphony events for one disposable task.
- Project those events into the existing read-model without changing lifecycle truth.
- Do not run Symphony against live work.
- Do not mutate Linear or GitHub.

That PR moves Harness toward a Symphony-compatible architecture without creating operational risk.
