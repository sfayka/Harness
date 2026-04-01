# Title

Define completion interception and artifact validation boundary

## Problem Statement

A future executor adapter must not let OpenClaw completion claims bypass Harness verification, reconciliation, or manual review rules. That interception boundary needs to be specified before implementation begins.

## Scope

- define how executor completion claims re-enter Harness
- define where artifact references are attached versus validated
- define which parts of completion handling remain core Harness responsibilities

## Non-Goals

- implementing completion hooks
- implementing artifact verification logic changes
- changing lifecycle semantics

## Acceptance Criteria

- boundary doc or contract exists
- completion interception is explicit
- artifact validation responsibility remains in Harness, not in the executor adapter

## Dependencies

- Define canonical ExecutorAdapter contract
- Define TaskEnvelope to OpenClaw mapping specification

## Suggested Labels

- `planning`
- `verification`
- `openclaw`
