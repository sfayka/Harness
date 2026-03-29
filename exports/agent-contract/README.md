# Harness Agent Contract Bundle

This directory is generated from the canonical Harness repository for execution agents and sync consumers such as `HARNESS-DRYRUN`.

Do not edit files in this directory manually. Re-run `.venv/bin/python scripts/export_agent_contract.py` from the Harness repo instead.

## Canonical API Surface

- `POST /tasks`: submit a new canonical task envelope
- `POST /tasks/<task_id>/reevaluate`: submit new evidence, facts, or review actions for an existing task
- `GET /tasks/<task_id>/read-model`: inspect current task truth
- `GET /tasks/<task_id>/timeline`: inspect the auditable task timeline

## Included Examples

- `examples/create-task.json`: canonical `POST /tasks` submission example generated from the ingress/OpenClaw request builder
- `examples/evaluate-happy-path.json`: canonical accepted-completion evaluation request
- `examples/evaluate-mismatch.json`: canonical reconciliation-mismatch evaluation request
- `examples/evaluate-review-required.json`: canonical review-required evaluation request

## Source Of Truth

This bundle was generated from these Harness source files:

- `AGENTS.md`
- `README.md`
- `docs/architecture/runtime-execution-contract.md`
- `docs/integration/openclaw-harness-spike.md`
- `modules/connectors/ingress_request_builder.py`
- `modules/connectors/openclaw_harness_spike.py`
- `modules/demo_cases.py`

## Provenance

- source repo: `Harness`
- source commit: `e46be111b793ea88f8ca0133f009c4f442931c59`
- generated at: `2026-03-29T15:38:47Z`
