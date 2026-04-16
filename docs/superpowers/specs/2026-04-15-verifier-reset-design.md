# Harness Verifier Reset Design

## Goal

Reset Harness around the smallest useful product: a local-first verification service that can prove whether OpenClaw and Codex Cloud actually produced a real GitHub result for a Linear issue.

The system should optimize for operator trust and low setup friction, not for broad control-plane completeness.

## Problem

The current repository has grown into a broad control-plane implementation:

- canonical `TaskEnvelope` ingestion and reevaluation
- multiple ingress adapters
- lifecycle enforcement
- read models and timelines
- a dashboard
- hosted deployment work
- autonomy queue and reconciliation flows

That architecture is coherent, but it is not solving the operator's immediate problem quickly enough.

The current pain is concrete:

- too much time is spent on environment variables, auth, and runtime wiring
- the product still does not provide one reliable end-to-end workflow
- Codex Cloud and similar systems still cannot be trusted to honestly report whether they created a real PR
- the operator already uses Linear as the work surface and does not need a second UI if Linear can show canonical truth

The reset must favor a thin vertical slice that saves operator time before expanding system scope again.

## Product Thesis

Harness V1 should be a verifier plus a small supervision loop.

It should not be the planner, the interview surface, the PRD author, the decomposition engine, or the executor.

For V1:

- OpenClaw owns intake, clarification, PRD generation, decomposition, Linear issue creation, and Codex dispatch.
- Harness owns verification contracts, GitHub proof validation, retry budgeting, and Linear truth updates.
- Linear remains the operator UI and source of record for work coordination.
- GitHub remains the proof source for code-bearing work.

## Core Workflow

The first shippable loop is:

1. OpenClaw creates a Linear issue and knows the expected repository and target branch context.
2. OpenClaw registers that issue with Harness by sending the verification contract.
3. OpenClaw dispatches Codex Cloud.
4. When Codex claims completion, OpenClaw sends a completion claim to Harness.
5. Harness validates the claim against GitHub.
6. Harness updates Linear with the canonical result.
7. If proof is invalid but retryable, Harness asks OpenClaw to repair the issue and tries again with a bounded retry budget.
8. If proof still does not become valid after the retry budget is exhausted, Harness moves the Linear issue to `In Review`.

This workflow exists specifically to catch false completion claims such as:

- no real PR
- PR in the wrong repository
- PR on a local-only or wrong branch
- missing commit SHA
- stale or unrelated PR URL

## V1 Scope

### Included

- local-first backend runtime
- repo-root `.env.local` for Harness runtime configuration
- OpenClaw local config under `config/openclaw/.env.local`
- file-backed persistence for reset-specific verification contracts
- GitHub REST validation of repo, branch, commit SHA, and PR
- Linear updates for workflow state and Harness substatus
- local OpenClaw repair dispatch through the OpenClaw CLI when repo-owned local config is present
- HTTP repair callback support as a fallback for remote OpenClaw receivers
- bounded retry budget
- deterministic supervision tick for active issues
- focused tests around the new verifier path

### Explicitly Out Of Scope

- dashboard-driven operator workflow
- hosted deployment as a requirement for usefulness
- broad TaskEnvelope-first architecture for V1 product behavior
- generic multi-ingress control-plane semantics
- generalized read-model and timeline expansion
- direct Codex Cloud credentials inside Harness
- OS-process tracking
- open-ended autonomous orchestration beyond verification and bounded retry

## State Model

Linear remains the visible workflow surface. Harness should reuse existing Linear states rather than inventing a second workflow taxonomy.

### Linear workflow states

- `In Progress`
- `In Review`
- `Done`

### Harness substatus

Harness writes a substatus through a Linear field or label:

- `running`
- `verifying`
- `retrying`
- `verified`
- `proof_invalid`
- `needs_review`

Only Harness should move an issue to `Done` in the reset slice.

`Done` means verified, not merely claimed complete.

## Verification Contract

The reset slice should store a per-issue verification contract rather than using the full TaskEnvelope machinery as the primary product object.

Required contract fields:

- Harness contract ID
- Linear issue ID
- expected GitHub owner/repo
- expected target branch or branch pattern
- current retry count
- max retry budget
- current Harness substatus
- latest completion claim summary
- timestamps for creation and last evaluation

OpenClaw is responsible for setting the expected repository and branch data correctly when it creates the Linear issue.

Harness does not infer those values.

## Completion Claim Contract

When OpenClaw says work is done, it sends a completion claim containing:

- Linear issue ID
- claimed repo owner/name
- claimed branch name
- claimed commit SHA
- claimed PR number and/or PR URL

Harness then verifies:

- the repository is the expected repository
- the branch exists remotely
- the commit exists in the expected repository
- the PR exists and is real
- the PR belongs to the expected repository
- the PR head branch matches the claim
- the PR head SHA matches the claim

The acceptance bar is strict: it must be a real PR the operator can click and merge.

## Verdicts

Harness should produce machine-readable verdicts so OpenClaw can act immediately.

Canonical reset-slice verdicts:

- `verified_done`
- `retryable_invalid_proof`
- `needs_review`

`retryable_invalid_proof` is not terminal. It means the claim is unacceptable in its current form, but OpenClaw should dispatch Codex to repair the issue.

After the retry budget is exhausted, the verdict becomes `needs_review`.

## Supervision Loop

OpenClaw cannot be trusted to remember future-time follow-up on its own. That means Harness must own a small deterministic supervision clock.

The supervision loop should:

- look only at Harness-managed issues still in `In Progress`
- revisit issues whose latest state is `running`, `verifying`, or `retrying`
- re-check GitHub proof when a claim exists but is not yet verified
- trigger OpenClaw repair when proof is invalid and retries remain
- escalate to `In Review` when retries are exhausted

The loop should not:

- inspect local OS processes
- poll every issue in Linear
- become a general workflow engine

## Environment Contract

Harness runtime configuration should be intentionally small.

Required local secrets and endpoints:

- `GITHUB_TOKEN`
- `LINEAR_API_KEY`

Optional local config:

- `OPENCLAW_BASE_URL`
- `OPENCLAW_REPAIR_ENDPOINT`
- `HARNESS_STORE_BACKEND=file`
- `HARNESS_STORE_ROOT`
- `HARNESS_RESET_POLL_SECONDS`
- `HARNESS_RESET_RETRY_BUDGET`
- `LINEAR_TEAM_ID` or other workflow mapping helpers if required by the issue update path

The backend should automatically load repo-root `.env.local` in local development so operators and agents do not need to keep exporting variables manually.

When `config/openclaw/.env.local` exports `OPENCLAW_CONFIG_PATH` or `OPENCLAW_STATE_DIR`, Harness should prefer local `openclaw agent --local` dispatch for repair requests. The HTTP callback fields remain the fallback for remote or gateway-exposed OpenClaw receivers.

The repo-owned OpenClaw local template should default the agent model to `openai-codex/gpt-5.4` so Codex OAuth can be used directly without requiring a separate `OPENAI_API_KEY`.

## API Surface

The reset should add a narrow API surface alongside the existing backend routes rather than replacing the old API in one step.

Recommended reset routes:

- `POST /reset/contracts`
  Register a Linear issue verification contract.

- `GET /reset/contracts`
  List reset-slice contracts for local inspection and tests.

- `GET /reset/contracts/{contract_id}`
  Inspect one contract.

- `POST /reset/contracts/{contract_id}/claims`
  Submit a completion claim and get an immediate verification verdict.

- `POST /reset/tick`
  Run one deterministic supervision cycle for local testing.

This keeps the reset path explicit while allowing the older TaskEnvelope surface to coexist during migration.

## Implementation Strategy

The reset should be additive first.

That means:

- preserve the existing broad control-plane code for now
- add a new reset-specific service and storage path
- write focused tests for the reset slice
- prove the narrow loop locally
- only then decide which older surfaces should be deprecated or removed

This is safer than trying to collapse the existing architecture before a working replacement exists.

## Success Criteria

The reset is successful when all of the following are true:

1. A local agent can run Harness with one command against repo-root `.env.local`.
2. OpenClaw can register a Linear issue contract through a thin HTTP client.
3. A fake completion claim with bad proof is rejected.
4. Harness updates Linear to show canonical non-acceptance.
5. Harness can trigger OpenClaw repair with a structured reason.
6. A valid completion claim with a real repo, branch, commit SHA, and PR is accepted.
7. Harness moves the Linear issue to `Done` only after successful verification.

## Rejected Alternatives

### Keep the dashboard as the main operator surface

Rejected because it adds another surface to keep truthful and increases local setup friction. Linear already satisfies the operator UI need.

### Make Harness push-only with no supervision loop

Rejected because OpenClaw is not a reliable owner of future-time follow-up.

### Give Harness Codex Cloud credentials and direct dispatch responsibility in V1

Rejected because it adds substantial environment and orchestration complexity without being required for the core trust problem.

### Preserve the full TaskEnvelope-centric architecture as the V1 product shape

Rejected because the product needs a narrow vertical slice that works before it needs generalized control-plane breadth.
