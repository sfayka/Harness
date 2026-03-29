# Agent API Usage

This document is the source-of-truth API usage guide for execution agents and downstream synced bundles.

## Canonical Submission Paths

- `POST /tasks`: submit a new canonical task payload
- `POST /tasks/<task_id>/reevaluate`: submit new facts, artifacts, or review decisions for an existing task

## Review-Required Lifecycle Rule

- If verification returns `requires_review=true`, Harness moves the task into `in_review`.
- A review-required result must not leave the task in `completed`.
- Manual review is what resolves `in_review` back to `completed`, `blocked`, `failed`, `planned`, `dispatch_ready`, `assigned`, or `canceled`.

## Reconciliation Classification Rule

Harness keeps these classes separate:

- `mismatch`: external facts directly contradict the task state or execution target and can be classified automatically
- `pending`: external facts are still incomplete, delayed, or otherwise not ready for a blocking contradiction decision
- `review_required`: external facts are unresolved or ambiguous enough that Harness cannot safely decide automatically

Current canonical example:

- `linear_record_not_found` is treated as `review_required`, not as an automatic mismatch, because the system cannot safely infer whether the task is missing, mislinked, or temporarily unresolved

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

If you also need the synced execution bundle under `exports/agent-contract/`, regenerate that with:

```bash
.venv/bin/python scripts/export_agent_contract.py
```
