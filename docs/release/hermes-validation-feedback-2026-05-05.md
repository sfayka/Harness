# Hermes Validation Feedback - 2026-05-05

This note records external validation feedback from a Hermes agent with Linear and GitHub access.

## Scope

- Repository: `/Users/ssbob/Documents/Developer/Knox_Analytics/Harness`
- Hermes starting commit: `362cdc3` (`Honor runtime secrets in live smoke preflight`)
- Current `main` after follow-up fixes: `ec6f7b0` (`Clarify armed live preflight gate`)
- Live mutation performed: no
- Live artifacts created: none

## Hermes Results

Hermes reported the synthetic/local ladder passing:

- Command: `python3 scripts/proofline_validate.py`
- Result: pass
- Backend suite: `923 tests`, `17 skipped`, `0 failures`
- Frontend tests: `23 tests`, `0 failures`
- Frontend lint: pass
- Frontend build: pass
- Synthetic execution-substrate dry runs: pass
- Reset success dry run: `verified_done`
- Reset review dry run: `needs_review`

Hermes reported coverage passing:

- Command: `PYTHONPATH=.tmp/proofline-dev-python python3 -m coverage run -m unittest discover -s tests`
- Command: `PYTHONPATH=.tmp/proofline-dev-python python3 -m coverage report -m`
- Backend suite under coverage: `923 tests`, `17 skipped`, `0 failures`
- Total coverage: `81%`

Hermes reported live preflight as `not_ready` because `HARNESS_RUN_LIVE_RESET_TESTS=1` was not set.

Important preflight checks in the Hermes context:

- `target_guard`: pass
- `linear_credential`: pass
- `github_credential`: pass
- `github_cli_auth`: pass
- `github_cli_token`: pass
- `github_repo_readonly`: pass

Hermes correctly did not run:

```bash
HARNESS_RUN_LIVE_RESET_TESTS=1 python3 -m unittest tests.test_reset_live_smoke -v
```

No Linear issues, GitHub branches, commits, or pull requests were created.

## Finding

Hermes identified a procedure mismatch in the live-smoke handoff:

- The handoff told Hermes to run the final preflight without `HARNESS_RUN_LIVE_RESET_TESTS=1`.
- The preflight intentionally cannot report `ready` unless that flag is present.
- The written procedure therefore blocked live smoke even when credentials and target checks passed.

This was a documentation bug, not a preflight bug. The live mutation flag is the explicit operator arm for a run that creates throwaway external artifacts, so missing it should keep preflight out of `ready`.

## Fix

Commit `ec6f7b0` updates the handoff and validation docs to require an armed final preflight:

```bash
HARNESS_RUN_LIVE_RESET_TESTS=1 python3 scripts/proofline_live_preflight.py --json
```

That command is still read-only. It only proves the operator has intentionally armed the live mutation gate. The mutation smoke remains a separate command:

```bash
HARNESS_RUN_LIVE_RESET_TESTS=1 python3 -m unittest tests.test_reset_live_smoke -v
```

## Current Status

Synthetic/local validation is covered and passing.

Read-only Linear/GitHub validation is covered through the documented preflight and connector checks.

The remaining incomplete validation is the live mutation smoke on latest `main`. It should be run only from a context with valid Linear/GitHub credentials, after the armed preflight reports `ready`, and only against:

- Linear project: `HARNESS-DRYRUN`
- GitHub repository: `sfayka/HARNESS-DRYRUN`
- Base branch: `main`
