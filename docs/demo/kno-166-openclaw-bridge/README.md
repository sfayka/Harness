# KNO-166 persisted OpenClaw ingress bridge proof

This run records one real persisted bridge from OpenClaw-shaped ingress into Harness canonical task truth, through reevaluation, and into dashboard-facing inspection surfaces.

## Canonical task definition

- Linear issue: `KNO-166`
- GitHub issue: https://github.com/sfayka/Harness/issues/127
- Harness task id: `kno-166-openclaw-bridge-2026-04-03`

## Canonical flow executed

1. Start API with isolated store:
   - `python -m modules.api --host 127.0.0.1 --port 8010 --store-root .tmp/kno166/store`
2. Submit OpenClaw ingress payload:
   - `POST /ingress/openclaw` with `create-request.json`
3. Confirm persistence + inspection visibility:
   - `GET /tasks`
   - `GET /tasks/kno-166-openclaw-bridge-2026-04-03/read-model`
   - `GET /tasks/kno-166-openclaw-bridge-2026-04-03/timeline`
4. Submit governed reevaluation with external completion evidence:
   - `POST /tasks/kno-166-openclaw-bridge-2026-04-03/reevaluate` with `reevaluate-request.json`
5. Re-check canonical read surfaces used by dashboard task views:
   - `GET /tasks`
   - `GET /tasks/kno-166-openclaw-bridge-2026-04-03/read-model`
   - `GET /tasks/kno-166-openclaw-bridge-2026-04-03/timeline`

## Outcome summary

- Ingress provenance persisted with `source_system=openclaw` and OpenClaw extension metadata.
- Initial evaluation state is deferred until a completion claim is submitted.
- Reevaluation with external artifacts transitions the task to `completed`.
- Dashboard-facing surfaces (`/tasks`, `/tasks/<id>/read-model`, `/tasks/<id>/timeline`) all include this task after ingress and after reevaluation.

## External artifacts used for completion evidence

- Repository: `sfayka/Harness`
- Branch: `codex/real-task-proof`
- Commit SHA: `04d9da2b7d8add29e33f8c98bf558e2d145b0f95`
- PR URL: `https://github.com/sfayka/Harness/pull/121`

## Captured payloads and responses

- `create-request.json`
- `create-response.json`
- `read-model-initial.json`
- `timeline-initial.json`
- `tasks-after-create.json`
- `reevaluate-request.json`
- `reevaluate-response.json`
- `read-model-final.json`
- `timeline-final.json`
- `tasks-after-reevaluate.json`

## Honest remaining gap

This proof demonstrates persisted ingress, evaluation, and dashboard visibility via canonical Harness surfaces. It does **not** claim that all execution is human-free; manual artifact collection/reconciliation inputs may still be required depending on policy and external fact availability.
