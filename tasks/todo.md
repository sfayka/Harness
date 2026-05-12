# Proofline Issue Backlog Pass

## Spec

Work the remaining open Proofline issues by turning actionable architecture work into focused PRs, closing stale or superseded issues with clear rationale, and redrafting broad research items into concrete next steps where needed.

## Plan

- [x] Refresh live GitHub issue state and local branch state.
- [x] Create a focused PR for issue #420 covering the v2 tracker/provider abstraction while preserving Linear as the v1 default.
- [x] Create or prepare a focused PR for issue #419 covering integration-proof evidence lanes.
- [x] Triage #417, #418, and #411 as close/redraft/follow-up based on existing Proofline architecture.
- [x] Run relevant validation for changed docs.
- [x] Summarize issue state, PRs, and any remaining user decisions.

## Review

- `git diff --check` passed.
- `python3 -m unittest tests.test_hosted_docs -v` passed.
- Checked changed Markdown links; all local links resolved.
- Opened PR #426 for #417, #419, and #420.
- Closed #411 as covered by the existing supervision queue, retry/stale/review behavior, and execution-substrate intent surfaces.
- Closed #418 as monitor-only because no reliable public `gpr` artifact matching the issue signal was found.
