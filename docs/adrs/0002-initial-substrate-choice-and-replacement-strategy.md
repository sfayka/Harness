# Initial Substrate Choice And Replacement Strategy

- title: Initial substrate choice and replacement strategy
- status: accepted
- date: 2026-03-23

## Context

Harness requires a workflow substrate that supports persistence, resumability, and controlled execution of multi-step tasks.

The system is early-stage, open-source, and not monetized. Priorities are:

- keeping the system model understandable
- minimizing operational overhead
- avoiding premature platform lock-in
- ensuring long-term replaceability of the workflow substrate
- keeping verification, evidence enforcement, and lifecycle correctness in Harness-owned code

The current candidate set is:

- LangGraph
- Temporal
- building a custom substrate

The architecture must allow replacing the underlying substrate later without rewriting the control plane or business logic.

## Decision

Harness will implement a **thin orchestration layer with explicit, Harness-owned contracts**, and use a **lightweight external substrate for persistence and resumability**.

The system is structured as follows:

- Harness defines:
  - task schema and lifecycle
  - module boundaries
  - orchestration rules and transitions
  - execution routing and event handling
  - verification rules and evidence requirements

- The substrate provides:
  - checkpoint persistence
  - resumability
  - durable step execution primitives (as available)

- All substrate-specific behavior is isolated behind **adapter interfaces**

For the initial implementation, prefer a **lightweight, low-operational-overhead substrate** (e.g., LangGraph or equivalent), but do not encode business logic directly in substrate-native constructs.

## Rationale

This approach balances control and pragmatism:

- avoids building a custom workflow engine prematurely
- keeps business logic and orchestration semantics owned by Harness
- keeps verification and artifact-backed completion out of substrate-native constructs
- reduces operational complexity compared to full platforms like Temporal
- allows early contributors to reason about the system without deep framework knowledge
- maintains flexibility to change substrates later

## Consequences

- additional abstraction layer (Harness contracts + substrate adapters) must be maintained
- developers must be disciplined about not leaking substrate-specific concepts into business logic
- some substrate capabilities may not be fully utilized initially
- system remains understandable and evolvable as the domain model stabilizes
- correctness still depends on Harness enforcing evidence and system-of-record rules above the substrate layer

## Alternatives Considered

### LangGraph

Viable as an initial substrate.

Pros:
- built-in persistence and resumability for agent-style workflows
- lower operational overhead than full workflow platforms
- good fit for iterative development

Cons:
- graph-native modeling can leak into business logic if not carefully isolated
- not designed as a general-purpose control plane

Use strategy:
- acceptable as initial substrate **only behind adapter boundaries**
- do not encode core orchestration logic as graph definitions

---

### Temporal

Not selected as the initial substrate.

Pros:
- strong durability guarantees
- mature model for long-running workflows
- scalable and production-proven

Cons:
- high operational and conceptual overhead
- requires stable workflow definitions to be effective
- over-optimizes for scale at the current stage

Use strategy:
- strong candidate for future adoption if system scale and reliability requirements increase

---

### Build Custom Substrate

Not selected as the default approach.

Pros:
- maximum control
- no external dependencies

Cons:
- requires re-implementing persistence, resumability, and replay semantics
- high risk of incomplete or fragile workflow guarantees
- significant engineering cost with low early leverage

Use strategy:
- limit custom implementation to:
  - domain models
  - orchestration contracts
  - control-plane logic
- do not attempt to build a full workflow engine

## Replacement Strategy

Substrate replacement is enabled by enforcing strict architectural boundaries:

- all orchestration state is defined in Harness-owned contracts
- substrate interfaces abstract persistence and execution
- Linear identifiers and task states remain business-level concepts
- artifact evidence and verification rules remain business-level concepts
- executor interactions are independent of substrate types

If replacement is required:

1. keep task and workflow contracts stable
2. implement a new substrate adapter
3. migrate or replay active workflow state if necessary
4. transition new workflows to the new substrate
5. deprecate the old adapter

## Architectural Constraint

Harness business logic must not depend on:

- LangGraph node or graph structures
- Temporal workflow classes or SDK types
- any substrate-specific execution model

All orchestration behavior must be expressed in Harness terms and mapped to the substrate via adapters.

Artifact-backed completion, auditability, and system-of-record reconciliation must also remain expressed in Harness terms rather than substrate-native workflow semantics.
