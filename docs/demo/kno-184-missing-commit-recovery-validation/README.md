# KNO-184 Validation Proof: Missing-Commit Recovery on Governed Reconciliation

## Scope

This proof validates the current `main` branch behavior for the boundary where a completion claim is missing commit SHA.

Validation target:

1. Missing commit SHA + trustworthy repo/branch can recover commit SHA from branch head.
2. Missing commit SHA + trustworthy repo/branch but unresolved branch head fails terminally instead of pretending success.
3. Missing commit SHA + weak execution identity remains blocked from acceptance and fails with a terminal contract violation.

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
- Expected: no `invalid_execution_attempt`; reconciliation resolves commit from branch head, attaches the recovered commit artifact, and keeps the task blocked until PR proof is also reconciled.
- Actual: claim action is `transition_applied`; reconciliation attempt is `resolved`; `details.commit_sha` is populated from branch-head recovery path; task status remains `blocked`.
- Result: **matched expectation**.

Evidence:

- `scenario-a-completion-claim-request.json`
- `scenario-a-completion-claim-response.json`
- `scenario-a-read-model-final.json`
- `scenario-a-timeline-final.json`

### Scenario B — Missing commit SHA cannot be resolved from branch head

- Construction: same as Scenario A, but gateway branch-head lookup returns `null`.
- Expected: no `invalid_execution_attempt`; recovery is attempted and fails; reconciliation ends in a terminal failure instead of leaving ambiguous success.
- Actual: claim action is `reconciliation_terminal_failed`; task is `failed`; reconciliation details record unresolved branch-head commit and explicit error.
- Result: **matched expectation**.

Evidence:

- `scenario-b-completion-claim-request.json`
- `scenario-b-completion-claim-response.json`
- `scenario-b-read-model-final.json`
- `scenario-b-timeline-final.json`

### Scenario C — Missing commit SHA with untrustworthy repo/branch identity

- Construction: an executing task without trusted repo/branch evidence receives a successful claim attempt that includes no repo/branch/commit execution identity.
- Expected: acceptance remains blocked; commit recovery must not backdoor through weak identity.
- Actual: action is `contract_violation_failed`; the failure classification records a terminal contract violation due to missing branch identity for the current run.
- Result: **matched expectation**.

Evidence:

- `scenario-c-completion-claim-request.json`
- `scenario-c-completion-claim-response.json`
- `scenario-c-read-model-final.json`
- `scenario-c-timeline-final.json`

## Overall conclusion

`validated`

All three scenarios matched expected behavior, including governed commit recovery only when repository and branch identity are trustworthy and honest terminal failure when recovery or attribution is insufficient.

## Completion artifact status

This proof run produced repository documentation and machine-generated local validation artifacts.

BLOCKED: no task-specific external artifacts created
