# Title

Define failure diagnosis contract and taxonomy

## Problem Statement

Future HEE outputs need a stable, reviewable diagnosis shape so recurring failures can be described consistently and tied back to real evidence.

## Scope

- define a diagnosis contract
- define the initial taxonomy shape for recurring failure modes
- define provenance and confidence expectations

## Non-Goals

- implementing diagnosis generation
- backfilling historical diagnoses
- choosing a final machine-learning approach

## Acceptance Criteria

- failure diagnosis contract exists
- diagnosis records distinguish observed facts from inferred causes
- taxonomy design is explicit enough for future implementation work

## Dependencies

- Define Harness Evolution Engine architecture and boundaries
- Define execution trace requirements for future HEE analysis

## Suggested Labels

- `planning`
- `contracts`
- `hee`
