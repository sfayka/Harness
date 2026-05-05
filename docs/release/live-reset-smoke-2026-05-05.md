# Live Reset Smoke - 2026-05-05

This note records the Hermes-run live Linear/GitHub mutation smoke on the approved dry-run targets.

## Scope

- Repository: `/Users/ssbob/Documents/Developer/Knox_Analytics/Harness`
- Commit tested: `a6426a0` (`Add Proofline completion audit`)
- Linear project: `HARNESS-DRYRUN`
- GitHub repository: `sfayka/HARNESS-DRYRUN`
- Base branch: `main`
- Live Symphony dispatch: not used

## Synthetic Validation

Command:

```bash
python3 scripts/proofline_validate.py
```

Result: passing.

- Backend suite: `923 tests`, `17 skipped`, `0 failures`
- Frontend tests: `23 tests`, `0 failures`
- Frontend lint: pass
- Frontend build: pass
- Execution-substrate event stream: no completion accepted; status remains pending/intake-ready
- Intent consumer: executor completion claim blocked for insufficient evidence; repair intent produced
- Handoff: live dispatch disabled; completion authority remains `harness_verification`
- Reset success dry run: `verified_done`; final Harness status `verified`
- Reset review dry run: escalated to `needs_review`; final Linear state `In Review`

## Coverage

Commands:

```bash
PYTHONPATH=.tmp/proofline-dev-python python3 -m coverage run -m unittest discover -s tests
PYTHONPATH=.tmp/proofline-dev-python python3 -m coverage report -m
```

Result: passing.

- Backend suite under coverage: `923 tests`, `17 skipped`, `0 failures`
- Total coverage: `81%`

## Armed Preflight

Command:

```bash
HARNESS_RUN_LIVE_RESET_TESTS=1 python3 scripts/proofline_live_preflight.py --json
```

Result: `ready`.

Passing checks:

- `live_mutation_flag`
- `target_guard`
- `linear_credential`
- `github_credential`
- `github_cli_auth`
- `github_cli_token`
- `github_repo_readonly`

Approved targets confirmed:

- Linear project: `HARNESS-DRYRUN`
- GitHub repository: `sfayka/HARNESS-DRYRUN`
- Base branch: `main`

## Live Smoke

Command:

```bash
HARNESS_RUN_LIVE_RESET_TESTS=1 python3 -m unittest tests.test_reset_live_smoke -v
```

Result: passing.

- Tests: `1 live smoke test`
- Failures: `0`

## Created Live Artifacts

| Scenario | Linear | Linear final state | GitHub PR | Branch | Commit/proof | Proofline verdict | Final Harness status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Happy path | [`KNO-241`](https://linear.app/knoxanalytics/issue/KNO-241/harness-live-smoke-happy-path-20260505t133525z) | `Done` | [`PR #58`](https://github.com/sfayka/HARNESS-DRYRUN/pull/58) | `codex/live-reset-happy-path-20260505t133525z` | `71a2116858eb7b84c45947322bf93365fbb876bf` | `verified_done` | `verified` |
| Missing PR proof | [`KNO-242`](https://linear.app/knoxanalytics/issue/KNO-242/harness-live-smoke-missing-pull-request-20260505t133534z) | `In Progress` | [`PR #59`](https://github.com/sfayka/HARNESS-DRYRUN/pull/59) | `codex/live-reset-missing-pr-20260505t133535z` | Actual commit `542a0be706b92a347bd16d4ab6560751427ecb9b`; claimed PR `https://github.com/sfayka/HARNESS-DRYRUN/pull/900059` | `retryable_invalid_proof` | `retrying` |
| Wrong SHA review | [`KNO-243`](https://linear.app/knoxanalytics/issue/KNO-243/harness-live-smoke-wrong-sha-review-20260505t133542z) | `In Review` | [`PR #60`](https://github.com/sfayka/HARNESS-DRYRUN/pull/60) | `codex/live-reset-wrong-sha-review-20260505t133542z` | Actual commit `a5fa3cfece1bc123099ed6b87570a77029d0550d`; claimed SHA `a5fa3cfece1bc123099ed6b87570a77029d05500` | Initial `retryable_invalid_proof`; final `needs_review` | `needs_review` |

Additional negative-path proof:

- Missing PR proof path requested repair.
- Missing PR reason: pull request does not exist in the expected repository.
- Wrong SHA review path requested repair.
- Wrong SHA reason: commit SHA does not exist in the expected repository.

## Cleanup

No cleanup was performed. The smoke intentionally left throwaway Linear issues, GitHub branches, commits, and PRs visible in the approved dry-run targets as external proof.

## Conclusion

The live mutation smoke passed on the approved Linear/GitHub dry-run targets. Completion claims were accepted only when proof matched, retryable proof failures requested repair, and exhausted invalid proof escalated to explicit review instead of being accepted as done.
