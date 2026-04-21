# Trace Continuity Model

## Status

Design/spec only. This document does not add storage, ingestion, runtime logging, or UI behavior.

Addresses: [GitHub issue #311](https://github.com/sfayka/Harness/issues/311)

## Purpose

Define how Harness preserves execution lineage across replay, retry, resume, compaction, handoff, and manual review.

Execution traces are not useful if they degrade into flat logs. Operators need to know which execution context an executor actually saw, which context was compacted or summarized, which attempt superseded another, and how handoff artifacts connect to the work lineage.

Trace continuity is descriptive/auditable truth. It does not authorize completion.

## Core Principle

Harness must preserve the difference between:

- what happened during execution
- how execution context changed over time
- which artifacts summarize or supersede prior context
- whether the final result is trustworthy enough to accept

The first three are lineage questions. The last remains verification and reconciliation policy.

## Identifiers

### `task_id`

Canonical Harness task identity.

All continuity records must link back to exactly one task.

### `attempt_id`

Concrete execution attempt identity.

One task may have many attempts across retries, redispatches, executor handoffs, or manual-review follow-up.

### `trace_segment_id`

Stable identity for one contiguous segment of execution context.

A segment usually starts when an executor receives a context bundle and ends when one of these happens:

- attempt completes, fails, stalls, or times out
- context is compacted or summarized
- work is handed to another executor
- manual review interrupts or redirects the attempt
- execution resumes with a materially different context bundle

### `continuity_group_id`

Identity for a lineage chain that should be understood together.

Segments inside the same continuity group may span retries, resumes, compactions, handoffs, and review intervention. Group membership does not imply success or consistency. It only says the segments are related enough that an operator should be able to reconstruct the chain.

### Relationship fields

Continuity records should support explicit relationships:

- `derived_from`: source segment or artifact used to create this segment
- `supersedes`: prior segment or artifact no longer used as the active context
- `compacted_from`: source segments summarized into a compacted representation
- `handoff_from`: prior executor/attempt context transferred into this segment
- `reviewed_from`: segment or artifact reviewed by a human decision

Relationships should point to stable record IDs. Missing references should be represented as unresolved provenance, not silently dropped.

## Mutation Semantics

### Replay

A replay reruns work from an earlier input or fixture.

Rules:

- replay creates a new `attempt_id`
- replay may share a `continuity_group_id` with the original attempt when the purpose is comparison or recovery
- replay must record `derived_from` pointing to the original attempt or segment
- replay must not overwrite the original attempt timeline

### Retry

A retry is a new execution attempt after a failed, stalled, or insufficient attempt.

Rules:

- retry creates a new `attempt_id`
- retry may share a continuity group with prior attempts on the same task
- retry must preserve prior failed and insufficient segments
- retry success must not collapse prior failure into a false single-success story

### Resume

Resume continues an interrupted attempt or stalled workflow from preserved context.

Rules:

- resume may keep the same `attempt_id` only if the execution substrate treats it as the same concrete run
- otherwise resume creates a new `attempt_id`
- resume always creates a new `trace_segment_id`
- resumed segments must reference the context bundle they resumed from

### Summarize / Compact

Compaction rewrites full-fidelity context into a shorter operational context.

Rules:

- compaction creates a new artifact or segment with `compacted_from` references
- compacted summaries must preserve enough provenance to reconstruct source segments
- compaction must distinguish dropped context from summarized context
- compaction must not erase contradictory facts

### Executor Handoff

Handoff transfers work from one executor or session to another.

Rules:

- handoff creates a `handoff_artifact`
- the new segment references the handoff artifact through `handoff_from`
- the handoff artifact references the source segment and source attempt
- handoff must record which context the receiving executor actually saw

### Manual Review Intervention

Manual review may inspect execution lineage and authorize a follow-up path.

Rules:

- review decisions reference the trace segments and artifacts inspected
- review-created follow-up segments record `reviewed_from`
- review does not mutate prior trace history
- review may authorize retry, redispatch, replan, clarification, failure, or completion only through normal policy surfaces

## Continuity-Preserving Artifacts

### `progress_artifact`

Use for structured progress state carried across execution cycles.

Continuity expectations:

- references the segment that produced it
- identifies which checklist, milestone, or progress state it summarizes
- does not imply completion by itself

### `handoff_artifact`

Use for session or executor transition context.

Continuity expectations:

- references source attempt and source segment
- records receiving executor or intended receiver when known
- records what context was handed off
- records what was intentionally omitted or unresolved

### Compacted summary artifact

Use when a full context bundle is summarized before replay, resume, or handoff.

Continuity expectations:

- references all source segments compacted into the summary
- records whether source detail remains available
- records whether any facts were dropped, elided, or contradicted

## Read And Query Requirements

Harness should eventually be able to answer:

- show the full lineage for a task
- show all attempts inside a continuity group
- show which context an executor actually saw
- show which artifacts superseded or summarized earlier context
- show what was dropped, compacted, or unresolved
- show manual review decisions linked to inspected segments
- show contradictory attempts without collapsing them into a single outcome

These are inspection requirements, not storage-engine requirements.

## Boundary Rules

- Trace continuity is observable execution lineage, not completion truth.
- A continuity group may contain failed, contradictory, stale, and successful segments.
- A compacted or handoff artifact is support context, not verified completion evidence by default.
- Continuity metadata may inform review, diagnosis, and local evals, but verification and reconciliation remain authoritative for completion.
- Trace ingestion or continuity reconstruction failure must not bypass lifecycle enforcement.

## Worked Example

1. Attempt `attempt-a` starts for task `task-123`.
2. Runtime records segment `seg-a1` in continuity group `cg-task-123-repair`.
3. The executor produces a progress artifact `progress-a1`.
4. Context is compacted into artifact `summary-a1`, with `compacted_from=["seg-a1"]`.
5. Attempt `attempt-a` resumes with segment `seg-a2`, `derived_from=["summary-a1"]`.
6. Work is handed to another executor with `handoff-1`, referencing `seg-a2`.
7. New executor starts `attempt-b`, segment `seg-b1`, `handoff_from=["handoff-1"]`, same continuity group.
8. Manual review inspects `seg-a2`, `handoff-1`, and `seg-b1`.
9. Review authorizes retry. Harness creates `attempt-c`, segment `seg-c1`, `reviewed_from=["review-decision-1"]`.
10. Completion still depends on GitHub/Linear evidence and Harness verification, not on the fact that the continuity chain exists.

## Related Documents

- [Runtime Execution Contract](runtime-execution-contract.md)
- [Artifact And Completion Evidence](artifact-and-completion-evidence.md)
- [Operator And Manual Review](operator-and-manual-review.md)
- [Harness Evolution Engine](harness-evolution-engine.md)
- [`modules/evolution/contracts/execution-trace-requirements.contract.md`](../../modules/evolution/contracts/execution-trace-requirements.contract.md)
