# Executor Adapter Contract

Planning scaffold only. This contract is not executable code.

## Purpose

Define the intended boundary between Harness execution coordination and a replaceable executor adapter such as OpenClaw.

## Sketch

```text
ExecutorAdapter
  prepare_execution(task_envelope, assignment_context) -> executor_request
  start_execution(executor_request) -> execution_start_fact
  poll_or_receive_events(execution_handle) -> ExecutionEvent[]
  collect_outputs(execution_handle) -> OutputRef[]
  collect_artifacts(execution_handle) -> ArtifactRef[]
  claim_completion(execution_handle) -> CompletionClaim
```

## Required Semantics

- Input task data must come from canonical Harness state, not executor-owned truth.
- `claim_completion` is advisory and must return to Harness verification paths.
- Event outputs must be normalized into canonical execution facts.
- The contract must support replaceable executors, not only OpenClaw.
- Adapter-specific transport or auth details must stay outside the canonical contract.

## Open Questions

- whether the adapter boundary is synchronous, event-driven, or both
- how attempt and retry identifiers are assigned and preserved
- which event families are required at minimum for later diagnostics
