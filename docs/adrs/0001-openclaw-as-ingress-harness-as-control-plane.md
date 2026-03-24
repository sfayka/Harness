# OpenClaw As Ingress, Harness As Control Plane

- title: OpenClaw as ingress, Harness as control plane
- status: accepted
- date: 2026-03-23

## Context

The project needs a clear boundary between the user-facing agent experience and the system that manages durable work execution. If those concerns are merged too early, the system will blur clarification, planning, assignment, verification, persistence, and execution into one layer.

The desired operating model is:

- OpenClaw handles user interaction and clarification
- Harness manages decomposition, assignment, monitoring, verification, and reporting
- Linear stores structured work
- GitHub stores code-bearing completion evidence
- executors perform assigned tasks

## Decision

Treat OpenClaw as the ingress layer and Harness as the control plane.

This means:

- OpenClaw receives requests and resolves ambiguity before handoff
- Harness accepts validated requests as input contracts, not free-form conversation state
- Harness owns orchestration policy, verification policy, and task lifecycle decisions
- Harness reports status back to OpenClaw, which remains the user-facing surface
- executors are workers behind contracts rather than the source of truth for completion
- artifact-backed completion and auditability are Harness concerns, not ingress concerns

## Consequences

- ingress, control-plane enforcement, and execution stay separable
- Harness can evolve independently from the user-facing agent shell
- executor integrations can change without rewriting ingress behavior
- the system gains a clearer path to durable orchestration because conversation state is not the primary control plane
- completion trust is moved out of conversational claims and into evidence-backed control-plane policy

## Alternatives Considered

### OpenClaw As Both Ingress And Control Plane

Rejected because it couples user interaction with durable orchestration and makes the system harder to reason about, swap, and test.

### Linear As The Control Plane

Rejected because Linear is the source of truth for structured work, not the component that should own planning and routing policy.
