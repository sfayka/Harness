# Proofline Completion Audit - 2026-05-05

This audit maps the active autonomous objective to concrete repo artifacts and validation evidence.

## Objective

Make Proofline complete and usable for Sean:

- ensure features and functions work
- strengthen synthetic-data testing
- keep tests passing with broad coverage
- ensure there is a concrete test plan for real Linear/GitHub validation
- use live Linear/GitHub only where available and safe

## Current Head

- Branch: `main`
- Remote state: `main...origin/main`
- Latest commit at audit time: `8a8d6f3` (`Record Hermes validation feedback`)
- Tracked worktree state: clean
- Remaining untracked files: local runtime artifacts and duplicate local files only

## Prompt-To-Artifact Checklist

| Requirement | Artifact or command | Evidence | Status |
| --- | --- | --- | --- |
| Proofline has a repo-owned synthetic/local validation command | `scripts/proofline_validate.py` | `python3 scripts/proofline_validate.py --list` includes backend suite, execution-substrate dry runs, reset dry runs, frontend tests, lint, and build | Done |
| Synthetic validation excludes live Linear/GitHub mutation | `scripts/proofline_validate.py` | Script footer says live mutation remains gated; tests assert `tests.test_reset_live_smoke` is not in the default plan | Done |
| Synthetic/local validation passed externally | `docs/release/hermes-validation-feedback-2026-05-05.md` | Hermes reported `python3 scripts/proofline_validate.py` passing with backend, synthetic dry runs, frontend tests, lint, and build | Done |
| Backend tests pass | `python3 -m unittest discover -s tests` | Latest recorded runs: `923 tests`, `17 skipped`, passing | Done |
| Frontend tests/lint/build pass | `pnpm test:frontend`, `pnpm lint`, `pnpm build` | Hermes validation reported 23 frontend tests passing, lint passing, and build passing | Done |
| Coverage is measurable and broad | `.coveragerc`, `requirements-dev.txt`, `scripts/proofline_validate.py --coverage` | Hermes reported coverage run passing with `923 tests`, `17 skipped`, total coverage `81%` | Done |
| Execution substrate remains advisory | `modules.execution_substrate_dryrun` scenarios | Hermes reported event stream did not accept completion without Proofline validation; handoff kept live dispatch disabled and completion authority as Proofline | Done |
| Reset verifier synthetic success path works | `python3 -m modules.reset_dryrun success` | Hermes reported final verdict `verified_done` | Done |
| Reset verifier review path works | `python3 -m modules.reset_dryrun review` | Hermes reported final status `needs_review` | Done |
| Live validation has a concrete read-only preflight | `scripts/proofline_live_preflight.py` | Preflight checks credentials, target guard, GitHub CLI/token, repository read-only path, and reports whether live artifacts are created | Done |
| Live validation target is explicit and guarded | `scripts/proofline_live_preflight.py`, `docs/howto/test-and-validate.md` | Target guard requires Linear `HARNESS-DRYRUN`, GitHub `sfayka/HARNESS-DRYRUN`, base branch `main` | Done |
| Linear dry-run target was checked read-only | Linear connector search | `docs/release/proofline-validation-status-2026-05-05.md` records project `HARNESS-DRYRUN`, expected URL, archived `false` | Done |
| GitHub dry-run target was checked read-only | GitHub connector PR search | `docs/release/proofline-validation-status-2026-05-05.md` records PRs `#55`, `#56`, `#57` in `sfayka/HARNESS-DRYRUN` | Done |
| Hermes handoff is durable and safe | `docs/howto/hermes-live-validation.md` | Contains copyable prompt, approved targets, no-production boundary, no live Symphony dispatch, Proofline-as-authority rule | Done |
| Armed live preflight procedure is correct | `docs/howto/hermes-live-validation.md`, `docs/howto/test-and-validate.md` | Final preflight now uses `HARNESS_RUN_LIVE_RESET_TESTS=1 python3 scripts/proofline_live_preflight.py --json` and remains read-only | Done |
| Procedure mismatch found by Hermes is recorded | `docs/release/hermes-validation-feedback-2026-05-05.md` | Records the missing-flag mismatch and the fix in `ec6f7b0` | Done |
| Live mutation smoke creates no artifacts unless armed | `scripts/proofline_live_preflight.py`, `tests/test_proofline_live_preflight.py` | Preflight reports `creates_live_artifacts=false`; live mutation command remains separate and gated | Done |
| Live mutation smoke has been run on latest `main` | `HARNESS_RUN_LIVE_RESET_TESTS=1 python3 -m unittest tests.test_reset_live_smoke -v` | Not run on latest `main`; current shell lacks required Linear/GitHub credentials and preflight is `not_ready` | Blocked |

## Current Local Preflight

Unarmed read-only preflight:

```bash
python3 scripts/proofline_live_preflight.py --json
```

Result in this shell:

- `status`: `not_ready`
- `creates_live_artifacts`: `false`
- `target_guard`: pass
- Missing local credentials: GitHub token, Linear API key, usable `gh auth token`

Armed read-only preflight:

```bash
HARNESS_RUN_LIVE_RESET_TESTS=1 python3 scripts/proofline_live_preflight.py --json
```

Result in this shell:

- `status`: `not_ready`
- `creates_live_artifacts`: `false`
- `live_mutation_flag`: pass
- `target_guard`: pass
- Missing local credentials: GitHub token, Linear API key, usable `gh auth token`

## Completion Decision

The objective is not complete yet.

All synthetic/local validation, coverage, documentation, read-only target checks, and safety gates are covered. The one remaining explicit requirement is live Linear/GitHub mutation validation on latest `main`.

That validation is intentionally blocked in this shell because the required credentials are not available. It should be run only from a context where the armed preflight reports `ready` and only against:

- Linear project: `HARNESS-DRYRUN`
- GitHub repository: `sfayka/HARNESS-DRYRUN`
- Base branch: `main`

The command remains:

```bash
HARNESS_RUN_LIVE_RESET_TESTS=1 python3 -m unittest tests.test_reset_live_smoke -v
```
