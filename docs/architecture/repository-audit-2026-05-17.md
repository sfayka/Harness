# Repository Audit - 2026-05-17

This audit covered the Python control plane, adapters/ingress/runtime surfaces, the Next dashboard, docs, validation tooling, and rename hygiene.

## Baseline

- Branch: `codex/tracker-provider-abstraction`
- Remote: `https://github.com/sfayka/Proofline.git`
- Local shell gaps: `python` and `pnpm` were unavailable.
- Backend validation passed with repo requirements through uv: `uv run --python 3.13 --with-requirements requirements-dev.txt python -m unittest discover -s tests`.
- Frontend unit tests passed with `npm run test:frontend`.
- Production build passed under Node 22: `npx -y node@22 node_modules/next/dist/bin/next build`.
- ESLint is currently blocked: importing `eslint-config-next/core-web-vitals` and running ESLint both hung with no findings in this shell.

## Refactors Landed In This Pass

1. File-backed evaluation history now preserves the same missing-task and duplicate-record guarantees as the SQL stores.
   - `FileBackedHarnessStore.put_evaluation_record` rejects records for missing tasks.
   - It refuses duplicate `evaluation_id` writes instead of overwriting JSON files.
   - The shared store contract now covers both cases.

2. GitHub fact normalization now validates `reasons` as a string sequence.
   - String values such as `"review required"` are rejected instead of becoming `("r", "e", ...)`.
   - Reason strings are stripped and empty entries are rejected.

3. Dashboard API mapping now renders resolved manual-review acceptance as accepted/reconciled.
   - `verification_summary.outcome = "review_resolved"` with accepted completion maps to `accepted`.
   - `reconciliation_summary.status = "resolved"` maps to `no_mismatch`.

## High-Priority Follow-Up

- Add a store-level atomic operation for "persist evaluated task plus evaluation records."
  Current API flows update task truth before appending evaluation records. If record persistence fails, lifecycle truth can advance without a matching audit record.

- Move manual-review post-processing into canonical enforcement or rebuild all nested enforcement summaries after mutation.
  Current post-processing updates top-level result task envelopes, but nested evidence/transition details can still reflect pre-reset state.

- Fix unattended dry runs to use canonical reevaluation.
  `modules/unattended_dryruns.py` creates tasks through `/tasks`, then posts overlay-heavy updates to `/evaluate`; existing-task updates should use `/tasks/<task_id>/reevaluate`.

- Prevent OpenClaw supervision from turning advisory execution artifacts into verified GitHub sync facts.
  GitHub sync should be provider-backed or explicitly unverified until a GitHub lookup validates the artifact.

- Reconcile Codex Cloud preflight policy with the Proofline repository rename.
  `scripts/codex-cloud-setup.sh`, docs, and `modules/adapters/codex_cloud/executor_adapter.py` still hard-code `/workspace/Harness` and `sfayka/Harness.git`.

- Fix dashboard task deep links.
  `?task=<id>` can be cleared while task data is still loading, preventing direct task-detail links from opening reliably.

## Medium-Priority Follow-Up

- Add timeline event-ID uniqueness tests and fix duplicate clarification event IDs in `modules/read_model.py`.
- Replace timestamp-only manual-review gate resolution with a shared helper keyed by `review_request_id`.
- Validate initial `POST /evaluate` review request task IDs against `task_envelope.id`.
- Parse Codex Cloud `.codex-bootstrap-proof` and require expected key/value fields instead of accepting any non-empty proof.
- Mark static demo GitHub artifacts as sample/unverified or route demo proof through `/sync/github`.
- Make demo bootstrap behavior explicit for persistent stores: reset namespace, skip existing seeds, or use run-scoped IDs.
- Decide whether reset service remains explicitly out-of-band or mirrors reset decisions into canonical task/timeline records.
- Split dashboard reconciliation display states so pending/review-required/stale evidence are not labeled as generic mismatches.
- Fix evidence validation matching to use exact artifact IDs instead of substring matching.
- Update docs for rename drift: hosted setup, local dashboard proxy route, README lifecycle wording, OpenClaw checkout examples, and repository rename status.
- Decide whether `output/` should be ignored, generated from a source command, or promoted under tracked docs/assets.

## Lower-Priority Cleanup

- Reduce duplicated ingress normalization between manual and Linear connectors by routing source-specific payloads through `IngressTaskIntent`.
- Add Proofline-first aliases for dashboard runtime config names while keeping Harness names as compatibility fallbacks.
- Refresh open task detail data after dashboard refreshes so the detail panel cannot retain stale timeline/read-model data.

## Expansion Candidates

- Provider abstraction v2 for non-Linear trackers after the current Linear/GitHub contract remains stable.
- Code-host abstraction for GitLab/Bitbucket only after GitHub artifact proof semantics are fully provider-backed.
- A canonical artifact-proof provider API that separates executor-advisory artifacts from externally verified artifacts.
- A dashboard status taxonomy helper that centralizes display labels, counts, and severity across table, cards, and detail panels.
- A store transaction contract that can be implemented by file, SQLite, and Postgres backends.
