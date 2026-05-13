# Integration Proof Evidence

## Status

Recommended v1.5 design slice.

Proofline should support integration-proof evidence as a normalized evidence lane, but it should not become an API simulator, mock server, webhook gateway, retry engine, or trace platform.

## Problem

Agentic work often fails at integration boundaries even when code exists and local tests pass.

Common failure modes include:

- a mock server accepts behavior that a real API rejects
- webhook delivery is not captured or correlated to the task
- retries hide partial failure or duplicate side effects
- async jobs finish after an executor has already claimed completion
- external system state changes are visible only in scattered logs or dashboards
- screenshots and raw logs are not enough to explain whether the integration proof is complete

Proofline needs a way to represent this proof without owning the external simulator or runtime.

## Product Boundary

Proofline accepts, normalizes, evaluates, and audits integration proof.

Proofline does not:

- simulate third-party APIs
- host mock servers as a product surface
- execute webhook delivery
- own retry orchestration
- replace CI, test harnesses, traces, or replay tools
- treat an integration tool's pass/fail flag as completion truth by itself

External systems such as Fetchsandbox, CI, application traces, webhook logs, or replay tools can produce evidence. Proofline decides whether that evidence satisfies the task's completion policy.

## Fit In Existing Evidence Model

The current artifact model can represent integration proof through `log`, `output`, and `external_refs`, but that is too generic for useful evaluation. Integration proof should be modeled as structured metadata on artifacts first, not as a new top-level execution subsystem.

The smallest compatible path is:

- keep existing canonical artifact types
- allow integration-proof subtypes in `metadata.integration_proof`
- make provenance, timestamps, correlation IDs, terminal states, and redaction status explicit
- only promote new top-level artifact types after multiple subtypes prove stable

This keeps `TaskEnvelope` stable while giving evaluation code a structured evidence target.

## Integration Proof Subtypes

Initial subtypes should include:

- `api_receipt`: request/response receipt from a real or replayed API interaction
- `webhook_receipt`: webhook delivery, receipt, and handler correlation proof
- `retry_trace`: retry attempts, budget outcome, and final disposition
- `async_job_state`: async job ID, polling or callback evidence, and terminal state
- `external_state_snapshot`: before/after state from an external system
- `sandbox_replay_result`: replay or sandbox result from a specialized integration tool
- `failure_classification`: structured classification of deterministic, transient, pending, or unknown external state

These are proof subtypes, not product modules.

## Required Metadata

Every integration-proof artifact should carry:

- `subtype`
- `correlation_id` when available
- `captured_at`
- `source_system`
- `environment`: `local`, `preview`, `staging`, `production`, `sandbox`, or `unknown`
- `redaction_status`: `redacted`, `not_required`, or `unsafe_unredacted`
- `terminal_state`: `passed`, `failed`, `pending`, `inconclusive`, or `not_applicable`
- `summary`
- `external_refs`

Subtype-specific metadata should stay inside the `metadata.integration_proof.details` object.

## Lifecycle Effects

Integration proof affects lifecycle through ordinary evidence and reconciliation rules:

- `passed` can support acceptance only when the task policy requires or allows that proof.
- `failed` should block or fail acceptance depending on whether the failure is recoverable.
- `pending` should prevent terminal completion when the task depends on the async outcome.
- `inconclusive` should require more evidence or manual review.
- `unsafe_unredacted` should block persistence or require redaction before evaluation.

Async proof must be especially strict. A task should not become accepted while required async proof is still pending just because an executor has claimed success.

## Redaction And Secret Safety

Redaction belongs at ingestion and provenance capture time.

Proofline should persist summaries, digests, correlation IDs, and safe excerpts rather than raw secrets or full payloads. If a provider cannot prove that sensitive payloads were redacted, the artifact should be treated as unsafe until a safe representation is available.

Minimum rules:

- do not persist authorization headers, tokens, session cookies, private keys, or raw credentials
- keep raw payload retention optional and off by default
- record whether redaction was performed by the source tool, adapter, or Proofline
- prefer digests and external references for large or sensitive traces

## Schema And API Implications

No immediate `TaskEnvelope` core change is required.

Recommended next implementation step:

- document and validate `metadata.integration_proof` for artifacts
- add fixture examples for accepted, failed, pending, and inconclusive proof
- project integration-proof summaries into read-model/timeline surfaces
- make evaluation treat required pending integration proof as not acceptable

Only after that should Proofline consider new artifact types such as `api_receipt` or `webhook_receipt`.

## Smallest Useful Slice

Create an issue-sized implementation slice that adds:

1. sample `metadata.integration_proof` fixtures
2. a validation helper for integration-proof metadata shape
3. read-model summary projection for integration proof
4. evaluation behavior for required async proof where `terminal_state=pending`

This slice proves the acceptance-layer value without building a simulator.

## Open Questions

- Should integration proof be required only by explicit task evidence policy, or inferred from task metadata?
- Which external source should be used for the first real fixture: CI logs, webhook logs, or a replay/sandbox tool?
- Should unsafe redaction fail ingestion or persist an informational rejected artifact?
