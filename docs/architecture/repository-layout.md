# Repository Layout Proposal

## Objective

Propose a repository layout that mirrors the architecture boundaries and gives reliability, verification, and system-of-record enforcement first-class homes.

## Proposed Layout

```text
docs/
  architecture/
  adrs/
  planning/

modules/
  contracts/
  intake/
  planning/
  dispatch/
  verification/
  integrations/
    openclaw/
    linear/
    github/
    executors/
      codex/
  substrate/

tests/
  contracts/
  intake/
  verification/
  integrations/
  substrate/
```

## Layout Rationale

### docs/

Architecture, ADRs, and planning artifacts stay visible and versioned next to code.

### modules/

Owns control-plane behavior only.

Suggested ownership slices:

- `contracts/` for canonical task and evidence contracts
- `intake/` for normalization after ingress validation
- `planning/` for decomposition and dependency generation
- `dispatch/` for routing and reassignment policy
- `verification/` for evidence checks and completion enforcement

### modules/integrations/

Contains boundary adapters to external systems.

- `openclaw/` for ingress-facing contracts
- `linear/` for structured work synchronization
- `github/` for artifact evidence synchronization
- `executors/` for worker-specific transport layers

### modules/substrate/

Contains the workflow runtime adapter and substrate-facing abstractions.

This directory should hide substrate implementation details behind stable interfaces used by the control-plane modules.

### tests/

Keeps contract validation, intake behavior, verification behavior, and adapter tests separate.

## Layout Rules

- do not put executor-specific behavior into `modules/planning/`, `modules/dispatch/`, or `modules/verification/`
- do not put planning or verification policy into `modules/integrations/`
- do not let substrate APIs leak through module boundaries
- keep shared contracts independent from vendor adapters
- keep artifact verification logic separate from executor integrations

## Near-Term Recommendation

Implementation should prioritize `contracts/`, `intake/`, `verification/`, and the integrations that provide structured work and artifact evidence before investing heavily in smarter planning or dispatch behavior.
