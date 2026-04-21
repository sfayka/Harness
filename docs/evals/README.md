# Local Eval Specs

This directory holds planning-stage examples for the future local eval harness.

These files are not executable test definitions yet. They define the operator-readable spec shape Harness should support when local evals become runnable.

Local eval specs must stay tied to Harness inspection truth:

- use stable local fixtures when possible
- declare live external dependencies when unavoidable
- compare baseline and candidate runs by explicit regression category
- link results back to canonical task, read-model, timeline, evaluation, trace, artifact, and budget records when present
- avoid treating an eval pass as task completion authority

## Examples

- [`examples/repair-workflow.eval.md`](examples/repair-workflow.eval.md)
- [`examples/pr-review-skill.eval.md`](examples/pr-review-skill.eval.md)
