# KNO-175 proof: successful `missing_pr_after_execution` auto-reconciliation (no operator intervention)

This bundle proves the **success path** where Harness receives a completion claim that has a commit artifact but no PR artifact, runs `missing_pr_after_execution`, creates/attaches a PR automatically, and then proceeds through canonical reevaluation to a non-review final state.

## Run identity

- Linear issue: `KNO-175`
- Harness task id: `kno-175-missing-pr-success-2026-04-04-run3`
- Repository: `sfayka/Harness`
- Execution branch: `codex/kno-175-missing-pr-runtime`
- Execution commit SHA: `ee295c3e9b7802c75ecd80bccc8218ec388afee3`
- Auto-created PR URL: `https://github.com/sfayka/Harness/pull/150`
- Final task state: `completed`
- Operator intervention required: **NO**

## Canonical flow executed

1. `POST /tasks` with an `executing` task that includes a real commit artifact and **no pull_request artifact**.
2. `POST /tasks/<task_id>/completion-claims` with completion claim + execution attempt, still without PR artifact.
3. Harness transitions `execution_complete -> reconciling` and runs reconciliation handler `missing_pr_after_execution`.
4. Reconciliation validates branch + commit, attempts PR lookup, then creates PR when not found.
5. Harness attaches PR artifact and records structured reconciliation attempt under `task_envelope.reconciliation`.
6. Harness performs canonical reevaluation and transitions from `reconciling -> completed`.

## Evidence map

### Request/response artifacts

- Task creation request: `create-task.json`
- Task creation response: `create-response.json`
- Completion-claim request: `completion-claim-request.json`
- Completion-claim response (includes reconciliation + reevaluation outputs): `completion-claim-response.json`

### Canonical inspection snapshots

- Read-model before completion claim: `read-model-before-claim.json`
- Timeline before completion claim: `timeline-before-claim.json`
- Read-model after reconciliation + reevaluation: `read-model-after-reconciliation.json`
- Timeline after reconciliation + reevaluation: `timeline-after-reconciliation.json`

### Before/after PR evidence

- Before completion claim (`--head codex/kno-175-missing-pr-runtime`): `github-prs-before.json` (empty list)
- After reconciliation: `github-pr-after.json` (PR #150 present)

## Key proof points from artifacts

- Missing PR at claim time is explicit (`github-prs-before.json` is `[]`).
- Completion claim response shows reconciliation attempt details:
  - `branch_exists: true`
  - `commit_exists: true`
  - PR lookup searched branch and commit
  - `created_pull_request: true`
  - `pull_request_lookup.source: "created"`
  - `pull_request_lookup.url: "https://github.com/sfayka/Harness/pull/150"`
- PR artifact is attached post-reconciliation as `artifact-pr-150` in task artifacts.
- `reconciliation.status` is `resolved`; `last_pr_url` is set.
- Verification accepts completion after reconciliation (`accepted_completion: true`, action `transition_applied`, target `completed`).
- Final lifecycle is `completed`, not `in_review`.

## Validation performed

- All JSON artifacts were syntax-validated with `jq empty`.
- Timeline confirms operational sequence including `reconciling` transition and final completion.
- No manual review event or operator override appears in task state/timeline.

