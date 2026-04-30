# Agent API Usage

This document is the source-of-truth API usage guide for execution agents and downstream synced bundles.

## Canonical Submission Paths

- `POST /tasks`: submit a new canonical task payload
- `POST /tasks/<task_id>/reevaluate`: submit new facts, artifacts, or review decisions for an existing task
- `POST /sync/github`: submit a GitHub-shaped sync payload for an existing task and let Harness translate it into canonical reevaluation input
- `POST /ingress/manual`: submit a manually initiated task and let Harness intake assign a canonical `task_id` when one is not provided
- `POST /ingress/linear`: submit a Linear-shaped work item that is normalized into canonical Harness task input
- `POST /ingress/openclaw`: submit an OpenClaw-shaped ingress payload that is normalized into canonical `TaskEnvelope` submission

For existing tasks, treat `POST /tasks/<task_id>/reevaluate` as the authoritative mutation path.
`POST /sync/github` is a thin convenience wrapper only. It must delegate back into canonical reevaluation semantics; it is not a separate truth path.

## Canonical Inspection Paths

- `GET /tasks`: canonical task inventory and triage surface
- `GET /tasks/<task_id>`: raw persisted task envelope
- `GET /tasks/<task_id>/evaluations`: append-only evaluation history
- `GET /tasks/<task_id>/read-model`: canonical current-truth projection for one task
- `GET /tasks/<task_id>/timeline`: canonical ordered audit timeline for one task
- `GET /supervision/queue`: canonical attention queue for autonomous supervisors such as OpenClaw, Hermes, or a future desktop agent client
- `GET /execution-substrate/intents`: runner-facing projection of Symphony-compatible execution continuation intents
- `GET /execution-substrate/transport-status`: read-only transport posture for the Symphony-compatible execution substrate
- `GET /execution-substrate/handoffs`: read-only preview of rendered Symphony-compatible handoff payloads

`GET /supervision/queue` is projection-only. It does not create work, mutate task state, or authorize follow-up actions. It exists so an ingress-side supervisor can poll Harness for the tasks that currently need intervention without rebuilding policy client-side from raw task payloads.

`GET /execution-substrate/intents` is also projection-only. It filters the supervision queue down to entries that carry `execution_substrate_intent`, so a Symphony-compatible runner can poll only the work that belongs to the execution substrate. The response is advisory and still points completion authority back to Harness verification.

`GET /execution-substrate/transport-status` is the operator-readable transport guardrail. It currently reports `transport_status=disabled`, `dispatch_enabled=false`, `live_dispatch_enabled=false`, `completion_authority=harness_verification`, `runner_completion_is_truth=false`, and `safe_to_execute_live=false`. That endpoint is posture, not permission. A live Symphony transport must add a separate policy-gated execution path instead of changing this status silently.

`GET /execution-substrate/handoffs` renders the handoff payloads for current execution-substrate intents without starting Symphony, mutating GitHub, updating Linear, or trusting runner completion. It exists for inspection and future adapter development.

Queue entries are derived from canonical read-model and timeline truth and currently classify:

- `review_required`
- `clarification_required`
- `invalid_execution_attempt`
- `github_sync_required`
- `retryable_failure`
- `stale_active_task`

OpenClaw, Hermes, Symphony, or another supervisor may use those entries to decide what to inspect next, but the actual task mutation still has to go back through canonical submission, execution-substrate event ingestion, GitHub sync, completion-claim, or reevaluation paths.

The repository now includes a thin example supervisor loop in [`modules/connectors/openclaw_supervisor.py`](../../modules/connectors/openclaw_supervisor.py). That file is the current concrete OpenClaw-shaped example, not an architectural requirement. It does not mutate review, clarification, or proof decisions on its own. It only:

- polls `GET /supervision/queue`
- enriches queue entries with canonical inspection surfaces
- may trigger `POST /sync/github` when the queue shows `github_sync_required` and the latest persisted execution attempt already carries enough repository proof to construct a bounded sync payload
- emits a Symphony-compatible `execution_substrate_intent` for retryable or stale execution work by default
- may still trigger `POST /tasks/<task_id>/dispatch` only when explicitly running the legacy direct-dispatch compatibility path

`POST /tasks` is an intake/planning creation path, not a completion-reporting path. A brand-new task may include objective, planning, support artifacts, coordination metadata, and clarification blockers, but it must not arrive with claimed completion, acceptance assertions, runtime facts, validated completion evidence, execution attempts, advisory completion claims, reconciliation history, or runtime/terminal lifecycle state already attached.

Fresh task creation also cannot inject assignment truth. Do not send `request.assigned_executor`, and do not try to create a new task directly in `assigned`. Executor assignment belongs to dispatcher-owned flows after Harness has accepted and persisted the task.

Ingress adapters are intake/planning surfaces, not execution-reporting surfaces. `POST /ingress/manual`, `POST /ingress/linear`, and `POST /ingress/openclaw` must not be used to claim completion, assert acceptance, submit executor runtime facts, or attach repository execution artifacts as proof. Those inputs belong to dispatch, completion-claim, and reevaluation paths where Harness can verify them mechanically.

## Ingress Client Contract

If you are building or swapping a direct ingress client such as Hermes, OpenClaw, or a future equivalent, do not start from `/ingress/manual` just because it is easy to hit. The `/ingress/*` routes are source-specific translators. They exist for callers that already have manual-, Linear-, or OpenClaw-shaped payloads.

For a new ingress that wants to speak Harness directly, the stable contract is:

- `POST /tasks` for new planning/intake submissions
- `POST /tasks/<task_id>/reevaluate` for later fact, artifact, clarification, or review updates
- `GET /tasks/<task_id>/read-model` and `GET /tasks/<task_id>/timeline` for canonical inspection

On hosted Vercel deployments, the same canonical backend path is exposed under the `/backend` prefix. In other words, a hosted caller should normally target `POST /backend/tasks`, not the frontend route and not a convenience ingress wrapper.

### What An Ingress Client Should Send

For a planning-only new task, send:

- `request.acceptance_criteria_satisfied=false`
- `request.claimed_completion=false`
- `request.external_facts={}`
- `request.task_envelope` with canonical task identity, origin, planning status, timestamps, objective, acceptance criteria, deferred completion evidence, and any ingress-specific metadata under `task_envelope.extensions.<ingress_name>`

Use `task_envelope.origin` for canonical provenance:

- `source_system`: the ingress system name such as `hermes`
- `source_type`: normally `ingress_request`
- `source_id`: the ingress-side message or request identifier
- `ingress_id`: the ingress-side conversation or submission identifier
- `ingress_name`: human-readable ingress name such as `Hermes`
- `requested_by`: operator identity when known

Use `task_envelope.extensions` for ingress-local metadata that should survive ingestion without becoming canonical policy truth.

### What An Ingress Client Must Not Send On Initial Submission

Do not send any of the following on a fresh `POST /tasks` request:

- runtime or terminal lifecycle states such as `executing`, `reconciling`, `completed`, `failed`, or `canceled`
- `request.claimed_completion=true`
- `request.acceptance_criteria_satisfied=true`
- `request.runtime_facts`
- satisfied or validated completion evidence
- execution attempts or advisory completion claims
- PR, commit, branch, or changed-file proof
- assignment truth meant to imply the task is already actively dispatched

If the ingress needs to report completion, runtime telemetry, repository proof, or executor-side artifacts later, that belongs to dispatch, completion-claim, sync, or reevaluation paths after the task already exists.

### Planning-Only Example

This is a canonical planning-only payload for a generic ingress client. It uses Hermes as the example name only. Replace `{{now_iso}}`, `{{run_id}}`, and the client-specific metadata before sending.

```json
{
  "request": {
    "acceptance_criteria_satisfied": false,
    "claimed_completion": false,
    "external_facts": {},
    "task_envelope": {
      "id": "task-{{run_id}}",
      "title": "Hermes ingress validation",
      "description": "Submit a planning-only ingress task through the canonical Harness API boundary.",
      "origin": {
        "source_system": "hermes",
        "source_type": "ingress_request",
        "source_id": "telegram:7762711117:{{run_id}}",
        "ingress_id": "{{run_id}}",
        "ingress_name": "Hermes",
        "requested_by": "Sean Fay via Hermes"
      },
      "status": "planned",
      "timestamps": {
        "created_at": "{{now_iso}}",
        "updated_at": "{{now_iso}}",
        "completed_at": null
      },
      "status_history": [],
      "objective": {
        "summary": "Validate that a generic ingress client can submit work into Harness through the canonical task contract while remaining ingress-only.",
        "deliverable_type": "planning_validation",
        "success_signal": "Harness accepts the task, preserves ingress provenance, and exposes canonical read-model and timeline surfaces without any completion proof."
      },
      "constraints": [
        {
          "type": "mode",
          "description": "Planning-only ingress validation.",
          "required": true
        },
        {
          "type": "executor_boundary",
          "description": "Ingress client only, not executor.",
          "required": true
        }
      ],
      "acceptance_criteria": [
        {
          "id": "ac-1",
          "description": "Task is created through POST /tasks as a planning-only canonical submission.",
          "required": true
        },
        {
          "id": "ac-2",
          "description": "Canonical inspection surfaces expose the stored task, read-model, and timeline.",
          "required": true
        },
        {
          "id": "ac-3",
          "description": "Ingress provenance remains visible in canonical task origin and extensions metadata.",
          "required": true
        }
      ],
      "parent_task_id": null,
      "child_task_ids": [],
      "dependencies": [],
      "assigned_executor": null,
      "required_capabilities": [],
      "priority": "normal",
      "artifacts": {
        "completion_evidence": {
          "notes": null,
          "policy": "deferred",
          "required_artifact_types": [],
          "status": "deferred",
          "validated_artifact_ids": [],
          "validated_at": null,
          "validation_method": "deferred",
          "validator": null
        },
        "items": []
      },
      "observability": {
        "errors": [],
        "execution_metadata": {
          "schema_required_deferred_fields": [
            "parent_task_id",
            "child_task_ids",
            "dependencies",
            "assigned_executor",
            "required_capabilities",
            "priority",
            "artifacts.items",
            "artifacts.completion_evidence",
            "observability"
          ]
        },
        "retries": {
          "attempt_count": 0,
          "last_retry_at": null,
          "max_attempts": 0
        }
      },
      "extensions": {
        "hermes": {
          "agent_id": "hermes",
          "platform": "telegram",
          "channel": "dm:Sean Fay",
          "conversation_id": "{{run_id}}",
          "message_id": "{{run_id}}",
          "user_id": "telegram:7762711117",
          "submitted_at": "{{now_iso}}",
          "purpose": "planning-only ingress validation"
        }
      }
    }
  }
}
```

If that task is accepted, the ingress client should treat these as the canonical follow-up inspection surfaces:

- `GET /tasks/task-{{run_id}}/read-model`
- `GET /tasks/task-{{run_id}}/timeline`

### Completion Claim Interception Helper

- `POST /tasks/<task_id>/completion-claims` is an executor-facing helper for advisory completion claims.
- This helper persists the claim under `task_envelope.observability.execution_metadata.advisory_completion_claims` and then runs canonical reevaluation.
- A completion claim is treated as `claimed_completion=true` advisory input; it does not directly authorize a lifecycle transition.
- The canonical lifecycle outcome still comes from verification/reconciliation/review enforcement.
- Caller-supplied support artifacts, pull-request artifacts, commit artifacts, branch artifacts, and changed-file artifacts on completion claims are never trusted as already verified. If a payload submits those artifact types with `verification_status=verified`, Harness downgrades them to `unverified` and strips them from validated evidence until canonical verification or reconciliation re-attests them.
- If a single completion claim still needs both PR and commit proof after that downgrade, Harness chains the canonical reconciliation handlers in order rather than trusting the self-certified artifact pair.
- If that chained reconciliation escalates to `in_review`, Harness persists the resulting reconciliation review gate as a real evaluation record with a canonical `review_request`. Clients should use that persisted request when later sending `review_decision`; `in_review` is not an informal status-only signal.
- Support artifacts do not satisfy repository, branch, or commit identity for executor-attempt validation. If an executor reports a review note or handoff artifact with GitHub-looking context fields, Harness treats it as support context only, not as current-run code proof.
- If a reevaluation resolves an active review gate with `authorize_redispatch`, Harness may follow through through the legacy direct-dispatch compatibility bridge instead of stopping at a passive `dispatch_ready` result.
- When that compatibility dispatch runs immediately, the reevaluation response reflects the post-dispatch canonical outcome, not the intermediate `dispatch_ready` transition that briefly authorized the follow-up attempt.
- New clients should inspect `execution_continuation`. The older `automatic_dispatch` response field remains as a compatibility alias while Harness pivots dispatch continuation toward Symphony-compatible execution-substrate events.
- This endpoint must not be used to mutate stored task truth with submission-style fields such as `request.task_envelope`, `request.task_status`, `request.assigned_executor`, or `request.linked_artifacts`. Those payload shapes are rejected as invalid input.

### Manual Dispatch Bridge

- `POST /tasks/<task_id>/dispatch` is the legacy direct-dispatch bridge for manually dispatching an existing canonical task to an executor adapter.
- New runner integrations should prefer the supervision queue's `execution_substrate_intent` plus `POST /tasks/<task_id>/execution-substrate-events`.
- The request supports:
  - `request.executor` (optional: `codex`, `openclaw`, or `stub-executor`; default `codex`)
  - `request.execution_parameters` (optional object for advisory execution metadata)
  - `request.artifact_references` (optional list of advisory artifact references such as PR URL, commit SHA, and branch metadata)
- Successful responses include `dispatch.compatibility_mode=true`, `dispatch.dispatch_surface=legacy_direct_dispatch`, and `dispatch.preferred_execution_surface=execution_substrate`.
- Dispatch:
  - records a new execution attempt under `observability.execution_metadata.execution_attempts`
  - records advisory completion claim metadata
  - automatically triggers canonical reevaluation through the existing completion-claim path
- Dispatch remains advisory-only and must not bypass verification, reconciliation, lifecycle enforcement, or review gates.
- The repository still includes a Codex Cloud adapter boundary that can be injected into this compatibility bridge for `request.executor="codex"`. That adapter requires repo/bootstrap preflight proof before it will emit a successful advisory completion path.

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

`POST /sync/github` exists for the specific case where an external sync process has observed GitHub state and wants Harness to ingest that reality without hand-assembling a canonical reevaluation body. It accepts a GitHub-shaped payload plus `task_id`, derives normalized `external_facts.github_facts`, and may attach trusted `github/api` branch, commit, pull-request, and changed-file artifacts through the canonical reevaluation path. It must not carry:

- `runtime_facts`
- `claimed_completion=true`
- `acceptance_criteria_satisfied=true`
- `completion_evidence`
- `review_request` or `review_decision`
- caller-supplied canonical `new_artifacts` or `external_facts`

That wrapper is for artifact synchronization only. Completion claims, acceptance assertions, and executor telemetry still belong to `POST /tasks/<task_id>/completion-claims`.

If Harness already has an unresolved advisory completion claim and successful execution attempt recorded for that task, the sync bridge may resume that persisted completion evaluation context and advance `completion_evidence.validated_artifact_ids` from the newly trusted synced artifacts. That resumption is Harness-derived state, not caller authority.

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
- A submitted `review_decision` is only accepted if it still matches the original review request's `allowed_outcomes` and canonical outcome-to-status mapping, if it resolves the task's currently active review request, and if its `record.reviewed_at` is not earlier than the persisted `request.requested_at`. Callers cannot forge a different target status, follow-up action, stale review-request payload, or backdated manual-review chronology by editing the serialized decision.
- Once review is active, automatic reevaluation, artifact sync, or external reconciliation must keep the task in `in_review` until an explicit manual decision resolves it.
- Reconciliation-driven `in_review` states follow the same rule. If completion-claim reconciliation cannot safely finish automatically, the API persists a concrete `review_request` and exposes it through evaluation history, read-model, timeline, and task-list surfaces.
- On those inspection surfaces, `review_required` remains a separate triage class. A task in `in_review` may report `failure_type=review_required`, but its projected state is `review_required`, not terminal `failed`.
- If a reconciliation-driven review gate is later resolved by explicit manual review, the projected `reconciliation_summary` resolves too. Inspection surfaces should not continue to present that older reconciliation gate as still active after the task has completed.
- The same rule applies to `verification_summary`: once explicit manual review resolves the gate, inspection surfaces should project a resolved verification state rather than leaving the older `review_required` or `verification_deferred` result in place as if it were still active.
- For non-accept manual-review outcomes, that resolved `verification_summary` must also stop projecting stale completion proof. Clients should not see `claimed_completion=true` or `evidence_is_sufficient=true` after manual review resolved the gate to a non-completed state with deferred evidence.
- That remains true even when the authorized follow-up later fails. If manual review resolves a gate with `authorize_redispatch`, `authorize_retry`, or `authorize_replan`, and the subsequent governed action lands in `blocked`, `failed`, or another non-review state, `verification_summary` should stay resolved rather than falling back to `verification_deferred` or `review_required`.
- If a manual-review follow-up is attempted but lifecycle policy rejects the requested transition, the review gate stays active. Inspection surfaces should keep `review_summary.status="requested"` and expose the attempt as a rejected review decision instead of projecting the gate as resolved.
- In that rejected-follow-up case, inspection surfaces must also clear the stale completion-safety projection from the rejected path. `verification_summary` should not keep advertising `claimed_completion=true`, `evidence_is_sufficient=true`, or `automatic_completion_safe=true` while the task is still `in_review`.
- If a newer `review_request` is recorded after an older manual decision was already resolved, the newer active request becomes authoritative. Inspection surfaces must project the reopened gate as `review_required` rather than falling back to stale `verification_deferred` or other pre-review projection from the earlier resolved branch.
- While that active review gate remains unresolved, inspection surfaces should also suppress `assigned_executor`. The dispatcher’s active assignment is no longer the authoritative next step while the task is `in_review`, even if persisted task state still retains prior assignment context for later policy-driven follow-up.
- That rejected attempt does not consume the active request. A later valid `review_decision` must still be able to resolve the same persisted gate.
- If manual review resolves the gate without accepting completion, Harness clears the task's satisfied completion evidence back to deferred. Follow-up outcomes such as `authorize_replan`, `authorize_retry`, `keep_blocked`, `mark_failed`, `require_clarification`, and `cancel_task` must not leave stale validated artifact proof behind.
- `require_clarification` is not just a blocked lifecycle move. When manual review chooses that outcome, Harness also writes a canonical `task_envelope.clarification` block so the missing-information requirement is visible and resumable through the inspection surfaces.
- More generally, `transition_rejected` on an existing task is an auditable rejected action, not a new lifecycle truth. Rejected reevaluation or completion-claim follow-up may append evaluation history and timeline entries, and may still persist new synchronized facts, but it must not replace the current lifecycle/verification/reconciliation/failure projection for an already-settled task.

## Reconciliation Classification Rule

Harness keeps these classes separate:

- `mismatch`: external facts directly contradict the task state or execution target and can be classified automatically
- `pending`: external facts are still incomplete, delayed, or otherwise not ready for a blocking contradiction decision
- `review_required`: external facts are unresolved or ambiguous enough that Harness cannot safely decide automatically

Current canonical example:

- `linear_record_not_found` is treated as `review_required`, not as an automatic mismatch, because the system cannot safely infer whether the task is missing, mislinked, or temporarily unresolved

## Inspection Surface Attempt Semantics

On `GET /tasks` and `GET /tasks/<task_id>/read-model`, `execution_summary.attempt_count` is the number of canonical execution attempts currently recorded on the task.

`execution_summary.total_attempts` is broader: it can include retry/evaluation-chain activity even when no new execution-attempt record exists. It must never be lower than `attempt_count`, because inspection surfaces cannot truthfully report fewer total attempts than the canonical execution-attempt history already attached to the task.

`execution_summary.latest_attempt`, `latest_status`, `latest_dispatch_origin`, and `latest_attempt_validation` must follow the newest recorded execution attempt by `recorded_at`. Clients must not treat storage append order as authoritative when execution-attempt arrays are out of sequence.

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
