# Title

Define TaskEnvelope to OpenClaw mapping specification

## Problem Statement

The future OpenClaw adapter needs a clear projection from canonical `TaskEnvelope` data into executor payloads without turning OpenClaw request shape into Harness truth.

## Scope

- define which `TaskEnvelope` fields are projected into OpenClaw requests
- define which fields remain Harness-only
- define provenance expectations for outputs, traces, and artifacts

## Non-Goals

- implementing payload builders
- implementing OpenClaw request validation
- expanding `TaskEnvelope` just to match executor ergonomics

## Acceptance Criteria

- mapping spec exists
- spec is explicit about fields that must not be treated as executor-owned truth
- provenance and artifact expectations are documented

## Dependencies

- Define canonical ExecutorAdapter contract

## Suggested Labels

- `planning`
- `contracts`
- `openclaw`
