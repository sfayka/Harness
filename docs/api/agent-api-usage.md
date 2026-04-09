# Agent API Usage

This document is the source-of-truth API usage guide for execution agents and downstream synced bundles.

## Canonical Submission Paths

- `POST /tasks`: submit a new canonical task payload
- `POST /tasks/<task_id>/reevaluate`: submit new facts, artifacts, or review decisions for an existing task
- `POST /ingress/manual`: submit a manually initiated task and let Harness intake assign a canonical `task_id` when one is not provided
- `POST /ingress/linear`: submit a Linear-shaped work item that is normalized into canonical Harness task input
- `POST /ingress/openclaw`: submit an OpenClaw-shaped ingress payload that is normalized into canonical `TaskEnvelope` submission

For existing tasks, treat `POST /tasks/<task_id>/reevaluate` as the authoritative mutation path.

`POST /tasks` is an intake/planning creation path, not a completion-reporting path. A brand-new task may include objective, planning, support artifacts, coordination metadata, and clarification blockers, but it must not arrive with claimed completion, acceptance assertions, runtime facts, validated completion evidence, execution attempts, advisory completion claims, reconciliation history, or runtime/terminal lifecycle state already attached.

Fresh task creation also cannot inject assignment truth. Do not send `request.assigned_executor`, and do not try to create a new task directly in `assigned`. Executor assignment belongs to dispatcher-owned flows after Harness has accepted and persisted the task.

Ingress adapters are intake/planning surfaces, not execution-reporting surfaces. `POST /ingress/manual`, `POST /ingress/linear`, and `POST /ingress/openclaw` must not be used to claim completion, assert acceptance, submit executor runtime facts, or attach repository execution artifacts as proof. Those inputs belong to dispatch, completion-claim, and reevaluation paths where Harness can verify them mechanically.

### Completion Claim Interception Helper

- `POST /tasks/<task_id>/completion-claims` is an executor-facing helper for advisory completion claims.
- This helper persists the claim under `task_envelope.observability.execution_metadata.advisory_completion_claims` and then runs canonical reevaluation.
- A completion claim is treated as `claimed_completion=true` advisory input; it does not directly authorize a lifecycle transition.
- The canonical lifecycle outcome still comes from verification/reconciliation/review enforcement.
- Caller-supplied support artifacts, pull-request artifacts, commit artifacts, branch artifacts, and changed-file artifacts on completion claims are never trusted as already verified. If a payload submits those artifact types with `verification_status=verified`, Harness downgrades them to `unverified` and strips them from validated evidence until canonical verification or reconciliation re-attests them.
- If a single completion claim still needs both PR and commit proof after that downgrade, Harness chains the canonical reconciliation handlers in order rather than trusting the self-certified artifact pair.
- If that chained reconciliation escalates to `in_review`, Harness persists the resulting reconciliation review gate as a real evaluation record with a canonical `review_request`. Clients should use that persisted request when later sending `review_decision`; `in_review` is not an informal status-only signal.
- Support artifacts do not satisfy repository, branch, or commit identity for executor-attempt validation. If an executor reports a review note or handoff artifact with GitHub-looking context fields, Harness treats it as support context only, not as current-run code proof.
- If a reevaluation resolves an active review gate with `authorize_redispatch`, Harness follows through by dispatching the next execution attempt automatically instead of stopping at a passive `dispatch_ready` result.
- When that automatic redispatch runs immediately, the reevaluation response reflects the post-dispatch canonical outcome, not the intermediate `dispatch_ready` transition that briefly authorized the follow-up attempt.
- This endpoint must not be used to mutate stored task truth with submission-style fields such as `request.task_envelope`, `request.task_status`, `request.assigned_executor`, or `request.linked_artifacts`. Those payload shapes are rejected as invalid input.

### Manual Dispatch Bridge

- `POST /tasks/<task_id>/dispatch` manually dispatches an existing canonical task to an executor adapter.
- The request supports:
  - `request.executor` (optional: `codex`, `openclaw`, or `stub-executor`; default `codex`)
  - `request.execution_parameters` (optional object for advisory execution metadata)
  - `request.artifact_references` (optional list of advisory artifact references such as PR URL, commit SHA, and branch metadata)
- Dispatch:
  - records a new execution attempt under `observability.execution_metadata.execution_attempts`
  - records advisory completion claim metadata
  - automatically triggers canonical reevaluation through the existing completion-claim path
- Dispatch remains advisory-only and must not bypass verification, reconciliation, lifecycle enforcement, or review gates.

- Existing-task reevaluation uses the stored task snapshot as the source of truth.
- `POST /evaluate` may still be used as an evaluation surface for an existing task id, but it no longer accepts submission-style mutation overlays for that stored task.
- Automatic callers must not rely on `POST /evaluate` to overwrite an existing task lifecycle state, assignment, artifact set, or completion evidence by supplying top-level overlays or a different nested `request.task_envelope`.

For new-task submission and one-shot evaluation, the canonical contract remains `request.task_envelope`. Harness also accepts ingress-style top-level overlays for convenience on initial requests:

- `request.task_status`
- `request.assigned_executor`
- `request.linked_artifacts`
- `request.completion_evidence`
- `request.unresolved_conditions`

Those overlays are merged into `request.task_envelope` before evaluation for new-task submission and one-shot evaluation only. If the task already exists, `POST /evaluate` rejects those overlay fields and returns a contract error that points the caller to `POST /tasks/<task_id>/reevaluate`.

For `POST /tasks/<task_id>/reevaluate`, only canonical reevaluation fields are allowed for persisted mutation. Use `request.new_artifacts` instead of `request.linked_artifacts`, and do not send `request.task_envelope`, `request.task_status`, or `request.assigned_executor`. Those submission-style fields are rejected so callers cannot pretend a stored task was updated when Harness ignored the payload.

`POST /tasks/<task_id>/reevaluate` is not an executor proof-ingestion shortcut. It may attach support artifacts such as review notes, progress artifacts, or handoff artifacts, and it may carry fact-only repository artifacts from external sync, but it must not combine repository execution artifacts with `runtime_facts`. If a caller needs to report executor-side runtime telemetry plus new PR/commit/branch/changed-file proof for an existing task, use `POST /tasks/<task_id>/completion-claims` so Harness can bind the artifacts to an execution attempt and enforce executor contract validation.

Like completion claims, evaluation overlays and reevaluation do not trust caller-submitted `verification_status=verified` on support artifacts. If a caller attaches review notes, handoff artifacts, or other non-execution artifacts already marked verified, Harness downgrades those artifacts back to `unverified`, strips them from validated evidence, and requires canonical verification to earn that trust again. Claimed provenance such as `github/api` sync or `harness/manual_review|verification` does not change that for support artifacts when it arrives through a public API request. Canonical GitHub-backed code-artifact overlays remain allowed for normalized external synchronization paths.

For `POST /tasks`, top-level completion-shaped overlays are rejected on new task creation. Do not send:

- `request.claimed_completion=true`
- `request.acceptance_criteria_satisfied=true`
- `request.runtime_facts`
- `request.completion_evidence`
- execution artifact overlays such as PR/commit/branch/changed-file proof

Nested `request.task_envelope` content is also checked. A fresh task must not already contain:

- runtime or terminal lifecycle status
- `timestamps.completed_at`
- validated completion evidence
- execution attempts or advisory completion claims
- reconciliation attempts or resolved reconciliation state

If initial `request.task_envelope.artifacts.items` includes support artifacts, they are stored as advisory attachments only. Caller-submitted `verification_status=verified` is stripped on new-task submission and on one-shot new-task `POST /evaluate` requests so a task cannot begin with pre-certified artifact truth.

`request.task_status` is intentionally narrow. It may seed only intake/planning lifecycle states:

- `intake_ready`
- `planned`
- `dispatch_ready`
- `assigned`
- `blocked`

It must not be used to inject runtime or terminal states such as `executing`, `reconciling`, `completed`, `failed`, or `canceled`. Runtime progress and completion truth must instead enter through dispatch, completion claims, reevaluation, evidence, and policy enforcement.

`request.unresolved_conditions` is not an advisory note. When present on submission, reevaluation, or completion-claim requests, Harness attaches or updates `task_envelope.clarification`, moves the task into `blocked`, and exposes that clarification state through the canonical read-model and timeline surfaces. If the caller also supplies an allowed `request.task_status`, that stronger status is treated as the intended clarification resume target rather than the current lifecycle truth.

## Review-Required Lifecycle Rule

- If verification returns `requires_review=true`, Harness moves an active non-terminal task into `in_review`.
- A review-required result must not leave the task in `completed`.
- Automatic review escalation is allowed from active lifecycle states such as `intake_ready`, `planned`, `dispatch_ready`, `assigned`, `executing`, and `blocked`.
- Automatic paths do not reopen `completed`, `failed`, or `canceled` tasks into review.
- Manual review is what resolves `in_review` back to `completed`, `blocked`, `failed`, `planned`, `dispatch_ready`, `assigned`, or `canceled`.
- A submitted `review_decision` is only accepted if it still matches the original review request's `allowed_outcomes` and canonical outcome-to-status mapping, and if it resolves the task's currently active review request. Callers cannot forge a different target status, follow-up action, or stale review-request payload by editing the serialized decision.
- Once review is active, automatic reevaluation, artifact sync, or external reconciliation must keep the task in `in_review` until an explicit manual decision resolves it.
- Reconciliation-driven `in_review` states follow the same rule. If completion-claim reconciliation cannot safely finish automatically, the API persists a concrete `review_request` and exposes it through evaluation history, read-model, timeline, and task-list surfaces.
- On those inspection surfaces, `review_required` remains a separate triage class. A task in `in_review` may report `failure_type=review_required`, but its projected state is `review_required`, not terminal `failed`.
- If a reconciliation-driven review gate is later resolved by explicit manual review, the projected `reconciliation_summary` resolves too. Inspection surfaces should not continue to present that older reconciliation gate as still active after the task has completed.
- The same rule applies to `verification_summary`: once explicit manual review resolves the gate, inspection surfaces should project a resolved verification state rather than leaving the older `review_required` or `verification_deferred` result in place as if it were still active.
- For non-accept manual-review outcomes, that resolved `verification_summary` must also stop projecting stale completion proof. Clients should not see `claimed_completion=true` or `evidence_is_sufficient=true` after manual review resolved the gate to a non-completed state with deferred evidence.
- If a manual-review follow-up is attempted but lifecycle policy rejects the requested transition, the review gate stays active. Inspection surfaces should keep `review_summary.status="requested"` and expose the attempt as a rejected review decision instead of projecting the gate as resolved.
- That rejected attempt does not consume the active request. A later valid `review_decision` must still be able to resolve the same persisted gate.
- If manual review resolves the gate without accepting completion, Harness clears the task's satisfied completion evidence back to deferred. Follow-up outcomes such as `authorize_replan`, `authorize_retry`, `keep_blocked`, `mark_failed`, `require_clarification`, and `cancel_task` must not leave stale validated artifact proof behind.

## Reconciliation Classification Rule

Harness keeps these classes separate:

- `mismatch`: external facts directly contradict the task state or execution target and can be classified automatically
- `pending`: external facts are still incomplete, delayed, or otherwise not ready for a blocking contradiction decision
- `review_required`: external facts are unresolved or ambiguous enough that Harness cannot safely decide automatically

Current canonical example:

- `linear_record_not_found` is treated as `review_required`, not as an automatic mismatch, because the system cannot safely infer whether the task is missing, mislinked, or temporarily unresolved

## Linear Facts Workflow Rule

The `external_facts.linear_facts.workflow` field is conditional on `record_found`.

- If `record_found=false`, `workflow` must be `null` or omitted.
- If `record_found=true`, `workflow` must be an object containing:
  - `workflow_id`
  - `workflow_name`

Invalid combinations should return an `invalid_input` API error rather than an internal constructor or parser exception.

## Canonical Examples

Generated source-of-truth payloads live under `examples/api/`:

- `examples/api/create-task.json`
- `examples/api/evaluate-happy-path.json`
- `examples/api/evaluate-mismatch.json`
- `examples/api/evaluate-review-required.json`

Regenerate them with:

```bash
python scripts/render_api_examples.py
```

If you also need the synced execution bundle under `exports/agent-contract/`, regenerate that with:

```bash
python scripts/export_agent_contract.py
```
