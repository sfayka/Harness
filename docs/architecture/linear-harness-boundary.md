# Linear And Harness Boundary

## Purpose

Clarify how Linear and Harness fit together so Harness is positioned as complementary to Linear rather than competitive with it.

## Boundary Summary

- Linear is the AI-native work surface and system of record for structured work.
- Harness is the control plane and reliability layer underneath that work surface.

Linear is where humans and agents coordinate work.

Harness is where the system decides whether work is actually verified, reconciled, and acceptable as complete.

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
