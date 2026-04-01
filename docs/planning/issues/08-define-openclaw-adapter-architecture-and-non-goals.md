# Title

Define OpenClaw executor adapter architecture and non-goals

## Problem Statement

The repository already has an ingress-side OpenClaw spike. A future executor adapter needs a separate architecture definition so ingress, execution, validation, and control-plane truth do not get conflated.

## Scope

- define the purpose and boundary of the future OpenClaw executor adapter
- distinguish it from the current ingress/client spike
- document explicit non-goals and replaceability constraints

## Non-Goals

- implementing API wiring
- implementing a working OpenClaw runtime integration
- making OpenClaw the source of lifecycle truth

## Acceptance Criteria

- architecture doc exists
- ingress/client spike and executor adapter roles are clearly separated
- doc states that Harness remains the control plane and lifecycle authority

## Dependencies

- Define canonical ExecutorAdapter contract
- Define TaskEnvelope to OpenClaw mapping specification

## Suggested Labels

- `planning`
- `architecture`
- `openclaw`
