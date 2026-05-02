# Harness Agent Contract Bundle

This directory is generated from the canonical Harness repository for execution agents and sync consumers such as `HARNESS-DRYRUN`.

Do not edit files in this directory manually. Re-run `python scripts/export_agent_contract.py` from the Harness repo instead.

## Canonical API Surface

- `POST /tasks`: submit a new canonical task envelope
- `POST /tasks/<task_id>/reevaluate`: submit new evidence, facts, or review actions for an existing task
- `GET /tasks/<task_id>/read-model`: inspect current task truth
- `GET /tasks/<task_id>/timeline`: inspect the auditable task timeline

For claimed completion, inspect `completion_validation_summary` from successful
persisted evaluation responses, `GET /tasks`, or `GET /tasks/<task_id>/read-model`.
Treat executor completion as advisory until that summary reports accepted
completion, matched intent, and sufficient evidence.

## Included Examples

- `examples/create-task.json`: canonical `POST /tasks` submission example generated from the ingress/OpenClaw request builder
- `examples/evaluate-happy-path.json`: canonical accepted-completion evaluation request
- `examples/evaluate-mismatch.json`: canonical reconciliation-mismatch evaluation request
- `examples/evaluate-review-required.json`: canonical review-required evaluation request

## Source Of Truth

This bundle was generated from these Harness source files:

- `AGENTS.md`
- `README.md`
- `docs/api/agent-api-usage.md`
- `docs/architecture/runtime-execution-contract.md`
- `docs/integration/openclaw-harness-spike.md`
- `examples/api/create-task.json`
- `examples/api/evaluate-happy-path.json`
- `examples/api/evaluate-mismatch.json`
- `examples/api/evaluate-review-required.json`
- `scripts/render_api_examples.py`

## Provenance

- source repo: `Harness`
- source commit: `f04c7b8cc5d00d950f9a8a587d22309c8b191b01`
- generated at: `2026-05-02T15:31:15Z`
