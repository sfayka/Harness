# Proofline Repository Audit And Refactor Plan

## Spec

Complete a repository-wide audit, then make only the refactors that are clearly justified by the audit and can be verified without weakening Proofline invariants.

The audit must cover:

- Python control-plane logic: `modules/api.py`, `modules/evaluation.py`, `modules/store.py`, `modules/read_model.py`, and `modules/contracts/`
- adapters and ingress: `modules/adapters/`, `modules/connectors/`, and canonical submission/reevaluation boundaries
- runtime/demo/reset utilities: `modules/*runtime*.py`, `modules/demo_*.py`, `modules/reset/`, and scripts
- frontend dashboard: `app/`, `components/dashboard/`, `lib/`, and frontend tests
- docs and repo hygiene: `README.md`, `AGENTS.md`, `docs/architecture/`, `docs/setup/`, generated outputs, and stale Harness/Proofline naming
- test/build health and improvement backlog

Refactoring rules:

- preserve canonical task truth, lifecycle enforcement, manual-review stickiness, append-only evaluation history, and read-model/timeline contracts
- prefer thin adapters and helpers over changing backend semantics
- do not turn the dashboard into a mutation surface
- do not silently replace live backend truth with mock/sample data
- do not mix broad architecture changes with opportunistic cleanup
- keep existing uncommitted user changes intact unless they are directly in scope and reviewed

## Plan

- [x] Confirm baseline state and existing user changes.
  - Record branch, remote, dirty files, and generated/untracked outputs.
  - Decide which existing dirty files are out of scope for this pass.

- [x] Run the smallest full-repo health baseline.
  - Python: `python -m unittest discover -s tests`
  - Frontend: `pnpm lint`, `pnpm build`, and `pnpm test:frontend`
  - Static hygiene: `git diff --check`
  - Capture failures as audit findings before editing.

- [x] Audit control-plane hotspots.
  - Review large/high-risk files: `modules/api.py`, `modules/reconciliation_runtime.py`, `modules/read_model.py`, `modules/store.py`, and contract validators.
  - Identify duplicated policy logic, unclear lifecycle boundaries, internal shortcut paths, and brittle tests.
  - Only refactor with tests when behavior can be preserved and proven.

- [x] Audit adapter and ingress boundaries.
  - Verify public clients still go through canonical submission and reevaluation paths.
  - Check OpenClaw, Codex Cloud, Symphony, GitHub, Linear, and manual ingress builders for duplicated normalization or policy leakage.
  - Prefer adapter-local cleanup over schema or evaluator changes.

- [x] Audit runtime, reset, demo, and script surfaces.
  - Check dry-run, local runtime, reset, and demo helpers for internal persistence/evaluation shortcuts.
  - Confirm seeded/demo data remains deterministic and honestly labeled.
  - Refactor obvious duplication only after protecting behavior with focused tests.

- [x] Audit dashboard and frontend data flow.
  - Verify dashboard reads canonical API/read-model/timeline surfaces.
  - Check fallback/sample-data labeling, API proxy behavior, and large dashboard components for safe extraction opportunities.
  - Run browser verification only if frontend behavior changes.

- [x] Audit docs, naming, and repo hygiene.
  - Find stale Harness naming that should remain compatibility-only versus stale product wording that should be updated.
  - Verify docs point to current commands and architecture boundaries.
  - Separate generated/demo artifacts from source changes.

- [x] Implement the first safe refactor batch.
  - Choose a narrow batch based on audit evidence, prioritizing low-risk duplication removal or file-boundary cleanup.
  - Add or adjust focused tests before behavior-preserving changes when practical.
  - Avoid contract changes unless the audit proves they are necessary.

- [x] Re-run validation for touched surfaces.
  - Backend changes: `python -m unittest discover -s tests`
  - Frontend changes: `pnpm lint`, `pnpm build`, and `pnpm test:frontend`
  - Docs-only changes: path/link/reference checks and `git diff --check`

- [x] Produce the improvement and expansion backlog.
  - Separate confirmed bugs, refactor candidates, product expansion ideas, docs gaps, test gaps, and larger architectural proposals.
  - Mark each item with risk, affected surface, suggested owner/sequence, and whether it needs an issue/PR.

## Review

- [x] Baseline commands and outcomes recorded.
  - Baseline state: branch `codex/tracker-provider-abstraction`, head `8c8b3a3`, remote `https://github.com/sfayka/Proofline.git`.
  - Pre-existing dirty files: `docs/architecture/runtime-execution-contract.md`, `docs/architecture/sandbox-secret-safety.md`, and generated `output/` artifacts.
  - This pass treats those dirty files as user-owned unless an audit finding explicitly brings them into scope.
  - `git diff --check` passed.
  - `python` is unavailable in this local shell; direct `python3 -m unittest discover -s tests` failed before test execution because dependencies were not installed in Homebrew Python 3.14.
  - `uv run --python 3.13 --with-requirements requirements-dev.txt python -m unittest discover -s tests` passed: 931 tests, 17 skipped.
  - `pnpm` is unavailable in this local shell.
  - `npm run test:frontend` passed: 23 tests.
  - `npx -y node@22 node_modules/next/dist/bin/next build` passed.
  - `npm run lint` and a focused `npx -y node@22 node_modules/eslint/bin/eslint.js ...` run both hung with no findings and were stopped.
- [x] Refactors are backed by audit findings, not speculative cleanup.
  - Implemented three audit-backed fixes: file-backed evaluation history guards, GitHub `reasons` validation, and frontend resolved-review status mapping.
- [x] Relevant tests/builds pass or failures are explained with exact blockers.
  - Final backend validation: `uv run --python 3.13 --with-requirements requirements-dev.txt python -m unittest discover -s tests` passed: 938 tests, 19 skipped.
  - Final frontend tests: `npm run test:frontend` passed: 24 tests.
  - Final frontend build: `npx -y node@22 node_modules/next/dist/bin/next build` passed.
  - Final static hygiene: `git diff --check` passed.
  - ESLint remains blocked in this shell: `npm run lint`, focused ESLint targets, and direct `eslint-config-next/core-web-vitals` import hung with no findings.
- [x] Proofline invariants remain intact.
- [x] Existing user-owned dirty changes are preserved.
- [x] Improvement backlog is concrete enough to turn into issues or follow-up PRs.
  - Backlog recorded in `docs/architecture/repository-audit-2026-05-17.md`.
