# Hermes Live Validation Handoff

Use this runbook when Sean wants a Hermes agent with Linear and GitHub access to validate Proofline against the approved dry-run systems.

Hermes is acting as an outside tester here. It is not a completion authority, it must not mutate production work, and it must not run live Symphony dispatch. Proofline remains the acceptance boundary.

## Approved Targets

- Repository checkout: `/Users/ssbob/Documents/Developer/Knox_Analytics/Harness`
- Linear project: `HARNESS-DRYRUN`
- GitHub repository: `sfayka/HARNESS-DRYRUN`
- Base branch: `main`

Do not use production Linear projects, production GitHub repositories, or active product branches for this validation.

## Paste This Prompt Into Hermes

```text
You are testing Proofline as an external Hermes agent with Linear and GitHub access.

Work in this repository only:
/Users/ssbob/Documents/Developer/Knox_Analytics/Harness

Hard boundaries:
- Do not touch production work.
- Only use Linear project HARNESS-DRYRUN.
- Only use GitHub repository sfayka/HARNESS-DRYRUN.
- Use base branch main.
- It is acceptable to create throwaway Linear issues, GitHub branches, commits, and PRs only when the live smoke gate below says it is ready.
- Do not run live Symphony dispatch.
- Do not treat Hermes, Codex, Symphony, or any runner completion as truth. Proofline verification is the authority.
- Do not mark Proofline complete just because tests passed; report exact evidence and remaining blockers.

Step 1: Inspect current state.

Run:
git status --short
git log -5 --oneline
python3 scripts/proofline_live_preflight.py --json

Report whether the preflight is ready. If it is not ready, stop before live mutation and report each blocker exactly.

Step 2: Run the synthetic validation ladder.

Run:
python3 scripts/proofline_validate.py

Expected result: passing backend suite, execution-substrate dry runs, reset dry runs, frontend tests, lint, and build. This command must not create live Linear or GitHub artifacts.

Step 3: Run backend coverage.

If coverage is not installed, run:
python3 -m pip install -r requirements-dev.txt --target .tmp/proofline-dev-python

Then run:
PYTHONPATH=.tmp/proofline-dev-python python3 -m coverage run -m unittest discover -s tests
PYTHONPATH=.tmp/proofline-dev-python python3 -m coverage report -m

Report the total coverage percentage and any failures.

Step 4: Re-run live preflight.

Run:
python3 scripts/proofline_live_preflight.py --json

Proceed to live mutation only if all of these are true:
- preflight status is ready
- target_guard passes
- github_credential passes
- linear_credential passes
- github_repo_readonly passes
- repository is sfayka/HARNESS-DRYRUN
- Linear project is HARNESS-DRYRUN

Step 5: Run gated live smoke only when preflight is ready.

Run:
HARNESS_RUN_LIVE_RESET_TESTS=1 python3 -m unittest tests.test_reset_live_smoke -v

Expected behavior:
- Happy path verifies completion.
- Missing pull-request proof remains retrying and requests repair.
- Wrong commit SHA after retry budget escalates to needs_review.

Record every artifact created:
- Linear issue URLs
- GitHub branch names
- GitHub commit SHAs
- GitHub PR URLs
- final Proofline verdicts
- any cleanup performed or intentionally left visible as proof

Step 6: Final report.

Return:
- repository path and current commit SHA
- synthetic validation result
- coverage result
- preflight result
- whether live smoke was run
- if live smoke ran, all Linear/GitHub artifact URLs and final Proofline verdicts
- if live smoke did not run, exact blockers
- any Proofline bugs found, with file paths or command output
```

## Interpreting Hermes Feedback

A Hermes report is useful only if it includes concrete command results and artifact identifiers. Treat broad claims like "tests passed" or "the smoke worked" as incomplete until the report names the commands, target repo, target Linear project, created artifacts, and final Proofline verdicts.

If Hermes reports `preflight status: not_ready`, do not run mutation smoke. Fix credential or target configuration first, then rerun the read-only preflight.

If Hermes reports live-smoke artifact URLs, record the successful run in `docs/release/` with the exact command, Linear issue URLs, GitHub branch/commit/PR identifiers, final verdicts, and cleanup state.
