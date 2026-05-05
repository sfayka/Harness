# Proofline Validation Status - 2026-05-05

This note records the current state after adding the Hermes live-validation handoff.

## Evidence Baseline

- Validation evidence was gathered after commit `a33797b` (`Document Hermes live validation handoff`).
- Branch: `main`
- Remote: `origin/main`

## What Changed

- Added `docs/howto/hermes-live-validation.md` so Sean can hand a gated validation prompt to a Hermes agent with Linear and GitHub access.
- Linked the Hermes handoff from `docs/howto/index.md`.
- Linked the Hermes handoff from `docs/howto/test-and-validate.md`.
- Added a docs regression test in `tests/test_hosted_docs.py` to keep the handoff visible and aligned with the approved dry-run targets.

## Passing Evidence

- Docs regression test:
  - Command: `python3 -m unittest tests.test_hosted_docs -v`
  - Result: `9 tests`, passing.
- Backend suite:
  - Command: `python3 -m unittest discover -s tests`
  - Result: `923 tests`, `17 skipped`, passing.
- Whitespace check:
  - Command: `git diff --check`
  - Result: passing.
- Synthetic/local validation runner:
  - Command: `python3 scripts/proofline_validate.py`
  - Result: passing after running with local port-binding permission.
  - Scope: backend suite, execution-substrate dry runs, reset dry runs, frontend tests, lint, and build.
  - Live Linear/GitHub mutation smoke remains intentionally excluded.

## Read-Only Live Preflight

- Command: `python3 scripts/proofline_live_preflight.py --json`
- Result: `not_ready`
- Live artifacts created: none

Current blockers in this shell:

- `HARNESS_RUN_LIVE_RESET_TESTS=1` is not set.
- No `GITHUB_TOKEN` or `GH_TOKEN` is configured.
- No runtime-managed GitHub credential is visible.
- No `LINEAR_API_KEY` is configured.
- No runtime-managed Linear credential is visible.
- `gh auth status` failed.
- `gh auth token` did not return a usable token.
- GitHub repository read-only check did not pass because usable GitHub auth is unavailable in this shell.

The approved target guard passed:

- Linear project: `HARNESS-DRYRUN`
- GitHub repository: `sfayka/HARNESS-DRYRUN`
- Base branch: `main`

## Linear Read-Only Evidence

- Tool: Linear connector search.
- Query: `"HARNESS-DRYRUN"` filtered to projects.
- Result:
  - Project: `HARNESS-DRYRUN`
  - URL: `https://linear.app/knoxanalytics/project/harness-dryrun-3d7d9476cb1e`
  - Archived: `false`

## Live Mutation Status

Live mutation smoke was not run.

The gated command remains:

```bash
HARNESS_RUN_LIVE_RESET_TESTS=1 python3 -m unittest tests.test_reset_live_smoke -v
```

Only run it after the preflight reports `ready` and Sean accepts that the run will create throwaway Linear issues, GitHub branches, commits, and pull requests in the approved dry-run targets.

## Assessment

Proofline's synthetic and local validation path is healthy. The remaining validation gap is live Linear/GitHub mutation from an authenticated agent or operator context.

Hermes can now perform that validation from the documented handoff without becoming a trust authority. Hermes should report command output and artifact URLs; Proofline should remain the system that verifies whether the work is accepted.
