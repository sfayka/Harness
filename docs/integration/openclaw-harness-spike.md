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

The spike client lives in [`modules/connectors/openclaw_harness_spike.py`](/Users/ssbob/Documents/Developer/Knox_Analytics/Harness/modules/connectors/openclaw_harness_spike.py).

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
- `GET /tasks/<task_id>`
- `GET /tasks/<task_id>/read-model`
- `GET /tasks/<task_id>/timeline`
- `GET /tasks/<task_id>/evaluations`

## Representative Flow

The built-in spike flow intentionally exercises a real control-plane change:

1. OpenClaw-style client submits a task that claims completion
2. Harness blocks the task because required evidence is still missing
3. OpenClaw-style client submits reevaluation with the missing review-note artifact
4. Harness accepts completion
5. Client fetches read model, timeline, and evaluation history

## What Was Learned

The current boundary works cleanly for a thin client.

The main friction point is task creation verbosity:

- `POST /tasks` is explicit and stable
- but canonical `TaskEnvelope` construction is still too verbose for most ingress clients to handcraft repeatedly

That means the right next move, if this grows, is not deeper coupling. It is a small ingress-side request builder or adapter, similar to the existing Linear-shaped ingress adapter.

Other observations:

- duplicate task handling is clear: `POST /tasks` returns `409`, and reevaluation remains explicit
- inspection endpoints are already sufficient for operator and dashboard visibility
- no API redesign was required for this spike

## Scope Limits

This spike does not implement:

- OpenClaw plugin lifecycle integration
- OpenClaw gateway runtime integration
- live OpenClaw message/channel wiring
- a new Harness ingress endpoint for OpenClaw

It is intentionally a narrow proof that OpenClaw can remain a client and Harness can remain a standalone service.
