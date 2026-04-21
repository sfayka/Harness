# Execution Trace Requirements Contract

Planning scaffold only. This contract is not executable code.

## Purpose

Define the minimum execution-trace facts that future HEE analysis needs while preserving Harness completion and lifecycle authority boundaries.

## Design Principles

1. Execution traces describe what happened during execution attempts.
2. Verification and reconciliation remain the authoritative source of trusted completion.
3. Trace records must preserve provenance to canonical task, attempt, artifact, and evaluation records.
4. Trace requirements are additive observability guidance, not a new submission or lifecycle path.

## Minimum Fields

```text
ExecutionTraceRecord
  trace_id: string
  task_id: string
  attempt_id: string
  attempt_sequence: integer
  trace_segment_id: string
  continuity_group_id: string
  segment_sequence: integer
  segment_kind: execution | replay | retry | resume | compaction | handoff | review_annotation
  derived_from: TraceContinuityRef[]
  supersedes: TraceContinuityRef[]
  compacted_from: TraceContinuityRef[]
  handoff_from: TraceContinuityRef[]
  reviewed_from: TraceContinuityRef[]
  context_snapshot_ref: ContextSnapshotRef?
  handoff_artifact_refs: ArtifactRef[]
  event_time: timestamp
  event_type: string
  event_status: started | checkpoint | completed | failed | cancelled | timed_out
  actor_type: executor | harness | external_system | human_reviewer
  actor_id: string?
  correlation_id: string?
  step_key: string?
  message: string?
  artifact_refs: ArtifactRef[]
  evidence_refs: EvidenceRef[]
  evaluation_refs: EvaluationRef[]
  timeline_ref: TimelineRef?
  source_system: string
  source_record_id: string
  ingest_time: timestamp
  schema_version: string

TraceContinuityRef
  ref_type: trace_segment | trace_record | artifact | attempt | review_decision
  ref_id: string
  relationship: derived_from | supersedes | compacted_from | handoff_from | reviewed_from

ContextSnapshotRef
  snapshot_id: string
  source_system: string
  source_record_id: string
  captured_at: timestamp
```

## Scope Requirements

### Attempt-Scoped Requirements (required)

Attempt-scoped trace records must capture:

- the attempt identifier and sequence
- ordered step or checkpoint events
- terminal event and terminal reason when the attempt ends
- references to attempt-produced artifacts and evidence
- source provenance for every imported event

### Task-Scoped Requirements (required)

Task-scoped summaries may be derived from attempt traces, but must:

- preserve references back to contributing attempt IDs
- preserve ordering across attempts
- keep failed/cancelled/timed-out attempts visible
- avoid collapsing contradictory attempt outcomes into a single success claim

### Continuity Requirements (required)

Trace records must preserve execution lineage across replay, retry, resume, compaction, handoff, and manual review.

Continuity records must:

- assign each contiguous execution context a stable `trace_segment_id`
- group related segments with `continuity_group_id`
- preserve segment order with `segment_sequence`
- distinguish normal execution from replay, retry, resume, compaction, handoff, and review annotation
- explicitly link source records through `derived_from`, `supersedes`, `compacted_from`, `handoff_from`, or `reviewed_from`
- preserve the context snapshot or handoff artifact the executor actually received when available
- represent missing lineage as unresolved provenance rather than dropping it

## Provenance And Linkage Requirements

Trace records must remain linkable to canonical control-plane records:

- `TaskEnvelope` identity (`task_id`)
- execution attempts (`attempt_id`)
- trace segments (`trace_segment_id`)
- continuity groups (`continuity_group_id`)
- evaluation history entries (by explicit reference)
- timeline events (via `timeline_ref` when available)
- artifact and evidence records used for verification
- review records when trace events are inspected during manual review

Missing linkage should be represented as explicit unresolved provenance, not silently dropped.

## Boundary Rules

- Trace events are descriptive execution facts, not completion decisions.
- A terminal `completed` trace status does not authorize lifecycle transition by itself.
- A complete continuity chain does not prove the task outcome is correct.
- Compacted summaries and handoff artifacts are support context unless verification policy explicitly accepts them as evidence.
- Verification/reconciliation outcomes remain the trusted completion authority.
- Trace ingestion or analysis failures must not bypass policy enforcement.

## Non-Goals

- specifying storage engine or indexing strategy
- defining runtime logging library APIs
- defining diagnosis or proposal scoring algorithms
- replacing canonical evaluation history or timeline contracts

## Open Questions

- whether `event_type` should be normalized by a shared enum in v1
- whether actor identity should support structured resolver metadata beyond `actor_id`
- what retention windows should apply for full-fidelity trace events versus compacted summaries
- whether continuity groups should span only one task or support explicit cross-task lineage for future delegated workflows

## Related Documents

- `docs/architecture/trace-continuity.md`
- `docs/architecture/runtime-execution-contract.md`
- `docs/architecture/artifact-and-completion-evidence.md`
