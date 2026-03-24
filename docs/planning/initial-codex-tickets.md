# Initial Codex Tickets

## Purpose

These tickets translate Epic 1 into concrete follow-on implementation work while keeping reliability, verification, and control-plane guarantees ahead of generic orchestration sophistication.

They assume Linear remains the upstream work surface and system of record rather than a product area Harness should compete with.

## Proposed Tickets

### Ticket 1: Define canonical contracts

- create request, task, and execution event contracts
- define status enums, evidence requirements, and ownership fields
- document which contracts are business state versus runtime state

### Ticket 2: Define artifact and evidence model

- define pull request, commit, log, and output evidence contracts
- specify which task classes require artifact-backed completion
- document how evidence is referenced and reconciled

### Ticket 3: Build completion verification path

- implement verification rules that prevent unverified terminal completion
- enforce explicit blocked, failed, and completed semantics
- record why completion was accepted or rejected

### Ticket 4: Model structured work synchronization

- define how Harness task state maps to Linear state
- identify fields that must remain authoritative in Linear
- specify reconciliation rules for drift and failed updates
- ensure Harness writes back verified outcomes so Linear reflects trusted state rather than executor claims

### Ticket 5: Add GitHub evidence reconciliation

- define how PRs, commits, and review status map to task evidence
- specify which GitHub facts are required for code-bearing completion
- reconcile artifact evidence against task lifecycle state

### Ticket 6: Create control-plane skeleton

- scaffold control-plane modules for intake, planning, dispatch, verification, and reporting
- add package-level documentation for each module
- avoid runtime logic beyond boundary scaffolding
- keep planner, dispatcher, and runtime work explicitly in service of verification and enforcement rather than as the primary product surface

### Ticket 7: Define executor task lifecycle

- document assignment, heartbeat, completion claim, failure, and retry events
- specify what an executor can report versus what Harness decides
- make executor replacement an explicit design constraint

### Ticket 8: Define substrate abstraction

- create substrate-facing interfaces for checkpoint persistence, workflow resume, and event replay
- keep substrate contracts independent from LangGraph or Temporal types
- add architecture tests for forbidden dependency directions

### Ticket 9: Add architecture guardrails

- add dependency-direction tests or lint rules
- enforce separation between control-plane modules, integrations, and substrate
- prevent executor-specific imports from leaking into control-plane modules
- prevent work-surface concerns from leaking into Harness verification and enforcement logic

## Sequencing

Recommended order:

1. canonical contracts
2. artifact and evidence model
3. completion verification path
4. structured work synchronization
5. GitHub evidence reconciliation
6. architecture guardrails
7. control-plane skeleton
8. executor lifecycle
9. substrate abstraction
