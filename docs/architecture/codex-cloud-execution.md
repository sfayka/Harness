# Codex Cloud Execution

## Purpose

Document the verified Codex Cloud execution path for Harness.

Harness treats executor summaries as advisory. Real completion depends on externally verifiable artifacts and explicit control-plane evaluation. The Codex Cloud execution contract exists so delegated execution starts from a known repository state and produces inspectable proof about both environment readiness and completion artifacts.

## Verified Execution Chain

The verified Harness Codex Cloud environment starts with the repo-owned bootstrap command:

```bash
bash /workspace/Harness/scripts/codex-cloud-setup.sh
```

That script is responsible for:

- validating that the repository root is `/workspace/Harness`
- ensuring `origin` exists and points to `https://github.com/sfayka/Harness.git`
- setting local git identity for Codex
- configuring non-interactive GitHub authentication from `GH_AUTH`
- verifying that `git fetch origin` succeeds
- installing likely-needed Python dependencies from `requirements.txt` and `requirements-dev.txt` when present
- installing likely-needed Node dependencies from the detected lockfile or `package.json`
- writing `.codex-bootstrap-proof`

Codex Cloud uses system Python for this bootstrap path. Repository scripts and operator commands must be runnable as `python ...` without assuming a `.venv` exists or activating one.

The proof file is environment evidence, not task-completion evidence. It proves that bootstrap ran successfully in the expected repository context. It does not prove that a task produced an external commit or pull request.

## Why The Bootstrap Script Exists

The bootstrap script exists because interactive terminal success was not enough to prove delegated execution correctness.

Before this flow was verified, a human could be in a healthy local shell while a fresh Codex Cloud task sandbox still lacked the git remote, authentication, or fetch state needed to produce real external artifacts. That mismatch allowed task summaries to sound complete even when the repository context was not fully initialized for delegated execution.

Harness cannot accept that kind of ambiguity. Delegated task execution needs explicit proof of execution context before any completion claim is trusted.

That includes interpreter assumptions. A task that only works after manually activating `.venv` is not portable across Codex Cloud sandboxes, so Harness standardizes Python execution on the system `python` command and system-level dependency installation via `pip install -r requirements.txt`.

## Task Preflight Contract

Every real Codex Cloud task for Harness must begin by returning raw output for:

```bash
pwd
git remote -v
cat .codex-bootstrap-proof
```

No repository changes or execution steps may occur before preflight output is returned. Preflight output must be generated within the same execution session as the task.

This preflight is required because it proves:

- the task is running in the expected repository root
- the repository remote matches the canonical GitHub repository
- repo-owned bootstrap completed and recorded the expected proof

Preflight output from a previous session, cached output, or copied output is invalid. Each task run must independently prove its execution context before any repository-modifying action, including branch creation, file writes, commits, and pushes.

A task must stop and report `BLOCKED` if any of the following are true:

- the repo path is wrong
- `origin` is missing
- `origin` points anywhere other than `https://github.com/sfayka/Harness.git`
- `.codex-bootstrap-proof` is missing
- fetch, authentication, or bootstrap completion has not succeeded

The preflight contract is intentionally strict. It prevents delegated work from proceeding on a sandbox that only looks plausible but is not actually connected to the external repository state Harness relies on.

Successful preflight validation is a prerequisite for any lifecycle transition from `assigned` to `in_progress`.

## Completion Artifact Contract

A Codex Cloud task is not complete unless it returns concrete external artifact identifiers:

- `Repository`
- `Branch`
- `Commit SHA`
- `PR URL`

These identifiers are the minimum operator-facing proof that the claimed work exists outside the executor summary. If those identifiers do not exist, the task is not complete regardless of how confident the executor summary sounds.

If `Repository`, `Branch`, `Commit SHA`, and `PR URL` are not all present, the task is considered invalid and not executed (not partial and not completed with issues).

Harness now enforces an earlier execution gate for attempt-shaped truth:

- a successful code-bearing attempt must at least prove current-run `Repository`, `Branch`, and `Commit SHA`
- if that minimum proof is missing or internally contradictory, Harness classifies the run as `invalid_execution_attempt`
- invalid execution attempts are retried with a bounded budget before completion handling continues
- exhausted invalid attempts transition the task to `failed`

This does not replace `missing_pr_after_execution`.

- `invalid_execution_attempt` means Harness does not trust that the current run produced a real code-bearing attempt yet
- `missing_pr_after_execution` means the current run is otherwise real and identifiable, but the PR artifact still needs governed recovery

This is consistent with Harness architecture:

- executor summaries are advisory
- external artifacts are completion evidence
- control-plane truth depends on evidence and reconciliation, not on claims alone

## Relationship To Harness Control-Plane Truth

This execution contract reinforces the core Harness distinction between execution claims and canonical truth.

Bootstrap proof answers the question, "did this delegated task start in the expected execution context?"

Completion artifacts answer the question, "what externally verifiable repository evidence exists for the claimed work?"

Harness still owns the final control-plane judgment. Even with a correct bootstrap and concrete repository artifacts, lifecycle acceptance remains evidence-backed and policy-enforced rather than inferred from executor confidence.

## Current Adapter Boundary

Harness now includes a Codex Cloud executor adapter implementation in [`modules/adapters/codex_cloud/executor_adapter.py`](../../modules/adapters/codex_cloud/executor_adapter.py).

That adapter does two narrow things:

- projects canonical `ExecutorDispatchInput` into a Codex Cloud execution request that includes the required bootstrap and preflight commands
- refuses to emit a successful advisory completion path unless the runtime response proves the expected repo root, canonical `origin`, and non-empty bootstrap proof

If the runtime response fails that preflight contract, the adapter emits an auditable failed execution event instead of a successful completion claim.

This keeps the contract aligned with Harness intent:

- environment proof is required before executor success can be taken seriously
- invalid preflight becomes auditable execution truth
- completion remains advisory until Harness verifies repository artifacts and external facts

The default local dispatch path still uses the stub executor unless a real Codex Cloud runtime client is injected. That is intentional. The adapter boundary is now real and test-covered, while live runtime transport remains a separate follow-on integration step.

## Known Failure Mode

The previously observed failure mode was:

- fresh Codex Cloud task sandboxes contained repository contents but no `origin`
- task summaries overstated completion when external artifacts did not actually exist
- interactive terminal success did not prove delegated task sandboxes were correctly bootstrapped

The fix was to make repository bootstrap repo-owned and explicit, then require task-level preflight output before work continues:

- `scripts/codex-cloud-setup.sh` establishes the repository, auth, and fetch prerequisites
- `.codex-bootstrap-proof` records that bootstrap completed in the expected environment
- raw preflight output proves the delegated task is running in that verified context
- completion remains tied to repository and GitHub artifacts rather than executor narrative

## Related Documents

- [runtime-execution-contract.md](runtime-execution-contract.md)
- [artifact-and-completion-evidence.md](artifact-and-completion-evidence.md)
