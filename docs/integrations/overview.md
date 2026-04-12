# Integrations Overview

Harness is API-first and connector-neutral.

## Boundary Model

- ingress clients submit work into Harness
- Harness owns canonical task truth and lifecycle correctness
- external systems provide facts, not automatic truth

## Linear

Linear is the structured-work system of record and coordination surface.

Linear contributes intended-work context such as:

- issue identity
- title and description
- workflow or status metadata
- optional labels, priority, and references

Harness translates that into canonical task and fact structures. Harness does not treat Linear workflow state alone as proof of completion.

## GitHub

GitHub is the artifact system of record.

Harness consumes normalized GitHub facts such as:

- repository and branch identity
- commits
- pull requests
- changed-file summaries
- artifact references

Those facts support reconciliation and verification. They do not bypass policy enforcement.

## OpenClaw And Similar Clients

OpenClaw is treated as an ingress client, not a runtime dependency of Harness.

The existing spike demonstrated:

- the public Harness API is sufficient for a thin real client
- task creation verbosity was the main pain point
- the right fix was a thin request-builder adapter, not a new control-plane shape

Harness now includes an OpenClaw-shaped ingress endpoint (`POST /ingress/openclaw`) backed by a thin adapter that normalizes request content into canonical submission payloads.

Harness also now exposes a canonical supervision polling surface for ingress-side autonomy:

- `GET /supervision/queue`

That queue is a read-only projection over canonical Harness truth. It is intended for OpenClaw-style supervisors that need to know which tasks currently require attention because they are review-gated, clarification-blocked, retryable, showing invalid execution proof, or stale.

Relevant code and docs:

- [modules/connectors/openclaw_harness_spike.py](../../modules/connectors/openclaw_harness_spike.py)
- [modules/connectors/openclaw_ingress.py](../../modules/connectors/openclaw_ingress.py)
- [modules/connectors/ingress_request_builder.py](../../modules/connectors/ingress_request_builder.py)
- [docs/integration/openclaw-harness-spike.md](../integration/openclaw-harness-spike.md)

## Live Vs Simulated Integrations

Real today:

- canonical API submission and reevaluation
- canonical supervision queue for autonomous polling
- normalized fact models
- Linear-shaped ingress adapter
- OpenClaw-shaped ingress adapter
- OpenClaw-informed thin client spike
- OpenClaw-style simulator flows that can inspect final supervision state through the public API

Not live today:

- live GitHub polling or webhook orchestration
- live Linear issue creation or sync loops
- full OpenClaw runtime/plugin lifecycle integration or autonomous loop execution

That split is intentional. Harness should remain a standalone control-plane service, not become tightly coupled to any single ingress or executor runtime.
