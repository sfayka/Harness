---
name: proofline-acceptance
description: Use when an agent is coordinating software work and needs Proofline to validate completion against user intent and evidence.
---

# Proofline Acceptance Skill

Use this skill when an agent is coordinating software work where an executor saying "done" is not enough.

Proofline is not the worker. Proofline is the acceptance layer. It validates whether a completion claim matches user intent, the task contract, GitHub evidence, Linear facts, and review policy.

This skill is agent-agnostic. Hermes, OpenClaw, Claude, Codex, or another coordinator can use it as long as it can inspect the repo, run commands, and report artifacts. The coordinator remains an interface or worker. Proofline remains the completion authority.

## When To Use Proofline

Use Proofline for:

- multi-step or ambiguous software work
- work tracked in Linear
- work that creates GitHub branches, commits, or pull requests
- completion claims that depend on tests, CI, review state, or artifact proof
- retry or repair loops after invalid proof
- final project acceptance before telling the user "done"

Do not use Proofline for:

- quick questions
- research summaries
- drafting text
- trivial local checks
- work with no meaningful external proof
- tasks where the user is directly supervising the result in real time

Rule of thumb:

If an agent is coordinating work, Proofline should verify completion. If the agent is only answering or assisting, Proofline is probably unnecessary.

## Trust Boundary

Never treat these as completion truth:

- coordinator narrative
- executor narrative
- Codex narrative
- Symphony runner status
- OpenClaw, Hermes, Claude, or other agent status
- Linear `Done` by itself
- a GitHub PR URL by itself

Completion is accepted only when Proofline reports accepted completion with matched intent and sufficient evidence.

For task/read-model inspection, start with `completion_validation_summary`.

The operator-safe done shape is:

- `completion_claimed=true`
- `completion_accepted=true`
- `intent_status=matched`
- `evidence_status=sufficient`

If Proofline reports `blocked`, `pending`, `insufficient`, `invalid`, `retrying`, or `review_required`, do not tell the user the work is done.

## Capability Check

Before using Proofline for real validation, verify what the current environment can actually do.

Minimum local capability:

- read the Proofline repository
- pull latest `main`
- run Python commands from the repo
- run `python3 scripts/proofline_validate.py`
- inspect Proofline API/read-model output

Code-proof capability:

- read the user's Git hosting system
- inspect repository, branch, commit, pull request or merge request metadata
- verify changed files or equivalent diff evidence
- verify test or CI evidence when required by the task

Project-tracker capability:

- read the user's project-tracking system
- identify the intended work item
- read title, description, acceptance criteria, state, assignee/owner, dependency/blocker facts, and comments when relevant
- distinguish intended work state from Proofline-accepted completion

Current V1 live adapters:

- project tracker: Linear
- code host: GitHub

For V1, stick to Linear and GitHub for live validation. Other project trackers and code hosts belong in the V2 adapter layer. A new tracker or code host needs an adapter that translates vendor-specific payloads into Proofline's normalized external facts and evidence model. Until that exists, use Proofline in synthetic/local mode or manual-evidence mode, and be explicit that live reconciliation is not first-class for that tool yet.

If the environment is missing required access, stop and ask the user to connect the tool through their agent platform or provide credentials through Proofline's supported secret path. Do not invent proof from screenshots, summaries, or worker claims.

Useful local checks:

```bash
git remote -v
git pull --ff-only
python3 scripts/proofline_validate.py --list
python3 scripts/proofline_live_preflight.py --json
python3 -m modules.proofline_runtime --json setup status
python3 -m modules.proofline_runtime --json setup status --workflow github-proof
python3 -m modules.proofline_runtime --json setup status --workflow linear-sync
python3 -m modules.proofline_runtime --json secrets status
```

The unarmed live preflight is read-only and may report `not_ready`. That is useful: it tells the agent which credentials, targets, or tool connections are missing before any live mutation is attempted.

## Modes

### Light Mode

Use when the user asks for status or before reporting that coordinated work is complete.

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

If Proofline returns `needs_review` or `review_required`, tell the user the task needs explicit review and include the reason.

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

When reporting to the user, use this shape:

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

Prefer the `proofline` repository name after the repo is renamed.

Until every local checkout and integration has migrated, tolerate the old `Harness` path and GitHub redirect. Before running validation, always pull latest `main` from the configured remote and report:

```bash
git remote -v
git pull --ff-only
git log -5 --oneline
git status --short
```

If the remote still points at `sfayka/Harness`, GitHub redirects may work after the rename, but the agent should update its configured repository URL to the new Proofline repo as soon as the rename is complete.
