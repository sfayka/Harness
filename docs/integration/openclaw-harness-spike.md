# OpenClaw -> Harness Integration Spike

This spike validates the intended client boundary between OpenClaw and Harness without introducing runtime coupling.

The reference point for this spike was the public [`openclaw/openclaw`](https://github.com/openclaw/openclaw) repository and its current packaging as a Node/TypeScript assistant, CLI, and gateway system.

That reference matters because it reinforces the intended split:

- OpenClaw acts as the ingress and client surface
- Harness acts as the standalone control-plane service

## What The Spike Proves

The spike uses only the public Harness HTTP API to:

1. submit a new task with OpenClaw-style source metadata
2. inspect the stored task and dashboard-friendly read model
3. submit reevaluation with new artifacts
4. inspect the updated timeline and evaluation history

No direct calls into Harness evaluation, persistence, or enforcement internals are used.

## Client Shape

The spike client lives in [`modules/connectors/openclaw_harness_spike.py`](../../modules/connectors/openclaw_harness_spike.py).

It provides:

- `OpenClawSourceContext`
- `OpenClawTaskIntent`
- `OpenClawHarnessSpikeClient`
- `run_openclaw_spike_flow()`

The client preserves OpenClaw-origin context in two places:

- canonical `task_envelope.origin`
- `task_envelope.extensions.openclaw`

That keeps ingress metadata auditable without making Harness depend on OpenClaw internals.

## Public API Surface Used

The spike uses only:

- `POST /tasks`
- `POST /tasks/<task_id>/reevaluate`
- `GET /supervision/queue`
- `GET /tasks/<task_id>`
- `GET /tasks/<task_id>/read-model`
- `GET /tasks/<task_id>/timeline`
- `GET /tasks/<task_id>/evaluations`

## Representative Flow

The built-in spike flow intentionally exercises a real control-plane change:

1. OpenClaw-style client submits a task that claims completion
2. Harness blocks the task because required evidence is still missing
3. OpenClaw-style client reads the canonical supervision queue and sees the live clarification blocker
4. OpenClaw-style client submits reevaluation with the missing review-note artifact
5. Harness accepts completion
6. Client fetches read model, timeline, evaluation history, and confirms the queue entry cleared

The spike now also includes a review-gate flow:

1. OpenClaw-style client submits a task without initial blockers
2. OpenClaw-style client reevaluates with unresolved external truth that must escalate to manual review
3. Harness moves the task into `in_review`
4. OpenClaw-style client reads the canonical supervision queue and sees a live `review_required` entry

## What Was Learned

The current boundary works cleanly for a thin client.

The main friction point is task creation verbosity:

- `POST /tasks` is explicit and stable
- but canonical `TaskEnvelope` construction is still too verbose for most ingress clients to handcraft repeatedly

That means the right next move, if this grows, is not deeper coupling. It is a small ingress-side request builder or adapter, similar to the existing Linear-shaped ingress adapter.

That builder now exists in [`modules/connectors/ingress_request_builder.py`](../../modules/connectors/ingress_request_builder.py) and is reused by the OpenClaw spike client.

Other observations:

- duplicate task handling is clear: `POST /tasks` returns `409`, and reevaluation remains explicit
- inspection endpoints are already sufficient for operator, dashboard, and thin-supervisor visibility
- no API redesign was required for this spike
- the same thin client can now observe both clarification-driven and review-driven supervision states through the canonical queue

## Thin Supervisor Loop

The spike now also includes a thin OpenClaw-side supervisor client in [`modules/connectors/openclaw_supervisor.py`](../../modules/connectors/openclaw_supervisor.py).

That loop does not invent new control-plane behavior. It:

- polls `GET /supervision/queue`
- enriches each attention item with `GET /tasks/<task_id>/read-model`
- inspects `GET /tasks/<task_id>/timeline`
- inspects `GET /tasks/<task_id>/evaluations`
- turns the canonical `suggested_action` into an explicit next-step decision

The loop remains intentionally narrow:

- `review_required` stays a manual-review requirement
- `clarification_required` stays a clarification collection requirement
- `invalid_execution_attempt` stays a proof-or-rework requirement unless a stronger canonical recovery path is added later

It currently performs bounded autonomous follow-ups only when the canonical task state is still dispatchable:

- if the queue surfaces `retryable_failure`, the loop may call `POST /tasks/<task_id>/dispatch` with an explicit `dispatch_trigger=openclaw_supervision_loop`
- if the queue surfaces `stale_active_task` for an `assigned` or `dispatch_ready` task, the loop may call the same canonical dispatch endpoint to kick stalled work back into motion
- if the queue surfaces `github_sync_required`, the loop may call `POST /sync/github` using repository and branch facts already recorded in the canonical execution summary

That keeps OpenClaw thin while proving the next autonomy step:

- OpenClaw can observe what needs attention
- OpenClaw can inspect the canonical evidence behind that attention
- OpenClaw can trigger a governed redispatch or GitHub sync without bypassing Harness lifecycle enforcement

Since the spike was written, Harness added a dedicated OpenClaw ingress adapter endpoint (`POST /ingress/openclaw`) that still delegates into canonical submission semantics (`POST /tasks`) rather than introducing a separate control-plane contract.

That ingress endpoint is now explicitly constrained to intake/planning handoff. It accepts task intent, provenance, and other ingress-owned context, but it rejects executor runtime facts, completion claims, and execution/terminal lifecycle states. OpenClaw can describe the work; it cannot declare the work executed or complete through ingress.

If OpenClaw submits a task as already `planned`, Harness now treats that as a stronger claim. The ingress payload must provide planning-grade objective fields, an explicit `plan_summary`, and must not carry unresolved conditions. Otherwise the handoff is rejected instead of letting vague orchestration look more resolved than it really is.

OpenClaw may also attach canonical planning structure such as `parent_task_id`, `dependencies`, and `required_capabilities`, but Harness validates that structure on ingress. Contradictory plan edges such as self-dependencies are rejected instead of being treated as advisory planner notes.

If OpenClaw still knows the task is ambiguous or incomplete, Harness now maps that upstream signal into canonical clarification state and blocks the task. The ambiguity is no longer preserved only as loose request baggage.

Dispatch policy also now enforces declared blocking dependencies mechanically. A task that is `dispatch_ready` but still waiting on an upstream dependency does not auto-dispatch and cannot be manually forced through the dispatcher until the required upstream milestone is actually satisfied.

## Scope Limits

This spike does not implement:

- OpenClaw plugin lifecycle integration
- OpenClaw gateway runtime integration
- live OpenClaw message/channel wiring

It is intentionally a narrow proof that OpenClaw can remain a client and Harness can remain a standalone service.

## Hosted Proof Artifact Attribution Note (KNO-167)

For the hosted ingress validation follow-up, see [`docs/demo/kno-167-hosted-proof/README.md`](../demo/kno-167-hosted-proof/README.md).

That note records an artifact-contract correction: the hosted verification run did not create a branch/commit/PR, so historical PRs must not be used as substitute proof for that run.
