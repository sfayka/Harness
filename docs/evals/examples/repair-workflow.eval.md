# Repair Workflow Local Eval Example

## Eval Spec

```yaml
id: eval-reset-repair-workflow-v1
title: Reset verifier repair workflow
target_type: ingress_to_verification
target_ref: modules.reset_dryrun:success
scenario: >
  A task claims completion without acceptable pull-request proof. Harness rejects
  the claim, records a repair request, then accepts a corrected claim with real
  repository, branch, commit, and PR evidence.
fixture_refs:
  - modules.reset_dryrun:success
expected_outcomes:
  - first claim is rejected as retryable invalid proof
  - repair request is recorded
  - corrected claim is accepted as verified done
  - final Linear-facing state would be Done
must_pass_checks:
  - initial_claim_verdict == retryable_invalid_proof
  - repair_request_count >= 1
  - final_claim_verdict == verified_done
  - final_harness_status == verified
allowed_variance:
  - generated contract ids may differ
  - timestamps may differ
  - repair request transport may be local file bridge or remote callback when explicitly declared
expected_artifacts:
  - reset contract event history
  - completion claim summary
  - repair request record
expected_trace_properties:
  - invalid claim, repair request, and corrected claim are linkable in one continuity group
expected_budget_behavior:
  - retry count stays within configured retry budget
canonical_surface_refs:
  - POST /reset/contracts
  - POST /reset/contracts/<contract_id>/claims
  - GET /reset/contracts/<contract_id>
```

## Baseline Comparison

Baseline and candidate runs should compare:

- verdict sequence
- repair request count
- final Harness status
- event history completeness
- trace continuity when trace support exists
- retry budget behavior when budget support exists

## Operator Summary Shape

```text
PASS: Reset repair workflow still rejects bad proof and accepts corrected proof.

Initial claim: retryable_invalid_proof
Repair requests: 1
Final claim: verified_done
Regression categories:
- correctness: unchanged
- evidence quality: unchanged
- trace continuity: not_available
- budget behavior: not_available
```
