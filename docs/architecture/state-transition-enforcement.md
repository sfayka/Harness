# State Transition Enforcement

## Purpose

Define the canonical state transition enforcement rules for Harness.

Harness is a reliability/control-plane system. Lifecycle states are enforced control-plane states, not informational labels or worker hints.

A state transition is valid only when:

- the transition is allowed by policy
- the responsible module or actor is authorized to cause it
- the required preconditions are satisfied
- the transition is recorded as an auditable state change

## Core Rule

Executor-reported events alone do not authorize arbitrary lifecycle movement.

Workers may emit facts.

Harness modules decide whether those facts justify a state transition.

## Canonical States

Harness uses these canonical task lifecycle states:

- `intake_ready`
- `planned`
- `dispatch_ready`
- `assigned`
- `executing`
- `blocked`
- `completed`
- `failed`
- `canceled`

## Transition Authority Model

State transitions are owned by specific modules or authorized actors.

The main transition authorities are:

- intake and clarification handling
- planner
- dispatcher
- runtime
- verification
- manual review or operator override

No module may cause lifecycle movement outside its authority just because it observed a relevant fact.

## Transition Table

| From | To | Allowed | Primary authority | Preconditions |
| --- | --- | --- | --- | --- |
| `intake_ready` | `planned` | yes | planner | task is valid, clarification is absent or resolved, planning preconditions are satisfied |
| `intake_ready` | `blocked` | yes | intake or clarification handling | missing information, ambiguity, or another control-plane blocker prevents safe planning |
| `planned` | `dispatch_ready` | yes | planner or control-plane planning finalization | decomposition is complete enough for routing, dependencies/checkpoints are defined |
| `planned` | `blocked` | yes | planner or verification/control plane | unresolved dependency, clarification, or planning-detected blocker exists |
| `planned` | `canceled` | yes | operator or authorized control-plane policy | task is intentionally stopped |
| `dispatch_ready` | `assigned` | yes | dispatcher | dispatch preconditions hold, executor selected, assignment recorded |
| `dispatch_ready` | `blocked` | yes | dispatcher or operator | dependencies unresolved, clarification unresolved, no valid executor, or policy forbids dispatch |
| `dispatch_ready` | `canceled` | yes | operator or authorized control-plane policy | task is intentionally stopped |
| `assigned` | `executing` | yes | runtime | real execution-start fact exists |
| `assigned` | `blocked` | yes | dispatcher, runtime, or operator | assignment cannot safely proceed, start failed, clarification reopened, or review/policy blocks execution |
| `assigned` | `failed` | yes | runtime or verification | startup or execution attempt is terminally unsuccessful under policy |
| `assigned` | `canceled` | yes | operator or authorized control-plane policy | assignment or task is intentionally stopped |
| `executing` | `completed` | yes | verification | runtime facts, evidence, and reconciliation satisfy completion policy |
| `executing` | `blocked` | yes | runtime, clarification handling, or verification | stall, missing input, reconciliation blocker, or review requirement prevents safe continuation or acceptance |
| `executing` | `failed` | yes | runtime or verification | execution attempt or resulting outcome is terminally unusable under policy |
| `executing` | `canceled` | yes | operator or authorized control-plane policy | execution is intentionally stopped |
| `completed` | `blocked` | yes | verification or reconciliation-driven control-plane policy | later verification/reconciliation shows outcome is provisional, insufficient, or contradictory |
| `blocked` | `intake_ready` | yes | clarification handling or operator | blocked intake task has newly resolved clarification and must resume normalization |
| `blocked` | `planned` | yes | planner, clarification handling, or operator | planning blocker resolved and task should return to planned state |
| `blocked` | `dispatch_ready` | yes | dispatcher or operator | dispatch blocker resolved and task is ready for assignment |
| `blocked` | `assigned` | yes | dispatcher | reassignment/redispatch is explicitly allowed and active assignment is recorded |
| `blocked` | `executing` | yes but narrow | runtime | execution resumes from a blocked in-flight state and a real execution-start/resume fact exists |
| `blocked` | `canceled` | yes | operator or authorized control-plane policy | blocked task is intentionally stopped |

## Transition Ownership By Module

### Intake And Clarification Handling

May cause:

- `intake_ready` -> `blocked`
- `blocked` -> `intake_ready`

Typical reasons:

- missing required information
- ambiguity discovered before planning
- clarification resolved and intake can resume

### Planner

May cause:

- `intake_ready` -> `planned`
- `planned` -> `dispatch_ready`
- `planned` -> `blocked`
- controlled re-entry from `blocked` -> `planned`

Planner does not own dispatch, execution start, completion, or terminal success/failure decisions.

### Dispatcher

May cause:

- `dispatch_ready` -> `assigned`
- `dispatch_ready` -> `blocked`
- `blocked` -> `dispatch_ready`
- controlled `blocked` -> `assigned` in redispatch or reassignment flows

Dispatcher does not own `assigned` -> `executing`; that belongs to runtime after a real start fact.

### Runtime

May cause:

- `assigned` -> `executing`
- `assigned` -> `blocked`
- `assigned` -> `failed` when startup or execution is terminally unusable under policy
- `executing` -> `blocked`
- `executing` -> `failed`
- narrow `blocked` -> `executing` when execution truly resumes

Runtime does not own `executing` -> `completed`.

Runtime may report success facts, but verification decides whether completion is accepted.

### Verification

May cause:

- `executing` -> `completed`
- `executing` -> `blocked`
- `executing` -> `failed`
- `completed` -> `blocked`

Verification owns completion acceptance policy and may reverse a provisional completed state when later facts invalidate it.

### Manual Review / Operator

May cause or authorize:

- transitions to `canceled`
- review-driven preservation of `blocked`
- override-driven re-entry into earlier states when policy permits
- explicit acceptance or rejection after manual review

Manual review is not a freeform permission to skip policy. It is an authorized control-plane decision path.

## Preconditions By Transition Family

### Entry To Planned

Required:

- valid task contract
- clarification absent or resolved
- enough structure to support decomposition

### Entry To Dispatch Ready

Required:

- planning output is complete enough for routing
- child tasks, dependencies, and checkpoints are explicit
- no unresolved planning blocker remains

### Entry To Assigned

Required:

- task is dispatch-eligible
- required dependencies and clarification are satisfied
- executor selection is made
- `assigned_executor` is updated
- assignment is auditable

### Entry To Executing

Required:

- active assignment exists
- execution request was accepted
- runtime has a trustworthy start or resume fact

Assignment alone is not enough.

### Entry To Completed

Required:

- runtime facts indicate an execution outcome exists
- acceptance criteria are satisfied strongly enough for policy
- required evidence is satisfied
- reconciliation is non-blocking where required
- verification accepts the result

This transition is always provisional until verification and required reconciliation pass.

### Entry To Blocked

`blocked` may be entered from multiple states, but only for explicit reasons such as:

- unresolved clarification
- unresolved dependency
- dispatch blocker
- runtime stall
- verification insufficiency
- reconciliation mismatch
- manual review pending

`blocked` must never be a silent dumping ground for unknown conditions.

### Entry To Failed

Required:

- policy determines the execution outcome is terminally unusable
- the task cannot be recovered through retry, reassignment, clarification, or additional evidence alone

### Entry To Canceled

Required:

- explicit intentional stop by an authorized operator or control-plane policy

Cancellation is not inferred from silence or worker inactivity.

## Forbidden And Invalid Transitions

The following transitions are forbidden unless the architecture changes explicitly:

- `intake_ready` -> `dispatch_ready`
- `intake_ready` -> `assigned`
- `intake_ready` -> `executing`
- `planned` -> `assigned`
- `planned` -> `executing`
- `dispatch_ready` -> `executing`
- `assigned` -> `completed`
- `completed` -> `executing`
- `completed` -> `assigned`
- `failed` -> any non-terminal state by default
- `canceled` -> any non-terminal state by default

Why these are forbidden:

- they skip required control-plane phases
- they collapse dispatch and execution start
- they bypass verification for completion
- they reopen terminal states without explicit future policy

If future architecture introduces controlled reopening of `failed` or `canceled`, that should be a deliberate contract change rather than an implicit exception.

## Provisional And Review-Driven Transitions

### Completed Is Provisional

`completed` is not durable merely because it was set once.

It survives only while verification continues to accept it.

If later evidence or reconciliation contradicts it, verification may move the task back to `blocked`.

### Manual Review Is Non-Terminal

Manual review does not itself create a terminal lifecycle state.

It is an outcome that usually keeps the task non-final until a later explicit decision resolves it.

Possible later results:

- accepted completed outcome
- continued `blocked`
- `failed`
- `canceled`

## Retry, Re-Dispatch, Re-Plan, And Re-Entry

### Retry

Retry is an additional execution attempt against the same task.

Typical lifecycle effect:

- task may remain `executing` while retry is in-flight under runtime control
- or move to `blocked` and later re-enter through dispatcher/runtime policy depending on implementation

Retry does not create a new task lifecycle family by itself.

### Re-Dispatch / Reassignment

Redispatch or reassignment typically re-enters through:

- `blocked` -> `dispatch_ready`
- `blocked` -> `assigned`

Required:

- prior assignment is no longer sufficient
- dispatcher policy explicitly permits reassignment
- reassignment is auditable

### Re-Planning

Re-planning is an explicit control-plane action, not an automatic side effect.

Typical re-entry path:

- `blocked` -> `planned`

Required:

- new clarification, scope change, or policy decision justifies a new plan
- prior plan outputs remain auditable even if superseded

### Review-Driven Re-Entry

Manual review may resolve a non-final state back into:

- `blocked`
- `planned`
- `dispatch_ready`
- accepted `completed` outcome through verification policy

Review does not authorize arbitrary jumps that skip required control-plane phases.

## Blocked State Entry And Exit

`blocked` is reusable but not generic.

Entry to `blocked` must record:

- the triggering condition
- the responsible module or actor
- what must change for exit to be allowed

Exit from `blocked` must be directed to the appropriate prior phase:

- clarification resolved -> `intake_ready` or `planned`
- dispatch blocker resolved -> `dispatch_ready` or `assigned`
- execution resume fact exists -> `executing`
- verification/reconciliation issue resolved -> whichever non-terminal state policy requires next

## Auditability Requirements

Every non-initial transition should remain reviewable.

At minimum, the control plane should preserve:

- from-state
- to-state
- transition timestamp
- responsible module or actor
- reason for the transition
- any supporting evidence or policy basis

The goal is that a reviewer can answer:

- who caused the state change
- why it was allowed
- what preconditions were satisfied
- whether the transition followed policy
