# KNO-182 proof: run-linked `missing_pr_after_execution` validation

This proof bundle validates the `missing_pr_after_execution` run-linkage hardening behavior from merged PR #161 on the current branch.

## Validation method

- Environment: local Harness Codex Cloud repo environment.
- Execution mode: controlled delegated-task-style workflow using `HarnessApiService.submit_completion_claim(...)` with a fake GitHub gateway to construct explicit candidate-linkage conditions.
- Why controlled: this run does not create hosted GitHub PRs for the underlying scenario; candidate relationships are intentionally synthesized so weak-vs-strong linkage can be deterministically verified.

## Scenario A — weak task-linked / stale candidate

Construction:
- Existing PR candidate was discoverable via commit association, but PR body lacked current-run linkage markers.

Expectation:
- Candidate should be rejected for current-run proof and reconciliation should create a new PR artifact.

Observed:
- Candidate rejected with `run_linkage_missing`.
- Reconciliation final decision `created_new`.
- New PR creation path invoked (`create_calls = 1`).

Artifacts:
- `scenario-a/completion-claim-request.json`
- `scenario-a/completion-claim-response.json`
- `scenario-a/read-model.json`
- `scenario-a/timeline.json`
- `scenario-a/notes.md`

## Scenario B — strong run-linked candidate

Construction:
- Existing PR candidate was discoverable via commit association and PR body included current-run markers for task, attempt, claim, branch, commit.

Expectation:
- Candidate should be accepted as valid current-run proof without creating a new PR.

Observed:
- Candidate accepted.
- Validation matched by `commit_association_match`, `task_linkage`, `attempt_linkage`, `completion_claim_linkage`.
- No new PR creation (`create_calls = 0`).

Artifacts:
- `scenario-b/completion-claim-request.json`
- `scenario-b/completion-claim-response.json`
- `scenario-b/read-model.json`
- `scenario-b/timeline.json`
- `scenario-b/notes.md`

## Conclusion

`validated`

Both required boundaries were demonstrated in this run:
- weak linkage rejected for current run,
- strong current-run linkage accepted.

## External-artifact status

This proof run generated repository documentation and local execution evidence only for the validation scenarios.
It did **not** create task-scoped hosted execution artifacts for the simulated scenario itself.
