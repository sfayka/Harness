# KNO-178 proof: non-latest claimed-attempt binding with real PR truth

This bundle proves that `missing_pr_after_execution` reconciliation stays bound to the execution attempt explicitly referenced by a completion claim, even when that attempt is **not** the latest execution attempt.

It also proves the claimed attempt resolves to a **real current-run GitHub PR artifact** in the Harness repository.

## Run identity

- Linear issue: `KNO-178`
- Repository: `sfayka/Harness`
- Task id: `kno-178-missing-pr-attempt-binding-2026-04-04-run2`
- Claimed attempt id: `kno178-attempt-claimed-1`
- Latest attempt id at claim time: `kno178-attempt-latest-2`
- Claimed-attempt branch: `codex/kno-178-claimed-attempt-run2`
- Claimed-attempt commit SHA: `02fa924e576d8f69ea44907075b8fdc0dc64e6da`
- Resolved PR URL: `https://github.com/sfayka/Harness/pull/155`
- Resolved PR state: `OPEN`
- Resolved PR base branch: `main`
- Final lifecycle state: `completed`

## Scenario executed

1. Created a task with two execution attempts already recorded in `observability.execution_metadata.execution_attempts`:
   - `kno178-attempt-claimed-1` (completed)
   - `kno178-attempt-latest-2` (failed, and newer)
2. Submitted a completion claim with explicit `completion_claim.metadata.attempt_id = kno178-attempt-claimed-1`.
3. Ensured no PR existed for the claimed branch before claim submission.
4. Triggered `POST /tasks/<task_id>/completion-claims`.
5. Observed reconciliation run (`missing_pr_after_execution`) against claimed branch/commit and create PR #155.
6. Observed reevaluation linked to the claimed attempt only; latest attempt remained unlinked.
7. Verified final task transitioned to `completed` with reconciliation status `resolved` and `last_pr_url` set to PR #155.

## Required evidence map

### Task creation + attempt inventory

- Task creation request: `create-task.json`
- Task creation response: `create-response.json`
- Pre-claim read-model snapshot: `read-model-before-claim.json`
- Pre-claim timeline snapshot: `timeline-before-claim.json`

### Completion claim + explicit attempt binding

- Completion-claim request (explicit `metadata.attempt_id`): `completion-claim-request.json`
- Completion-claim response (reconciliation + reevaluation): `completion-claim-response.json`

### Reconciliation + reevaluation proof

- Post-claim read-model snapshot: `read-model-after-reconciliation.json`
- Post-claim timeline snapshot: `timeline-after-reconciliation.json`
- Final canonical task snapshot: `final-task.json`
- Final artifact/lifecycle extraction: `final-artifact-state.json`

### GitHub PR truth for claimed attempt

- PR list before claim for claimed branch (empty): `github-prs-before.json`
- PR list after reconciliation for claimed branch (contains PR #155): `github-pr-after.json`

## Key proof points

- Claimed attempt is not latest: claim references `kno178-attempt-claimed-1` while latest recorded attempt is `kno178-attempt-latest-2`.
- Reconciliation used claimed branch and commit (`codex/kno-178-claimed-attempt-run2` / `02fa924e...`), not latest-attempt branch.
- Reconciliation result includes `created_pull_request: true` and `pull_request_lookup.source: "created"`.
- Resolved PR is real in GitHub (`https://github.com/sfayka/Harness/pull/155`) with:
  - head branch `codex/kno-178-claimed-attempt-run2`
  - base branch `main`
  - state `OPEN`
  - head SHA `02fa924e576d8f69ea44907075b8fdc0dc64e6da`
- Reevaluation linkage was written only on the claimed attempt (`kno178-attempt-claimed-1`), while latest attempt reevaluation remained empty.
- Final state is `completed`; reconciliation is `resolved`; no latest-attempt drift observed.

## Skeptical notes

- A first run against hosted backend failed due GitHub REST rate limiting from hosted IP and is intentionally not treated as successful proof.
- This proof bundle only treats run2 as valid because it demonstrates both attempt binding and real PR truth on the same claimed non-latest attempt.
