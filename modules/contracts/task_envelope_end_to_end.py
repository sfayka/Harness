"""End-to-end canonical enforcement helpers built on normalized external facts."""

from __future__ import annotations

from dataclasses import dataclass

from modules.contracts.task_envelope_enforcement import (
    EnforcementInput,
    EnforcementResult,
    enforce_task_envelope,
)
from modules.contracts.task_envelope_external_facts import (
    BranchFact,
    ChangedFilesSummary,
    CommitFact,
    GitHubArtifactFacts,
    LinearFacts,
    LinearProjectFact,
    LinearTaskReference,
    LinearWorkflowFact,
    PullRequestFact,
    RepositoryFact,
)
from modules.contracts.task_envelope_reconciliation import (
    ExpectedCodeContext,
    ReconciliationEvaluationInput,
)
from modules.contracts.task_envelope_review import ReviewDecisionResult, ReviewRequest
from modules.contracts.task_envelope_validation import assert_valid_task_envelope
from modules.contracts.task_envelope_verification import RuntimeVerificationFacts

TaskEnvelope = dict[str, object]


@dataclass(frozen=True)
class CanonicalExternalFactBundle:
    """Normalized external facts plus expected code context for reconciliation."""

    expected_code_context: ExpectedCodeContext | None = None
    github_facts: GitHubArtifactFacts | None = None
    linear_facts: LinearFacts | None = None


@dataclass(frozen=True)
class CanonicalCaseInput:
    """Canonical end-to-end enforcement input for representative task cases."""

    claimed_completion: bool = False
    acceptance_criteria_satisfied: bool = False
    runtime_facts: RuntimeVerificationFacts = RuntimeVerificationFacts()
    external_facts: CanonicalExternalFactBundle | None = None
    unresolved_conditions: tuple[str, ...] = ()
    review_reasons: tuple[str, ...] = ()
    review_request: ReviewRequest | None = None
    review_decision: ReviewDecisionResult | None = None


def build_expected_code_context(
    *,
    repository_host: str = "github.com",
    repository_owner: str = "sfayka",
    repository_name: str = "Harness",
    branch_name: str | None = "codex/end-to-end",
    base_branch: str | None = "main",
) -> ExpectedCodeContext:
    """Build a representative normalized expected code context."""

    return ExpectedCodeContext(
        repository_host=repository_host,
        repository_owner=repository_owner,
        repository_name=repository_name,
        branch_name=branch_name,
        base_branch=base_branch,
    )


def build_github_completion_facts(
    *,
    repository_host: str = "github.com",
    repository_owner: str = "sfayka",
    repository_name: str = "Harness",
    branch_name: str = "codex/end-to-end",
    base_branch: str | None = "main",
    commit_sha: str = "abcdef1234567890",
    pull_request_number: int = 200,
    review_state: str | None = "approved",
    artifact_found: bool = True,
    changed_files_match: bool | None = True,
    reasons: tuple[str, ...] = (),
) -> GitHubArtifactFacts:
    """Build representative normalized GitHub facts for canonical enforcement cases."""

    if not artifact_found:
        return GitHubArtifactFacts(artifact_found=False, reasons=reasons)

    return GitHubArtifactFacts(
        artifact_found=True,
        repository=RepositoryFact(
            host=repository_host,
            owner=repository_owner,
            name=repository_name,
        ),
        branch=BranchFact(
            name=branch_name,
            base_branch=base_branch,
            head_commit_sha=commit_sha,
        ),
        commit=CommitFact(sha=commit_sha),
        pull_request=PullRequestFact(number=pull_request_number, review_state=review_state),
        changed_files=ChangedFilesSummary(matches_expected_scope=changed_files_match),
        reasons=reasons,
    )


def build_linear_completion_facts(
    *,
    record_found: bool = True,
    issue_id: str = "lin-1",
    issue_key: str | None = None,
    state: str | None = "completed",
    workflow_id: str | None = None,
    workflow_name: str | None = None,
    workflow_state_type: str | None = None,
    project_id: str | None = None,
    project_name: str | None = None,
    harness_task_id: str | None = None,
    external_ref: str | None = None,
    reasons: tuple[str, ...] = (),
) -> LinearFacts:
    """Build representative normalized Linear facts for canonical enforcement cases."""

    if not record_found:
        return LinearFacts(record_found=False, reasons=reasons)

    workflow = None
    if workflow_id or workflow_name or workflow_state_type:
        workflow = LinearWorkflowFact(
            workflow_id=workflow_id or "workflow-default",
            workflow_name=workflow_name or state or "unknown",
            state_type=workflow_state_type,
        )

    project = None
    if project_id or project_name:
        project = LinearProjectFact(
            project_id=project_id or "project-default",
            project_name=project_name,
        )

    task_reference = None
    if harness_task_id or external_ref:
        task_reference = LinearTaskReference(
            harness_task_id=harness_task_id,
            external_ref=external_ref,
        )

    return LinearFacts(
        record_found=True,
        issue_id=issue_id,
        issue_key=issue_key,
        state=state,
        workflow=workflow,
        project=project,
        task_reference=task_reference,
        reasons=reasons,
    )


def build_canonical_fact_bundle(
    *,
    expected_code_context: ExpectedCodeContext | None = None,
    github_facts: GitHubArtifactFacts | None = None,
    linear_facts: LinearFacts | None = None,
) -> CanonicalExternalFactBundle:
    """Assemble normalized external facts for the end-to-end enforcement path."""

    return CanonicalExternalFactBundle(
        expected_code_context=expected_code_context,
        github_facts=github_facts,
        linear_facts=linear_facts,
    )


def _build_reconciliation_input(
    task_envelope: TaskEnvelope,
    *,
    claimed_completion: bool,
    external_facts: CanonicalExternalFactBundle,
) -> ReconciliationEvaluationInput:
    completion_evidence = task_envelope["artifacts"]["completion_evidence"]
    evidence_policy = str(completion_evidence["policy"])
    evidence_status = str(completion_evidence["status"])

    return ReconciliationEvaluationInput(
        claimed_completion=claimed_completion,
        evidence_policy=evidence_policy,
        evidence_status=evidence_status,
        expected_code_context=external_facts.expected_code_context,
        github_facts=external_facts.github_facts,
        linear_facts=external_facts.linear_facts,
    )


def enforce_canonical_task_case(
    task_envelope: TaskEnvelope,
    *,
    case_input: CanonicalCaseInput,
) -> EnforcementResult:
    """Evaluate a canonical TaskEnvelope end-to-end using normalized external facts only."""

    assert_valid_task_envelope(task_envelope)
    reconciliation_input = None
    if case_input.external_facts is not None:
        reconciliation_input = _build_reconciliation_input(
            task_envelope,
            claimed_completion=case_input.claimed_completion,
            external_facts=case_input.external_facts,
        )

    return enforce_task_envelope(
        task_envelope,
        enforcement_input=EnforcementInput(
            claimed_completion=case_input.claimed_completion,
            acceptance_criteria_satisfied=case_input.acceptance_criteria_satisfied,
            runtime_facts=case_input.runtime_facts,
            reconciliation_input=reconciliation_input,
            unresolved_conditions=case_input.unresolved_conditions,
            review_reasons=case_input.review_reasons,
            review_request=case_input.review_request,
            review_decision=case_input.review_decision,
        ),
    )


__all__ = [
    "CanonicalCaseInput",
    "CanonicalExternalFactBundle",
    "build_canonical_fact_bundle",
    "build_expected_code_context",
    "build_github_completion_facts",
    "build_linear_completion_facts",
    "enforce_canonical_task_case",
]
