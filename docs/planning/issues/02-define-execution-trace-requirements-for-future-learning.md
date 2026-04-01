# Title

Define execution trace requirements for future HEE analysis

## Problem Statement

HEE can only diagnose recurring failures if Harness preserves the right execution-trace facts, attempt boundaries, and provenance. Those requirements need to be defined before any future learning work starts.

## Scope

- define the minimum execution-trace fields HEE will need
- distinguish execution facts from correctness or completion truth
- define how traces relate to attempts, artifacts, evaluations, and timelines

## Non-Goals

- implementing trace storage
- adding new runtime logging libraries
- building analytics or model pipelines

## Acceptance Criteria

- a trace-requirements note or contract exists
- attempt-scoped versus task-scoped expectations are explicit
- trace requirements preserve the rule that verification still owns trusted completion

## Dependencies

- Define Harness Evolution Engine architecture and boundaries

## Suggested Labels

- `planning`
- `architecture`
- `hee`
- `observability`
