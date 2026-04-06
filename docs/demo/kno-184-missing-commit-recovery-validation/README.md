# KNO-184 Validation Proof: Missing-Commit Recovery on Governed Reconciliation

## Scope

This proof validates the `main` branch behavior merged from PR #166 for the specific boundary where a completion claim is missing commit SHA.

Validation target:

1. Missing commit SHA + trustworthy repo/branch can recover commit SHA from branch head.
2. Missing commit SHA + trustworthy repo/branch but unresolved branch head escalates safely.
3. Missing commit SHA + weak execution identity remains blocked by `invalid_execution_attempt`.

## Execution mode

- Mode: `local-controlled`
- Hosted proof: `not performed`
- Generator: `PYTHONPATH=. python docs/demo/kno-184-missing-commit-recovery-validation/generate_proof_bundle.py`

## Artifacts in this bundle

- Scenario A request/response/read-model/timeline snapshots
- Scenario B request/response/read-model/timeline snapshots
- Scenario C request/response/read-model/timeline snapshots
- Machine-readable summary: `summary.json`

## Scenario results

### Scenario A — Missing commit SHA recoverable from trusted branch head

- Construction: a branch-only reconciliation-eligible task is submitted with commit context removed from the claim, while gateway branch-head lookup returns a SHA.
- Expected: no `invalid_execution_attempt`; reconciliation resolves commit from branch head and proceeds normally.
- Actual: claim action is `transition_applied`; reconciliation attempt is `resolved`; `details.branch_head_commit_sha` and `details.commit_sha` are both populated from branch-head recovery path.
- Result: **matched expectation**.

Evidence:

- `scenario-a-completion-claim-request.json`
- `scenario-a-completion-claim-response.json`
- `scenario-a-read-model-final.json`
- `scenario-a-timeline-final.json`

### Scenario B — Missing commit SHA cannot be resolved from branch head

- Construction: same as Scenario A, but gateway branch-head lookup returns `null`.
- Expected: no `invalid_execution_attempt`; recovery is attempted and fails; reconciliation escalates instead of pretending success.
- Actual: claim action is `reconciliation_failed`; task is `in_review`; reconciliation details record unresolved branch-head commit and explicit error.
- Result: **matched expectation**.

Evidence:

- `scenario-b-completion-claim-request.json`
- `scenario-b-completion-claim-response.json`
- `scenario-b-read-model-final.json`
- `scenario-b-timeline-final.json`

### Scenario C — Missing commit SHA with untrustworthy repo/branch identity

- Construction: an executing task without trusted repo/branch evidence receives a successful claim attempt that includes no repo/branch/commit execution identity.
- Expected: blocked by `invalid_execution_attempt`; commit recovery must not backdoor through weak identity.
- Actual: action is `invalid_execution_attempt_failed`; validation reasons explicitly include missing repository, branch, and commit identity.
- Result: **matched expectation**.

Evidence:

- `scenario-c-completion-claim-request.json`
- `scenario-c-completion-claim-response.json`
- `scenario-c-read-model-final.json`
- `scenario-c-timeline-final.json`

## Overall conclusion

`validated`

All three scenarios matched expected behavior, including preservation of the `invalid_execution_attempt` boundary while allowing governed branch-head commit recovery only when repository and branch identity are trustworthy.

## Completion artifact status

This proof run produced repository documentation and machine-generated local validation artifacts.

BLOCKED: no task-specific external artifacts created
