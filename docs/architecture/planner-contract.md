# Planner Contract

## Purpose

Define the canonical contract for planner behavior in Harness.

Harness is a reliability/control-plane system. The planner is not a freeform reasoning agent. It is a bounded module that transforms sufficiently defined task contracts into a structured, reviewable execution plan.

## Planner Role

The planner takes a valid task contract that is ready for planning and produces a decomposition that later modules can execute without reinterpretation.

The planner is responsible for:

- decomposing a sufficiently defined task into child tasks
- defining dependency edges between planned tasks
- identifying checkpoints or validation gates needed before later work may proceed
- preserving the parent task objective, constraints, and acceptance criteria in a structured plan
- producing planning output that is auditable and reviewable

The planner is not responsible for:

- clarification policy at ingress
- executor selection
- workflow runtime durability
- artifact-backed completion verification
- reconciliation with GitHub or Linear
- freeform execution of the task itself

## Preconditions For Planning

Planning may begin only when all of the following are true:

- the input `TaskEnvelope` is schema-valid
- the task is in a planning-eligible lifecycle state
- required clarification is absent or resolved
- no blocking reconciliation or evidence mismatch prevents safe planning
- the objective, constraints, and acceptance criteria are sufficiently defined to support decomposition

### Planning-Eligible Lifecycle States

The primary planning entry state is:

- `intake_ready`

Harness may also allow explicit replanning of an already planned task when policy permits, but that is a separate control-plane action, not the default planner path.

The planner must not begin normal planning from:

- `blocked` when clarification is still unresolved
- `assigned`
- `executing`
- `completed`
- `failed`
- `canceled`

### Clarification Preconditions

Planning must not proceed if the task still has unresolved required clarification.

Planning is blocked when:

- `clarification.status` is `required`, `requested`, or `answered`
- a required clarification input remains open
- the task depends on a human or upstream system response that has not yet been resolved

Planning may proceed when:

- no `clarification` object is present, or
- `clarification.status` is `resolved`, and
- required inputs have been satisfied or explicitly waived by policy

### Reconciliation And Evidence Preconditions

Planning is usually an early lifecycle activity, so reconciliation is normally not the active blocker.

However, if planning is invoked as part of a controlled replan flow, it must not proceed while the task is blocked by:

- missing required completion evidence
- contradictory GitHub or Linear facts
- unresolved reconciliation mismatches that make the current task shape untrustworthy

The planner must not paper over evidence or reconciliation problems by silently creating a new plan.

## Planner Input Contract

The planner receives:

- one canonical parent `TaskEnvelope`
- optional control-plane planning directives supplied outside the task contract

### Required TaskEnvelope Inputs

The planner relies on these fields from the parent task:

- `id`
- `title`
- `description`
- `objective`
- `constraints`
- `acceptance_criteria`
- `status`
- `clarification`
- `dependencies`

The planner may inspect:

- `origin` for provenance
- `artifacts` for context, but not for completion authority
- `observability` for audit or prior planning attempts

The planner must not require executor-native payloads or runtime checkpoint state as input.

### Optional Planning Directives

Harness core may supply non-canonical planning directives such as:

- maximum decomposition depth
- preferred task granularity
- planning policy profile
- whether checkpoint tasks are required for this plan

These directives shape planning behavior, but they do not replace the canonical task contract.

## Planner Output Contract

The planner output is a structured planning bundle, not a freeform narrative.

It must contain enough structure for later modules to register tasks, evaluate dependencies, and route work without reinterpreting planner intent.

## Canonical Planner Output Shape

A planner output bundle should contain:

- `plan_id`
- `parent_task_id`
- `planner_run`
- `plan_summary`
- `parent_task_update`
- `child_tasks`
- `dependency_edges`
- `checkpoint_tasks`
- `planning_notes`

### Plan Metadata

`plan_id`:

- stable identifier for the planning bundle

`planner_run`:

- planner module identity
- timestamp
- optional policy profile or version

### Plan Summary

`plan_summary` provides a concise, reviewable explanation of:

- the decomposition strategy
- the intended execution order
- major assumptions preserved from the parent task
- any explicit non-goals or excluded scope

This is for auditability, not for downstream reinterpretation.

### Parent Task Update

The planner may propose a bounded update to the parent task.

Allowed parent-task planning updates include:

- `status` -> `planned`
- `child_task_ids`
- planning-related `status_history` entry
- plan attachment metadata through approved extension or registry surfaces

The planner must not use the parent update to:

- assign executors
- mark evidence satisfied
- mark the task completed
- rewrite origin semantics

## Child Task Representation

Executable decomposition results are represented as child `TaskEnvelope` records.

Each child task must:

- be independently schema-valid
- have its own stable `id`
- reference the parent through `parent_task_id`
- start in `planned`
- inherit only the constraints and acceptance criteria that actually apply to that child

Each child task should include:

- a clear objective
- explicit acceptance criteria
- any child-specific constraints
- empty or deferred dispatcher-owned and execution-owned fields

The planner must not create vague child tasks that require later modules to guess what work was intended.

## Dependency Semantics

Dependency edges must be explicit and machine-usable.

The planner output must identify:

- which task depends on which upstream task
- the dependency type
- the required upstream status before the downstream task may proceed

Downstream modules should be able to register these edges directly into `dependencies` without inventing new meaning.

The planner should not use narrative notes as a substitute for actual dependency edges.

## Checkpoint And Validation Gate Semantics

Harness needs checkpoints, but they should remain explicit work objects rather than hidden planner prose.

In the initial contract, a checkpoint is represented as a planned child task whose purpose is validation, review, or gatekeeping rather than primary execution.

Typical checkpoint task characteristics:

- `objective.deliverable_type` identifies the task as a checkpoint or validation gate
- downstream tasks depend on the checkpoint task reaching `completed`
- the checkpoint task has explicit acceptance criteria describing the gate condition

Examples:

- architecture review gate before implementation tasks dispatch
- test-plan approval gate before code execution begins
- artifact-review gate before completion is considered

This keeps checkpoint semantics inside the normal task and dependency model without inventing a second, weaker planning-only object.

`checkpoint_tasks` in the planner output are therefore a labeled subset of `child_tasks`, included separately for reviewability.

## Planning Failure And Clarification Discovery

The planner must not compensate for missing required information by guessing.

If planning discovers unresolved ambiguity or missing required inputs, the planner should return a blocked planning outcome rather than a speculative decomposition.

That outcome should identify:

- why planning could not proceed
- which inputs are missing or ambiguous
- whether clarification is required before planning can resume

The planner may surface clarification findings, but it does not own ingress conversation state. Harness core remains responsible for attaching any resulting clarification contract back to the task.

## Ownership Boundaries

### Intake Owns

- request normalization
- initial task construction
- intake-owned defaults
- initial clarification capture

### Planner Owns

- decomposition strategy
- child task creation
- dependency definition
- checkpoint definition
- transition into a structured planned state

### Dispatcher Owns

- executor selection
- assignment decisions
- routing policy

### Runtime Owns

- durable checkpoint persistence
- retries, resumes, and execution orchestration progress

### Verification And Reconciliation Own

- artifact validation
- completion enforcement
- external system consistency checks

## What The Planner May Not Decide

The planner must not:

- choose Codex, Claude, or any other specific executor
- mark a task `dispatch_ready`, `assigned`, `executing`, or `completed`
- declare artifact evidence satisfied
- declare reconciliation complete
- mutate GitHub or Linear state directly
- treat reasoning quality as a substitute for explicit task structure

## How Planning Results Attach Back To Harness

Planning results attach back through controlled control-plane updates:

- parent task status changes to `planned`
- child tasks are registered as canonical `TaskEnvelope` records
- `parent_task_id` and `child_task_ids` are updated
- `dependencies` are written onto the affected child tasks
- checkpoint tasks are registered as normal planned tasks with gate semantics

The planner output bundle should also remain available for audit so humans can inspect what the planner proposed and why.

## Auditability Requirements

Planner output must be reviewable after the fact.

At minimum, the control plane should preserve:

- planner identity and run timestamp
- the planning summary
- created child task IDs
- defined dependency edges
- checkpoint tasks
- any explicit assumptions or exclusions

The goal is that a human reviewer can answer:

- what the planner received
- why it decomposed the task this way
- what work it created
- what later modules were expected to do with that output
