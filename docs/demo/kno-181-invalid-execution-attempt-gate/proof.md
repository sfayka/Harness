# KNO-181 Validation Proof: `invalid_execution_attempt` gate vs `missing_pr_after_execution`

## Scope and run context

- Repository: `sfayka/Harness`
- Validation mode: **local controlled run** using `HarnessApiService` with a deterministic in-memory/file-backed harness store.
- Hosted execution: **not used** in this run. No hosted proof is claimed.
- Goal: prove the boundary between:
  1. `invalid_execution_attempt` (no attributable current-run repository/branch/commit proof), and
  2. `missing_pr_after_execution` (real attributable run exists, PR proof still missing).

A deterministic GitHub reconciliation gateway stub was used for reproducibility. It confirms branch/commit existence but intentionally fails PR creation so Scenario B remains in the missing-PR boundary and does not mutate into a created PR artifact.

## Scenario A — Invalid execution attempt

### Construction

- Created a task with assigned code executor.
- Submitted a completion claim with a successful execution attempt that only provided an execution log artifact.
- **No repository / branch / commit current-run proof** was included.
- Set `HARNESS_INVALID_EXECUTION_RETRY_BUDGET=1` to force a bounded retry and terminal outcome for validation.

Artifacts:

- Request/response pair:
  - `scenario-a-submit-request.json`
  - `scenario-a-submit-response.json`
  - `scenario-a-completion-claim-request.json`
  - `scenario-a-completion-claim-response.json`
- Read-model snapshots:
  - `scenario-a-read-model-initial.json`
  - `scenario-a-read-model-final.json`
- Timeline snapshots:
  - `scenario-a-timeline-initial.json`
  - `scenario-a-timeline-final.json`
- Retry/audit evidence:
  - `scenario-a-evaluation-history-final.json`

### Expected

- Classified as `invalid_execution_attempt`.
- Not treated as a normal attributable run.
- Retry should occur only within policy budget.
- After budget exhaustion, task should fail.
- Read-model/timeline should expose invalid-attempt details.

### Actual

- Completion-claim response action: `invalid_execution_attempt_failed`.
- Failure classification: `invalid_execution_attempt`.
- Retry context present with `triggered_by_category=invalid_execution_attempt` and `max_retries=1`.
- Final task state: `failed`.
- Final read-model shows invalid attempt summary fields and failure type `invalid_execution_attempt`.
- Final timeline includes invalid execution attempt handling + failure transition.

✅ Scenario A matched expectations.

## Scenario B — Real attributable execution with missing PR proof

### Construction

- Created a task with assigned code executor.
- Submitted a completion claim with a successful execution attempt that includes explicit current-run code identity:
  - repository host/owner/name,
  - branch name,
  - commit SHA.
- Did **not** attach pull request artifact proof.
- Reconciliation gateway stub confirms branch/commit existence but fails PR creation intentionally.

Artifacts:

- Request/response pair:
  - `scenario-b-submit-request.json`
  - `scenario-b-submit-response.json`
  - `scenario-b-completion-claim-request.json`
  - `scenario-b-completion-claim-response.json`
- Read-model snapshots:
  - `scenario-b-read-model-initial.json`
  - `scenario-b-read-model-final.json`
- Timeline snapshots:
  - `scenario-b-timeline-initial.json`
  - `scenario-b-timeline-final.json`
- Evaluation history snapshot:
  - `scenario-b-evaluation-history-final.json`

### Expected

- Must **not** be classified as `invalid_execution_attempt`.
- Must route to missing-PR-after-attributable-run boundary.
- Read-model/timeline should show this as real attempt with missing downstream artifact proof.

### Actual

- Completion-claim response action: `reconciliation_failed`.
- Reconciliation failure type: `missing_pr_after_execution`.
- Latest execution attempt validation: `status=valid`.
- Task moved to `in_review` (manual review required after reconciliation failure).
- No `invalid_execution_attempt` response block appears.
- Timeline captures reconciliation attempt/failure events for missing PR.

✅ Scenario B matched expectations.

## Overall conclusion

**Conclusion: hole closed.**

This run demonstrates the gate now distinguishes between:

- non-attributable execution claims (`invalid_execution_attempt`, bounded retry -> failed), and
- attributable execution attempts missing PR proof (`missing_pr_after_execution`, reconciliation/manual-review flow).

Both boundaries were validated with concrete machine-readable artifacts produced by this run.

## Notes / limitations

- This is local controlled proof, not hosted proof.
- Hosted proof was not fabricated.
