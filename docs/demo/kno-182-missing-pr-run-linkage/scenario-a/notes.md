# Scenario A notes

- Construction: commit-associated existing PR candidate intentionally omitted current-run linkage markers in PR body.
- Expected: candidate rejected for current run; reconciliation creates a new PR candidate instead.
- Actual: final_decision=created_new; rejected reasons=['run_linkage_missing']; create_calls=1.
- Result: matched expectation.
