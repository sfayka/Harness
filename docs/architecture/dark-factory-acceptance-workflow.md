# Dark Factory Acceptance Workflow

## Status

Reference architecture for Proofline adoption.

This workflow is adopted as a Proofline reference pattern, not as a new product surface. It describes how Proofline should sit above a tracker-to-runner-to-GitHub automation loop and decide whether work is truly acceptable.

## Pattern

A dark-factory workflow moves work through an automated loop:

```text
Production signal or user intent
        |
        v
Linear issue or tracker record
        |
        v
Symphony-like execution substrate
        |
        v
Codex or another executor
        |
        v
GitHub branch, commit, pull request, CI, review
        |
        v
Proofline verification, reconciliation, and review gates
        |
        v
Accepted, blocked, failed, retryable, or in_review
```

Proofline should own the acceptance boundary at the end of the loop and the policy feedback that can send work back for repair. It should not become the issue tracker, runner daemon, or executor.

## Proofline Primitives Involved

The existing primitives are sufficient for this workflow:

- `TaskEnvelope` for the canonical task contract
- execution packets for upstream intent/spec/context bundles
- execution-substrate events for runner progress and handoff
- completion claims for executor-reported done states
- artifact evidence for GitHub branches, commits, pull requests, diffs, CI, logs, and outputs
- tracker facts for intended-work state
- reconciliation rules for Linear/GitHub/Proofline alignment
- sticky manual-review gates for ambiguous or unsafe outcomes
- timeline and read-model surfaces for durable inspection
- supervision queue and execution-substrate intents for retryable or stale work

No new control-plane role is required.

## Evidence By Transition

### Tracker Record Created

Proofline should capture:

- tracker provider and record identity
- title, body, status, labels, owner, and links
- intended repository or execution context when known
- acceptance criteria or evidence requirements

### Runner Dispatch Requested

Proofline should capture:

- task ID and attempt ID
- runner kind and executor kind
- execution budget and retry policy
- workspace identity or workspace policy
- handoff payload digest

### Executor Claims Completion

Proofline should capture:

- completion claim ID
- attempt binding
- claimed summary
- artifact references
- validation commands or test references
- known unresolved conditions

The claim remains advisory.

### GitHub Artifacts Exist

Proofline should capture and validate:

- repository identity
- branch name and base branch
- commit SHA
- pull request URL and number
- changed-file summary
- CI/check status when relevant
- review state when relevant

### Acceptance Decision

Proofline should publish:

- completion validation verdict
- evidence summary
- reconciliation summary
- review summary
- lifecycle transition
- timeline events explaining the decision

## Failure Modes

The workflow should explicitly catch:

- executor says done but no pull request exists
- pull request exists in the wrong repository or branch
- pull request exists but does not match the current attempt
- tests or CI are missing, failing, or inconclusive when required
- tracker state moves to done before evidence is accepted
- multiple runs compete over the same tracker record or branch
- stale artifacts from an earlier attempt are reused as current proof
- manual review is required but skipped
- async or integration proof is still pending

These are acceptance-layer failures, not runner failures alone.

## What To Adopt

Adopt this as a reference integration pattern for explaining Proofline:

- tracker is the work queue
- runner is the execution substrate
- executor performs the work
- GitHub stores artifact proof
- Proofline validates whether the work can be accepted

This is enough to guide demos, documentation, and future integration tests.

## What Not To Build

Do not turn this pattern into:

- a second Linear UI
- an always-on tracker poller by default
- a custom runner daemon
- an auto-merge system
- a generic PM workflow engine
- a dashboard that treats runner progress as accepted truth

## Next Implementation Slice

The next issue-sized slice should be a deterministic reference scenario:

1. seed a tracker-backed task through canonical submission
2. record a runner handoff event
3. submit an executor completion claim
4. attach GitHub artifact evidence
5. reevaluate into accepted, blocked, or in_review
6. render the result through read-model and timeline surfaces

That scenario should use public API paths and clearly labeled sample data unless it is explicitly configured for live Linear/GitHub dry-run targets.
