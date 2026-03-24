# Initial Codex Tickets

## Purpose

These tickets translate Epic 1 into concrete follow-on implementation work without turning the repository into the task management system.

## Proposed Tickets

### Ticket 1: Define canonical contracts

- create request, task, and execution event contracts
- define status enums and ownership fields
- document which contracts are business state versus runtime state

### Ticket 2: Create control-plane skeleton

- scaffold `src/harness/` with intake, planning, assignment, and reporting module boundaries
- add package-level documentation for each module
- avoid runtime logic beyond boundary scaffolding

### Ticket 3: Create integration boundaries

- scaffold `src/integrations/openclaw/`, `src/integrations/linear/`, and `src/integrations/executors/codex/`
- define adapter interfaces without implementation detail leakage
- document what each integration owns and does not own

### Ticket 4: Define substrate abstraction

- create substrate-facing interfaces for checkpoint persistence, workflow resume, and event replay
- keep substrate contracts independent from LangGraph or Temporal types
- add architecture tests for forbidden dependency directions

### Ticket 5: Model structured work synchronization

- define how Harness task state maps to Linear state
- identify fields that must remain authoritative in Linear
- specify reconciliation rules for drift and failed updates

### Ticket 6: Define executor task lifecycle

- document assignment, heartbeat, completion, failure, and retry events
- specify what an executor can report versus what Harness decides
- make executor replacement an explicit design constraint

### Ticket 7: Add architecture guardrails

- add dependency-direction tests or lint rules
- enforce separation between `harness`, `integrations`, and `substrate`
- prevent executor-specific imports from leaking into control-plane modules

## Sequencing

Recommended order:

1. canonical contracts
2. control-plane skeleton
3. integration boundaries
4. substrate abstraction
5. structured work synchronization
6. executor lifecycle
7. architecture guardrails
