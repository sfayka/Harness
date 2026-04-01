# Title

Define Harness Evolution Engine architecture and boundaries

## Problem Statement

Harness needs a clear planning-stage architecture for future evolution work so failure diagnosis and proposal generation do not drift into hidden runtime mutation or vague "self-improvement" language.

## Scope

- define HEE purpose, responsibilities, and non-responsibilities
- define how HEE relates to `TaskEnvelope`, evaluation history, timelines, execution traces, artifacts, and review decisions
- define advisory-only boundaries and review expectations

## Non-Goals

- implementing learning logic
- implementing model selection or training
- implementing automated code changes, PR generation, or deployment

## Acceptance Criteria

- architecture doc exists and is reviewed
- boundary language makes HEE advisory-only
- doc explicitly states that Harness lifecycle truth remains outside HEE

## Dependencies

- none

## Suggested Labels

- `planning`
- `architecture`
- `hee`
