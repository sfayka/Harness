# Agent API Usage

This document is the source-of-truth API usage guide for execution agents and downstream synced bundles.

## Canonical Submission Paths

- `POST /tasks`: submit a new canonical task payload
- `POST /tasks/<task_id>/reevaluate`: submit new facts, artifacts, or review decisions for an existing task

For existing tasks, treat `POST /tasks/<task_id>/reevaluate` as the authoritative mutation path.

- Existing-task reevaluation uses the stored task snapshot as the source of truth.
- `POST /evaluate` may still be used as an evaluation surface for an existing task id, but Harness evaluates against the stored task snapshot and only reapplies the supported top-level overlays listed below.
- Automatic callers must not rely on `POST /evaluate` to overwrite an existing task lifecycle state by supplying a different nested `request.task_envelope`.

For new-task submission and one-shot evaluation, the canonical contract remains `request.task_envelope`. Harness also accepts ingress-style top-level overlays for convenience on initial requests:

- `request.task_status`
- `request.assigned_executor`
- `request.linked_artifacts`
- `request.completion_evidence`

Those overlays are merged into `request.task_envelope` before evaluation. For existing tasks evaluated through `POST /evaluate`, the same overlay fields are reapplied onto the stored task snapshot before policy evaluation. For canonical persisted updates, prefer `POST /tasks/<task_id>/reevaluate`.

## Review-Required Lifecycle Rule

- If verification returns `requires_review=true`, Harness moves an active non-terminal task into `in_review`.
- A review-required result must not leave the task in `completed`.
- Automatic review escalation is allowed from active lifecycle states such as `intake_ready`, `planned`, `dispatch_ready`, `assigned`, `executing`, and `blocked`.
- Automatic paths do not reopen `completed`, `failed`, or `canceled` tasks into review.
- Manual review is what resolves `in_review` back to `completed`, `blocked`, `failed`, `planned`, `dispatch_ready`, `assigned`, or `canceled`.
- Once review is active, automatic reevaluation, artifact sync, or external reconciliation must keep the task in `in_review` until an explicit manual decision resolves it.

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
