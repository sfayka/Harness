# Repository Layout Proposal

## Objective

Propose a repository layout that mirrors the architecture boundaries without committing to runtime implementation yet.

## Proposed Layout

```text
docs/
  architecture/
  adrs/
  planning/

src/
  harness/
    intake/
    planning/
    assignment/
    reporting/
  integrations/
    openclaw/
    linear/
    executors/
      codex/
  substrate/
  contracts/

tests/
  architecture/
  integrations/
  substrate/
```

## Layout Rationale

### docs/

Architecture, ADRs, and planning artifacts stay visible and versioned next to code.

### src/harness/

Owns control-plane behavior only.

Suggested ownership slices:

- `intake/` for normalization after ingress validation
- `planning/` for decomposition and dependency generation
- `assignment/` for routing and reassignment policy
- `reporting/` for status aggregation and upstream summaries

### src/integrations/

Contains boundary adapters to external systems.

- `openclaw/` for ingress-facing contracts
- `linear/` for structured work synchronization
- `executors/` for worker-specific transport layers

### src/substrate/

Contains the workflow runtime adapter and substrate-facing abstractions.

This directory should hide substrate implementation details behind stable interfaces used by `src/harness/`.

### src/contracts/

Contains canonical payload and state definitions shared across modules.

Examples:

- request contract
- task contract
- execution event contract
- status enums

### tests/

Keeps architecture tests and adapter tests separate from control-plane tests.

## Layout Rules

- do not put executor-specific behavior into `src/harness/`
- do not put planning policy into `src/integrations/`
- do not let substrate APIs leak through module boundaries
- keep shared contracts independent from vendor adapters

## Near-Term Recommendation

Do not create the runtime directories yet unless implementation starts in those areas.

For Epic 1, the value is in agreeing on the layout and using it to guide future tickets.
