# KNO-161 real non-synthetic Harness run

This document records one real task executed through Harness using canonical API paths.

## Canonical task definition

- Linear issue: `KNO-161`
- GitHub issue: https://github.com/sfayka/Harness/issues/114
- Harness task id: `kno-161-real-task-2026-04-03`

## Canonical submission path used

1. Start API locally:
   - `python -m modules.api --host 127.0.0.1 --port 8010 --store-root .tmp/kno161/store`
2. Submit task:
   - `POST /tasks` with `create-task.json`
3. Inspect canonical read surfaces:
   - `GET /tasks/kno-161-real-task-2026-04-03/read-model`
   - `GET /tasks/kno-161-real-task-2026-04-03/timeline`
4. Reevaluate after real external artifacts exist:
   - `POST /tasks/kno-161-real-task-2026-04-03/reevaluate`

## External artifacts produced by the real task

- Repository: `sfayka/Harness`
- Branch: `codex/real-task-proof`
- Commit SHA: `04d9da2b7d8add29e33f8c98bf558e2d145b0f95`
- PR URL: `https://github.com/sfayka/Harness/pull/121`

## Harness evaluation snapshots

### Initial submission (before completion claim)

- Outcome: `verification_deferred`
- Reason: `No completion claim is currently being evaluated`
- Evidence state: deferred/pending until execution artifacts are attached

See:
- `create-response.json`
- `read-model-initial.json`
- `timeline-initial.json`

### Final reevaluation (after real artifacts)

- Request payload: `reevaluate-request.json`
- Response payload: `reevaluate-response.json`
- Read model: `read-model-final.json`
- Timeline: `timeline-final.json`

## Final lifecycle outcome

The task transitioned to `completed` after reevaluation with real repository artifacts (`accepted_completion=true`, `target_status=completed`, `action=transition_applied`).

## Notes

- This run is intentionally non-synthetic: it is tied to a real Linear issue and a real GitHub PR in this repository.
- If verification fails or requires manual review, that outcome is recorded as-is (no bypass).
