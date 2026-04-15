# Hosted Dry-Run Operator Flow

Use this when you want one real end-to-end dry run with:

- Linear as the upstream work record
- Codex Cloud as the executor
- GitHub as artifact proof
- hosted Harness as the control plane and inspection surface

This flow is intentionally minimal. The repo-owned helper owns the repetitive API calls so the operator only performs:

1. one `start` command
2. one prompt paste into Codex Cloud
3. one `finish` command with the returned PR URL

## Prerequisites

Set these local environment variables before running the helper:

```bash
export LINEAR_AUTH=lin_api_...
export GH_AUTH=github_pat_...
```

The defaults in the helper already target the current dry-run systems:

- Harness: `https://harness-umber.vercel.app/backend`
- Dashboard: `https://harness-umber.vercel.app/tasks`
- GitHub repo: `sfayka/HARNESS-DRYRUN`
- Base branch: `main`
- Target proof file: `docs/dry-run-proof.md`

## Step 1: Ingest The Linear Issue And Render The Executor Prompt

```bash
python scripts/hosted_dryrun.py start --linear-issue KNO-185
```

This command:

- fetches the Linear issue
- submits it through `POST /ingress/linear`
- writes a local session file under `.harness-dryruns/`
- writes an exact Codex Cloud prompt under `.harness-dryruns/`
- prints the prompt to stdout

## Step 2: Paste The Printed Prompt Into Codex Cloud

The helper-generated prompt already includes:

- required preflight proof
- the exact target repository
- the exact file to change
- the exact commit message
- the required final proof lines

Codex Cloud must return:

- `Repository: ...`
- `Branch: ...`
- `Commit SHA: ...`
- `PR URL: ...`

## Step 3: Finalize The Run In Harness Using Only The PR URL

Use the session file printed by step 1 and the PR URL returned by Codex Cloud:

```bash
python scripts/hosted_dryrun.py finish \
  --session .harness-dryruns/<task-id>.session.json \
  --pr-url https://github.com/sfayka/HARNESS-DRYRUN/pull/<number>
```

This command:

- fetches the PR, commit, reviews, and changed files from GitHub
- verifies the expected proof file exists in the PR
- posts `POST /tasks/<task_id>/completion-claims`
- posts `POST /sync/github`
- fetches:
  - `GET /tasks/<task_id>/read-model`
  - `GET /tasks/<task_id>/timeline`
  - `GET /tasks/<task_id>/evaluations`
- writes those artifacts back into `.harness-dryruns/`

## Step 4: Recheck The Current Canonical State

At any point:

```bash
python scripts/hosted_dryrun.py status \
  --session .harness-dryruns/<task-id>.session.json
```

That prints the current read-model, timeline, and evaluations payloads from the hosted backend.
