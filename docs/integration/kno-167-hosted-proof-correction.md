# KNO-167 Hosted OpenClaw Proof — Artifact Correction (2026-04-03)

This note corrects the completion artifact reporting for KNO-167.

## Why this correction exists

A prior task update referenced a historical merged PR that was **not** created by that task run. That violates the Codex Cloud artifact contract for this repository.

This run only reports artifacts produced during this run.

## Hosted proof run in this execution

The run evidence for this execution is stored in:

- `docs/integration/artifacts/kno-167-hosted-proof-20260403-run-correction.json`

Recorded proof task id:

- `task-openclaw-hosted-proof-20260403-194057`

Recorded hosted endpoints include:

- `POST https://harness-qeav.onrender.com/ingress/openclaw`
- `GET https://harness-qeav.onrender.com/tasks`
- `GET https://harness-qeav.onrender.com/tasks/task-openclaw-hosted-proof-20260403-194057/read-model`
- `GET https://harness-qeav.onrender.com/tasks/task-openclaw-hosted-proof-20260403-194057/timeline`
- `GET https://harness-umber.vercel.app/api/harness/tasks`
- `GET https://harness-umber.vercel.app/api/harness/tasks/task-openclaw-hosted-proof-20260403-194057/read-model`
- `GET https://harness-umber.vercel.app/api/harness/tasks/task-openclaw-hosted-proof-20260403-194057/timeline`

## Manual gaps (honest status)

- Browser screenshot capture is still a manual gap in this environment because a browser screenshot tool was not available in-session.

## Artifact reporting rule applied in this correction

- Only repository/branch/commit/PR artifacts created by this execution are valid completion identifiers.
- Historical PRs are not substituted as evidence for this run.
