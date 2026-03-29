# Linear And Harness Boundary

## Purpose

Clarify how Linear and Harness fit together so Harness is positioned as complementary to Linear rather than competitive with it.

## Boundary Summary

- Linear is the AI-native work surface and system of record for structured work.
- Harness is the control plane and reliability layer underneath that work surface.

Linear is where humans and agents coordinate work.

Harness is where the system decides whether work is actually verified, reconciled, and acceptable as complete.

## System Of Record Model

- Linear is the source of truth for intended work.
- GitHub is the source of truth for executed artifacts.
- Harness is the source of truth for verified state and lifecycle correctness.

## Linear Owns

- issue, project, and workflow coordination
- human and agent visibility into work state
- upstream work capture
- collaboration around task planning and progress
- structured-work records that represent what should be happening

## Harness Owns

- canonical control-plane contracts such as `TaskEnvelope`
- artifact-backed completion enforcement
- reconciliation between Harness state, GitHub facts, and Linear facts
- auditable lifecycle and state-transition enforcement
- verification and manual-review policy
- decisions about whether completion should be accepted, blocked, reversed, or escalated

## Questions Each System Answers

### Linear Answers

- what work exists?
- how is that work organized?
- which issue, project, or workflow does it belong to?
- what do humans and agents currently believe is happening?

### Harness Answers

- did the work actually happen?
- is completion supported by evidence?
- do GitHub, Linear, and Harness agree?
- should completion be accepted, blocked, reversed, failed, or sent to manual review?

## Interaction Model

1. Work is initiated through an ingress surface such as OpenClaw or directly inside a work surface such as Linear.
2. Linear remains the visible system of record for work coordination.
3. Harness consumes relevant task state and normalizes it into canonical control-plane contracts.
4. Harness delegates execution to workers and gathers execution evidence.
5. Harness reconciles its own state against GitHub and Linear.
6. Harness reports verified outcomes back so Linear reflects trusted state rather than unverified claims.

## Contract Boundary

### Linear -> Harness

Linear sends:

- `issue_id`
- `title`
- `description`
- `labels` and `priority` when present
- linked artifacts when present

### Harness Derives

Harness derives:

- canonical `TaskEnvelope`
- required artifacts
- verification expectations
- reconciliation expectations against GitHub and Linear state

### Harness -> Linear

Harness returns:

- control-plane outcome: `completed`, `blocked`, `failed`, or `review_required`
- evidence validation result
- reconciliation result
- required follow-up actions

## Linear Facts Contract

When Harness receives normalized `linear_facts` through the public API:

- `record_found=false` means the Linear record is unresolved, and `workflow` must be `null` or omitted
- `record_found=true` means the record is resolved, and `workflow` must be an object containing:
  - `workflow_id`
  - `workflow_name`

This keeps review-required cases explicit: unresolved Linear identity is represented with `record_found=false`, not with a partially populated workflow object.

## Example: Feature Implementation Task

1. A Linear issue is created for a feature implementation task.
2. An executor such as Codex performs the work.
3. A pull request is opened in GitHub.
4. Linear is marked done by a human or agent.
5. Harness evaluates the completion claim:
   - verifies the pull request exists
   - checks repository and branch correctness
   - validates artifact completeness
6. Harness returns a control-plane decision:
   - `accepted_completion` when the evidence and external facts align
   - `blocked` when required evidence is missing or incomplete
   - `external_mismatch` when GitHub, Linear, and Harness facts do not agree

## Boundary Note

`review_required` should be understood as a control-plane outcome returned to Linear.

It does not require Linear and Harness to share the same internal lifecycle enum. Harness may still keep the underlying task in a blocked state until review is resolved.

## Non-Goals

Harness should not become:

- a replacement for Linear's issue/project coordination UX
- a generic agent coordination product
- a competing planning surface for work management
- a substitute for human and agent collaboration already happening in Linear

## Product Implication

The moat for Harness is not better work coordination UX.

The moat is reliable completion enforcement beneath AI-driven work:

- evidence-backed completion
- reconciliation across systems
- auditable state transitions
- explicit blocked, failed, completed, and review-required outcomes
