# Module Boundaries

## Objective

Define a single owner for each core module and keep ingress, orchestration, structured work, and execution separate.

## Boundary Model

Each module below has one owner. Ownership here means responsibility for the module's behavior, interfaces, and state transitions.

| Module | Owner | Responsibilities | Must Not Own |
| --- | --- | --- | --- |
| Ingress adapter | OpenClaw integration layer | receive validated requests from OpenClaw, return status and results upstream, map clarification outcomes into Harness input contracts | task decomposition, executor selection, durable workflow state |
| Intake and normalization | Harness core | convert validated requests into canonical Harness work objects, reject malformed inputs, attach metadata needed for planning | UI policy, executor-specific logic |
| Planning and decomposition | Harness core | create epics, tasks, and dependency edges from normalized requests | direct execution, persistence substrate details |
| Work registry sync | Linear integration layer | create and update Linear records, reconcile Harness state with Linear task state, enforce Linear as structured work record | decomposition policy, executor runtime control |
| Assignment and routing | Harness core | choose executor type, assign work, reassign stalled tasks, enforce assignment rules | executor implementation details, user-facing clarification |
| Execution gateway | Executor integration layer | send tasks to Codex or future workers, collect outputs, normalize execution events | planning, Linear ownership, long-term orchestration policy |
| Workflow runtime adapter | Workflow substrate layer | persist workflow checkpoints, resume interrupted runs, model orchestration progress through durable state | user-facing ingress, structured work definitions |
| Reporting and summarization | Harness core | aggregate task outcomes and expose upstream progress summaries | direct executor control, source-of-truth ownership |

## Ownership Rules

- Harness core owns orchestration policy.
- Linear integration owns synchronization with Linear only.
- Executor integrations own protocol translation to specific workers only.
- Workflow substrate owns internal durability only.
- OpenClaw integration owns ingress and upstream reporting surfaces only.

## Interaction Rules

- OpenClaw may submit work to Harness, but not mutate internal orchestration state directly.
- Harness core may request persistence from the workflow substrate, but should not couple business rules to a specific substrate API.
- Harness core may update structured work through the Linear integration layer, but should not treat executor events as the source of truth.
- Executors may report status and outputs, but they do not decide final work state without Harness applying policy.

## Required Contracts

### Request Contract

Input entering Harness after clarification is complete.

Required fields should eventually include:

- request identifier
- originating ingress
- validated objective
- constraints
- requested deliverable shape

### Task Contract

Unit of structured work tracked by Harness and represented in Linear.

Required fields should eventually include:

- task identifier
- parent work item
- owner executor type
- status
- dependencies
- expected output contract

### Execution Event Contract

Message from an executor back to Harness.

Required fields should eventually include:

- executor identifier
- task identifier
- event type
- timestamp
- payload

## Anti-Patterns To Avoid

- putting clarification logic into the control plane after work is accepted
- letting executor implementations define task semantics
- treating workflow checkpoint state as the product-facing source of truth
- storing business workflow policy inside a vendor-specific orchestration graph
