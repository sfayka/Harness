# Title

Define canonical ExecutorAdapter contract

## Problem Statement

Harness needs a generic executor-adapter contract before any specific OpenClaw execution work starts, otherwise executor behavior will leak into control-plane semantics.

## Scope

- define the generic executor-adapter boundary
- define canonical inputs and outputs at the adapter layer
- define how completion claims return to Harness verification

## Non-Goals

- implementing OpenClaw execution
- adding dispatch wiring
- choosing the final runtime transport

## Acceptance Criteria

- executor-adapter contract exists
- contract keeps completion claims advisory-only
- contract is framed as replaceable, not OpenClaw-exclusive

## Dependencies

- none

## Suggested Labels

- `planning`
- `contracts`
- `executors`
- `openclaw`
