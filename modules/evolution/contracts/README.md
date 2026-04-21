# Evolution Contracts Scaffold

This directory holds planning-stage contracts for future HEE outputs.

These contracts define:

- what a failure diagnosis must contain, including strict observed-fact vs inferred-cause separation
- what an evolution candidate must contain before a proposal is drafted
- what an evolution proposal must contain for auditable human review and decision tracking
- what execution trace records must contain for future diagnosis inputs
- what execution budget records must contain for cost, retry, fan-out, and continuation governance
- how taxonomy versioning and provenance back to task, trace, artifact, and review records are preserved

Contracts here are non-executable and non-authoritative for runtime behavior until implemented through normal Harness review.

## Current Planning Contracts

- `failure-diagnosis.contract.md`
- `evolution-candidate.contract.md`
- `evolution-proposal.contract.md`
- `execution-trace-requirements.contract.md`
- `execution-budget.contract.md`
