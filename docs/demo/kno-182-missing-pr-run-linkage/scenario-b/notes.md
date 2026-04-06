# Scenario B notes

- Construction: commit-associated existing PR candidate contained current-run linkage markers (task, attempt, claim, branch, commit).
- Expected: candidate accepted as proof for current run without creating a new PR.
- Actual: accepted=True; matched_by=['commit_association_match', 'task_linkage', 'attempt_linkage', 'completion_claim_linkage']; create_calls=0.
- Result: matched expectation.
