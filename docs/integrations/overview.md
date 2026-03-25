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

Relevant code and docs:

- [modules/connectors/openclaw_harness_spike.py](../../modules/connectors/openclaw_harness_spike.py)
- [modules/connectors/ingress_request_builder.py](../../modules/connectors/ingress_request_builder.py)
- [docs/integration/openclaw-harness-spike.md](../integration/openclaw-harness-spike.md)

## Live Vs Simulated Integrations

Real today:

- canonical API submission and reevaluation
- normalized fact models
- Linear-shaped ingress adapter
- OpenClaw-informed thin client spike

Not live today:

- live GitHub polling or webhook orchestration
- live Linear issue creation or sync loops
- full OpenClaw runtime/plugin lifecycle integration

That split is intentional. Harness should remain a standalone control-plane service, not become tightly coupled to any single ingress or executor runtime.
