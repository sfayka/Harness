---
name: hermes-proofline
description: Use when Hermes is coordinating software work and needs Proofline to validate completion against user intent and evidence.
---

# Hermes Proofline Skill

Use this skill when Hermes is coordinating agentic software work where an executor saying "done" is not enough.

Proofline is not the worker. Proofline is the acceptance layer. It validates whether a completion claim matches user intent, the task contract, GitHub evidence, Linear facts, and review policy.

## When To Use Proofline

Use Proofline for:

- multi-step or ambiguous software work
- work tracked in Linear
- work that creates GitHub branches, commits, or pull requests
- completion claims that depend on tests, CI, review state, or artifact proof
- retry or repair loops after invalid proof
- final project acceptance before telling Sean "done"

Do not use Proofline for:

- quick questions
- research summaries
- drafting text
- trivial local checks
- work with no meaningful external proof
- tasks where Sean is directly supervising the result in real time

Rule of thumb:

If Hermes is coordinating work, Proofline should verify completion. If Hermes is only answering or assisting, Proofline is probably unnecessary.

## Trust Boundary

Never treat these as completion truth:

- Hermes narrative
- Codex narrative
- Symphony runner status
- OpenClaw or other executor status
- Linear `Done` by itself
- a GitHub PR URL by itself

Completion is accepted only when Proofline reports accepted completion with matched intent and sufficient evidence.

For task/read-model inspection, start with `completion_validation_summary`.

The operator-safe done shape is:

- `completion_claimed=true`
- `completion_accepted=true`
- `intent_status=matched`
- `evidence_status=sufficient`

If Proofline reports `blocked`, `pending`, `insufficient`, `invalid`, `retrying`, or `review_required`, do not tell Sean the work is done.

## Modes

### Light Mode

Use when Sean asks for status or before reporting that a coordinated task is complete.

Inspect canonical state:

```bash
python3 -m modules.proofline_runtime --json inspect task <task-id>
```

Or use the API:

```bash
curl -sS http://127.0.0.1:8000/tasks/<task-id>/read-model
curl -sS http://127.0.0.1:8000/tasks/<task-id>/timeline
```

Report:

- current lifecycle state
- completion validation summary
- evidence status
- reconciliation status
- manual-review status
- next required action

### Validation Mode

Use when a worker claims code-bearing completion.

Require concrete artifacts:

- repository owner/name
- branch name
- commit SHA
- pull request URL
- changed files or proof that changed files can be verified
- tests or CI evidence when relevant

Submit or inspect the completion through Proofline's canonical completion path, not by trusting the worker summary.

If Proofline returns retryable invalid proof, request repair instead of escalating immediately.

If Proofline returns `needs_review` or `review_required`, tell Sean the task needs explicit review and include the reason.

### Live Project Mode

Use when validating a real Linear/GitHub dry-run or production-like project.

First run synthetic validation:

```bash
python3 scripts/proofline_validate.py
```

Run coverage when the work touched backend/control-plane behavior:

```bash
PYTHONPATH=.tmp/proofline-dev-python python3 -m coverage run -m unittest discover -s tests
PYTHONPATH=.tmp/proofline-dev-python python3 -m coverage report -m
```

Before live mutation, run the armed read-only preflight:

```bash
HARNESS_RUN_LIVE_RESET_TESTS=1 python3 scripts/proofline_live_preflight.py --json
```

Proceed only if preflight reports `ready` and the approved targets are correct.

Approved dry-run targets:

- Linear project: `HARNESS-DRYRUN`
- GitHub repository: `sfayka/HARNESS-DRYRUN`
- Base branch: `main`

Only after the armed preflight is ready, run:

```bash
HARNESS_RUN_LIVE_RESET_TESTS=1 python3 -m unittest tests.test_reset_live_smoke -v
```

Record every live artifact:

- Linear issue URLs
- GitHub branch names
- commit SHAs
- PR URLs
- final Proofline verdicts
- cleanup performed or intentionally skipped

## Reporting Format

When reporting to Sean, use this shape:

```text
Proofline status:
- Task/project:
- Commit tested:
- Synthetic validation:
- Coverage:
- Armed preflight:
- Live smoke:
- Linear artifacts:
- GitHub artifacts:
- Final Proofline verdict:
- Remaining blockers:
```

If live smoke did not run, say exactly why. Do not imply completion from a skipped gate.

## Repo Rename Handling

Prefer the `proofline` repository name after Sean renames it.

Until every local checkout and integration has migrated, tolerate the old `Harness` path and GitHub redirect. Before running validation, always pull latest `main` from the configured remote and report:

```bash
git remote -v
git pull --ff-only
git log -5 --oneline
git status --short
```

If the remote still points at `sfayka/Harness`, GitHub redirects may work after the rename, but Hermes should update its configured repository URL to the new Proofline repo as soon as the rename is complete.
