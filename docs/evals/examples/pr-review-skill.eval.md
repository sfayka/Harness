# PR Review Skill Local Eval Example

## Eval Spec

```yaml
id: eval-pr-review-skill-v1
title: PR review skill actionable-comment classification
target_type: skill
target_ref: github:gh-address-comments
scenario: >
  A PR review workflow receives a fixture containing blocking comments,
  resolved comments, praise-only comments, and ambiguous comments. The skill
  must identify actionable work without converting non-actionable commentary
  into tasks.
fixture_refs:
  - docs/evals/fixtures/pr-review-comments.v1.json
expected_outcomes:
  - blocking comments are classified as actionable
  - resolved comments are ignored unless they reveal unresolved follow-up
  - praise-only comments are not turned into work
  - ambiguous comments are surfaced as questions or review-needed items
must_pass_checks:
  - all fixture comments with expected_classification=actionable are returned
  - no fixture comments with expected_classification=non_actionable are returned as required work
  - output includes file path and line references when fixture provides them
  - output does not claim code changes were completed
allowed_variance:
  - wording of the human-readable plan may differ
  - ordering may differ only within the same severity class
  - ambiguous comments may be classified as questions or review-needed items
expected_artifacts:
  - human-readable action plan
  - structured actionable-comment list
expected_trace_properties:
  - inspected comments and final classifications are linkable
expected_budget_behavior:
  - no browser or external mutation tool class is used
canonical_surface_refs:
  - GitHub PR review threads
  - Harness task timeline when this eval is run through a Harness task
```

## Baseline Comparison

Baseline and candidate runs should compare:

- actionable recall
- false positive count
- file/line reference preservation
- operator readability
- tool usage class

## Operator Summary Shape

```text
REVIEW REQUIRED: Candidate found all blocking comments but misclassified one praise-only comment as required work.

Regression categories:
- correctness: regressed
- evidence quality: unchanged
- trace continuity: not_available
- budget behavior: unchanged
```
