# Agent API Usage

This document is the source-of-truth API usage guide for execution agents and downstream synced bundles.

## Canonical Submission Paths

- `POST /tasks`: submit a new canonical task payload
- `POST /tasks/<task_id>/reevaluate`: submit new facts, artifacts, or review decisions for an existing task

## Linear Facts Workflow Rule

The `external_facts.linear_facts.workflow` field is conditional on `record_found`.

- If `record_found=false`, `workflow` must be `null` or omitted.
- If `record_found=true`, `workflow` must be an object containing:
  - `workflow_id`
  - `workflow_name`

Invalid combinations should return an `invalid_input` API error rather than an internal constructor or parser exception.

## Canonical Examples

Generated source-of-truth payloads live under `examples/api/`:

- `examples/api/create-task.json`
- `examples/api/evaluate-happy-path.json`
- `examples/api/evaluate-mismatch.json`
- `examples/api/evaluate-review-required.json`

Regenerate them with:

```bash
.venv/bin/python scripts/render_api_examples.py
```
