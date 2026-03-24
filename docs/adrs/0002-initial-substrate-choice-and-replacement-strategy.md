# Initial Substrate Choice And Replacement Strategy

- title: Initial substrate choice and replacement strategy
- status: accepted
- date: 2026-03-23

## Context

Harness needs a workflow substrate that provides persistence and resumability for orchestration. The initial choice should fit an early-stage open-source project with limited operational budget and a strong need to keep business rules understandable.

The current candidate set is:

- LangGraph
- Temporal
- build mostly ourselves with minimal framework support

The architecture also needs a credible path to replace the initial substrate later without rewriting the control plane.

## Decision

Start by building the workflow substrate mostly ourselves behind a narrow internal abstraction, using only minimal framework support where it removes obvious boilerplate.

The recommended shape is:

- explicit Harness state machines and contracts live in Harness-owned code
- substrate interfaces handle checkpoint persistence, resume, and event replay
- vendor-specific orchestration behavior stays behind adapters

This is the default starting point because it best matches the current stage of the project:

- it keeps the system model legible while core concepts are still changing
- it avoids early commitment to a graph-oriented or platform-oriented runtime model
- it reduces operational and conceptual overhead for a non-monetized open-source project
- it forces the control plane contracts to become explicit before platform lock-in happens

## Consequences

- initial implementation effort is higher than adopting a full orchestration platform immediately
- the project keeps tighter control over task lifecycle semantics
- later migration remains possible because business workflow state is defined in Harness terms rather than substrate terms
- early contributors can reason about the system without learning a large orchestration platform first

## Alternatives Considered

### LangGraph

Not the default starting point.

Reasons:

- its graph-centric model is attractive for persistent agent workflows, but Harness is primarily a control plane, not a graph-authored agent runtime
- adopting it early risks encoding business orchestration policy into framework-specific graph structures
- it is more useful after the core Harness state model is stable enough to map intentionally onto graph execution

Potential future use:

- if the system later benefits from graph-native resumability for planner-heavy flows, LangGraph can be introduced behind the substrate adapter for selected workflow classes

### Temporal

Not the default starting point.

Reasons:

- it offers strong durability and long-running workflow primitives, but adds operational weight and platform complexity too early
- it is a better fit once workflow volume, reliability demands, and team maturity justify the infrastructure cost
- starting there would optimize for scale and robustness before the Harness domain model is settled

Potential future use:

- if Harness grows into a multi-tenant or high-throughput orchestration service, Temporal is a credible replacement substrate because it is strong at durable execution once contracts are stable

### Build Mostly Ourselves With Minimal Framework Support

Chosen as the starting point.

Reasons:

- lowest operational burden
- best fit for an architecture that is still being defined
- easiest way to keep the substrate replaceable by making boundaries explicit now

## Replacement Strategy

The migration path depends on keeping these rules from day one:

- define orchestration state in Harness-owned contracts
- isolate checkpointing and resume behavior behind substrate interfaces
- treat Linear identifiers and task states as business-level references, not substrate internals
- keep executor event handling independent from vendor runtime types

If replacement becomes necessary later:

1. keep task and workflow state contracts stable
2. implement a new substrate adapter
3. replay or migrate active workflow state into the new adapter
4. cut over workflow creation to the new substrate while retiring the old adapter

The key architectural constraint is that Harness business rules must not depend on LangGraph nodes, Temporal workflow classes, or any other substrate-native model.
