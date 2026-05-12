# Long-Session Risk And Checkpoint Handoff

## Status

Design/spec only. This document does not add runtime detection, storage, API, or dashboard behavior.

Addresses: [GitHub issue #413](https://github.com/sfayka/Proofline/issues/413)

## Purpose

Define how Proofline should detect long-running agent or Codex sessions that are becoming risky, and what checkpoint or handoff evidence is required before the work continues or before a completion claim is accepted.

Long sessions are not automatically bad. They become risky when time, context size, repeated tool failures, missing artifacts, or stale evidence make it harder to trust the executor's current claim about progress or completion.

This model gives Proofline a way to say:

- execution may continue only after a checkpoint summary
- a fresh follow-up run should receive an explicit handoff
- manual review is required before accepting a completion claim
- the current session is informative context, not sufficient proof

## Boundary

Long-session risk is runtime and continuity risk. It is not completion truth.

Proofline may use this risk to require a checkpoint, handoff, manual review, or retry before accepting a claim. It must not use the absence of a long-session warning as proof that work is complete.

The detector must preserve the core invariants:

- executor-reported success is advisory only
- progress and handoff artifacts are support context, not completion evidence by default
- completion still depends on task-appropriate evidence and reconciliation
- manual review gates remain explicit and auditable
- trace continuity records what context the next executor actually saw

## Risk Signals

The first detector should combine objective runtime facts with artifact and evidence freshness.

### Time And Size

- elapsed runtime above configured threshold
- wall-clock idle time above configured threshold
- excessive accumulated token/output volume where available
- too many context compactions or summaries in one continuity group

### Progress Quality

- repeated planning or status narration without durable artifact changes
- no new artifact delta after a meaningful execution window
- no evidence update after a claimed implementation step
- repeated "almost done" or equivalent progress events without terminal proof

### Tool And Environment Reliability

- repeated tool errors in the same execution segment
- repeated failed validation commands
- unstable dev server, test runner, or dependency installation behavior
- inability to inspect generated artifacts after the executor claims they exist

### Continuity Quality

- large session handoff missing a structured summary
- compacted context with unresolved omissions
- handoff that does not identify source attempt, source segment, current branch, and known validation state
- receiving executor cannot identify what context was handed to it

## Default Threshold Bands

Implementations should make thresholds configurable, but the first policy can use bands rather than one brittle cutoff.

| Risk level | Default trigger examples | Required response |
| --- | --- | --- |
| `watch` | 45 minutes elapsed, 15 minutes idle, or 3 repeated tool errors | Add runtime note and continue watching |
| `checkpoint_required` | 90 minutes elapsed, 30 minutes without artifact delta, repeated planning without execution, or second compaction | Require a `progress_artifact` or checkpoint summary before further continuation |
| `handoff_required` | 150 minutes elapsed, context cannot safely continue, session is interrupted, or a fresh executor is needed | Require a `handoff_artifact` before redispatch or resume |
| `manual_review_required` | completion is claimed while checkpoint/handoff requirements are unmet, evidence is stale, or risk signals contradict the claim | Move through explicit review policy before acceptance |

The exact numbers are starting defaults. Hosted, local, and enterprise environments may tune them by executor type, task class, and evidence policy.

## Configuration Shape

The detector should eventually support a policy object with these fields:

```json
{
  "long_session_risk": {
    "enabled": true,
    "watch_after_minutes": 45,
    "checkpoint_after_minutes": 90,
    "handoff_after_minutes": 150,
    "idle_minutes_before_checkpoint": 30,
    "max_repeated_tool_errors": 3,
    "max_context_compactions": 1,
    "require_artifact_delta_before_completion": true,
    "require_handoff_before_redispatch": true
  }
}
```

This policy belongs with execution/runtime policy, not inside `TaskEnvelope` core fields, unless later implementation proves that task-specific overrides are required.

## Checkpoint Protocol

A checkpoint is required when Proofline can still let the same session continue, but needs a durable progress state before trusting more work.

The checkpoint should create a `progress_artifact` with:

- `task_id`
- `attempt_id`
- `trace_segment_id`
- `continuity_group_id`
- current branch or workspace reference when applicable
- completed work summary
- remaining work summary
- known blockers or unresolved questions
- artifact delta since the last checkpoint
- validation commands run and their outcomes
- evidence that still needs to be collected
- timestamp and provenance

Checkpoint artifacts do not satisfy completion evidence by themselves. They make the next evaluation or manual review possible.

## Handoff Protocol

A handoff is required when the current session should stop, resume elsewhere, or transfer to a fresh executor.

The handoff should create a `handoff_artifact` with:

- source `attempt_id`
- source `trace_segment_id`
- `continuity_group_id`
- receiving executor or intended receiver when known
- current repository, branch, and working-tree status when applicable
- changed files or generated artifacts that need review
- commands already run and exact outcomes
- commands that still need to be run
- known failures, flaky tools, or environment caveats
- explicit unresolved assumptions
- whether completion has been claimed
- whether completion has been accepted by Proofline
- pointers to logs, screenshots, PRs, commits, or other durable evidence

The receiving segment must reference the handoff through `handoff_from` so operators can reconstruct what context the next executor actually saw.

## Evidence Required After Handoff

After a risk-driven handoff, Proofline should require the receiving executor to produce fresh evidence before accepting completion.

Minimum expected evidence:

- a new execution segment or attempt record that references the handoff
- a fresh artifact delta or explicit statement that no artifact delta was required
- fresh validation output after the handoff, not only pre-handoff claims
- reconciliation against current GitHub/Linear facts when relevant
- manual review decision if the risk state was `manual_review_required`

Pre-handoff success claims are advisory context. They do not become accepted completion merely because the next executor received them.

## Lifecycle Behavior

Long-session risk should affect continuation and review routing, not silently rewrite lifecycle state.

Recommended behavior:

- `watch`: add a runtime warning event; do not change task lifecycle by itself
- `checkpoint_required`: block further automated continuation until a checkpoint artifact exists
- `handoff_required`: block redispatch/resume until a handoff artifact exists
- `manual_review_required`: route through the explicit sticky manual-review gate

If a completion claim arrives while required checkpoint or handoff evidence is missing, evaluation should treat the claim as insufficient or review-required, depending on policy and task risk.

## Implementation Touchpoints

Likely future implementation should be split into small changes:

1. Runtime policy contract
   - add a long-session risk policy object outside `TaskEnvelope` core
   - define default thresholds and environment/config override behavior

2. Execution event projection
   - derive elapsed time, idle time, repeated tool errors, artifact deltas, and validation freshness from existing execution events and artifacts
   - emit advisory `long_session_risk_detected` events or equivalent timeline entries

3. Artifact enforcement
   - validate required `progress_artifact` and `handoff_artifact` metadata when risk state requires them
   - ensure checkpoint/handoff artifacts remain non-completion evidence by default

4. Evaluation integration
   - make completion claims review-required or insufficient when required checkpoint/handoff evidence is missing
   - keep manual review sticky until explicit review resolution

5. Read-model/dashboard projection
   - expose risk state, required next evidence, and latest checkpoint/handoff summary through read-only inspection surfaces
   - do not add mutation controls in the dashboard

## Out Of Scope

- turning Proofline into a session manager
- suppressing executor narration as a substitute for checkpoints
- using model self-assessment as the risk detector
- accepting completion because a handoff summary sounds confident
- live redispatch policy or executor spawning in this design slice

## Related Documents

- [Runtime Execution Contract](runtime-execution-contract.md)
- [Trace Continuity Model](trace-continuity.md)
- [Artifact And Completion Evidence](artifact-and-completion-evidence.md)
- [Operator And Manual Review](operator-and-manual-review.md)
- [Execution Budget Model](execution-budget-model.md)
