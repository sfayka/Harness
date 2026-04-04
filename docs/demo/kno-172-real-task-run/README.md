# KNO-172 real non-synthetic Harness run

This document records one real task executed through Harness using canonical API paths.

## Canonical task definition

- Linear issue: `KNO-172`
- GitHub issue: https://github.com/sfayka/Harness/issues/147
- Harness task id: `kno-172-real-task-2026-04-04`

## Canonical submission path used

1. Start API locally:
   - `python -m modules.api --host 127.0.0.1 --port 8012 --store-root .tmp/kno172/store`
2. Submit task:
   - `POST /tasks` with `create-task.json`
3. Inspect canonical read surfaces:
   - `GET /tasks/kno-172-real-task-2026-04-04/read-model`
   - `GET /tasks/kno-172-real-task-2026-04-04/timeline`
4. Reevaluate after real external artifacts exist:
   - `POST /tasks/kno-172-real-task-2026-04-04/reevaluate` with `reevaluate-request.json`

## Real external artifacts produced during this run

- Repository: `sfayka/Harness`
- Branch: `codex/real-task-proof`
- Commit SHA: `d6e0d3ca62f8604b44ff1656b9349dd7683e7c03`
- PR URL: `https://github.com/sfayka/Harness/pull/148`

## Proof bundle contents

- Ingress payload: `create-task.json`
- Ingress response: `create-response.json`
- Initial read-model: `read-model-initial.json`
- Initial timeline: `timeline-initial.json`
- Reevaluation payload: `reevaluate-request.json`
- Reevaluation response: `reevaluate-response.json`
- Final read-model: `read-model-final.json`
- Final timeline: `timeline-final.json`

## Honest run result

### What is fully working

- Canonical submission, persistence, timeline recording, and reevaluation all executed through public API endpoints.
- The final reevaluation accepted completion with artifact-backed evidence (`accepted_completion=true`, `action=transition_applied`).
- Reconciliation stayed `no_mismatch` with repository/branch/commit/PR facts matching the run.

### What still required human/manual involvement

- Artifact and fact payloads were assembled manually for this proof run.
- Local API process orchestration (start server, call endpoints, capture JSON snapshots) was manual.

### What is still missing for full autonomy

- This run used the stub executor path for dispatch attempt data, not a production autonomous executor.
- Read-model `task.status` remained `null` in `read-model-final.json` despite accepted completion, so lifecycle status projection still needs tightening.

This is intentionally documented as-is without smoothing over gaps.
