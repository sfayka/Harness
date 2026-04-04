# KNO-174 proof: governed `missing_pr_after_execution` failure path (safe escalation)

This bundle records the **governed failure path** for `missing_pr_after_execution`.

It proves that Harness does not silently accept completion when execution finished but no PR artifact was attached and automated recovery could not safely finish because of an external GitHub limitation.

## Run summary

- Linear issue: `KNO-174`
- Failure class: `missing_pr_after_execution`
- Initial condition: completion claimed without a PR artifact
- Lifecycle transition: `executing` or `assigned` completion claim moved the task into `reconciling`
- Recovery result: blocked by an external GitHub limitation
- Final task state: `in_review`
- Operator intervention required to resolve: **YES**

## What this proof establishes

1. Harness distinguishes execution from completion.
2. A missing PR after execution is treated as a recoverable defect, not as implicit success.
3. Harness spends automation before operator attention by attempting bounded reconciliation first.
4. When recovery is blocked, Harness escalates explicitly to `in_review`.
5. The failed attempt is preserved as structured reconciliation evidence under `task.reconciliation`.

## Governed flow proved

1. A task completed execution and reported success without a PR artifact.
2. Harness classified the defect as `missing_pr_after_execution`.
3. Harness transitioned the task into `reconciling`.
4. The reconciliation handler ran its bounded recovery checks and encountered an external GitHub limitation.
5. Harness recorded the failure details under `task.reconciliation`.
6. Harness moved the task to `in_review` instead of silently completing it.

## Claim boundary

KNO-174 proves safe escalation under blocked recovery for this specific reconciliation class.

It does not prove that all reconciliation failures can be repaired automatically, and it does not claim a completed outcome when the external recovery path is blocked.
