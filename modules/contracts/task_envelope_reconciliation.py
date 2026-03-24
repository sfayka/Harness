"""Reconciliation evaluation primitives for canonical TaskEnvelope state."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from modules.contracts.task_envelope_validation import assert_valid_task_envelope
from modules.contracts.task_envelope_verification import ReconciliationFacts, ReconciliationStatus

TaskEnvelope = dict[str, object]


class ReconciliationOutcome(StrEnum):
    """Canonical reconciliation outcome classes.

    RECONCILIATION_PENDING means reconciliation cannot yet judge the task
    because external facts are still pending or unavailable.

    MISSING_EVIDENCE means the expected evidence should exist by now under the
    declared task/evidence policy, but does not.
    """

    NO_MISMATCH = "no_mismatch"
    MISSING_EVIDENCE = "missing_evidence"
    WRONG_TARGET = "wrong_target"
    CONTRADICTORY_FACTS = "contradictory_facts"
    REVIEW_REQUIRED = "review_required"
    TERMINAL_INVALID = "terminal_invalid"
    RECONCILIATION_PENDING = "reconciliation_pending"


class MismatchCategory(StrEnum):
    """Canonical mismatch categories produced by reconciliation."""

    MISSING_REQUIRED_ARTIFACT = "missing_required_artifact"
    MISSING_VALIDATED_ARTIFACT = "missing_validated_artifact"
    GITHUB_ARTIFACT_NOT_FOUND = "github_artifact_not_found"
    LINEAR_RECORD_NOT_FOUND = "linear_record_not_found"
    LINEAR_STATE_CONFLICT = "linear_state_conflict"
    GITHUB_REVIEW_CONFLICT = "github_review_conflict"
    WRONG_REPOSITORY = "wrong_repository"
    WRONG_BRANCH = "wrong_branch"
    CHANGED_FILES_CONFLICT = "changed_files_conflict"
    COMPLETION_WITHOUT_RECONCILIATION = "completion_without_reconciliation"
    EVIDENCE_POLICY_CONFLICT = "evidence_policy_conflict"


class ReconciliationEvaluationError(ValueError):
    """Base error for invalid reconciliation evaluation attempts."""


class ReconciliationInputError(ReconciliationEvaluationError):
    """Raised when normalized reconciliation inputs are malformed or contradictory."""


@dataclass(frozen=True)
class ExpectedCodeContext:
    """Expected repository and branch context for code-bearing reconciliation."""

    repository_host: str
    repository_owner: str
    repository_name: str
    branch_name: str | None = None
    base_branch: str | None = None


@dataclass(frozen=True)
class GitHubArtifactFacts:
    """Normalized GitHub facts consumed by reconciliation."""

    artifact_found: bool = True
    repository_host: str | None = None
    repository_owner: str | None = None
    repository_name: str | None = None
    branch_name: str | None = None
    pull_request_found: bool | None = None
    commit_found: bool | None = None
    review_state: str | None = None
    changed_files_match: bool | None = None
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class LinearFacts:
    """Normalized Linear facts consumed by reconciliation."""

    record_found: bool = True
    state: str | None = None
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReconciliationEvaluationInput:
    """Structured reconciliation input bundle."""

    claimed_completion: bool
    evidence_policy: str
    evidence_status: str
    expected_code_context: ExpectedCodeContext | None = None
    github_facts: GitHubArtifactFacts | None = None
    linear_facts: LinearFacts | None = None
    review_reasons: tuple[str, ...] = ()
    pending_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReconciliationResult:
    """Structured reconciliation result suitable for later verification input."""

    task_id: str
    outcome: ReconciliationOutcome
    status: ReconciliationStatus
    blocking: bool
    terminal: bool
    mismatch_categories: tuple[MismatchCategory, ...]
    reasons: tuple[str, ...]

    def to_verification_facts(self) -> ReconciliationFacts:
        """Convert reconciliation result into verification-consumable facts."""

        return ReconciliationFacts(
            status=self.status,
            blocking=self.blocking,
            terminal=self.terminal,
            reasons=self.reasons,
        )


def _append_category(
    categories: list[MismatchCategory],
    reasons: list[str],
    *,
    category: MismatchCategory,
    reason: str,
) -> None:
    if category not in categories:
        categories.append(category)
    reasons.append(reason)


def _repo_matches(expected: ExpectedCodeContext, github: GitHubArtifactFacts) -> bool:
    return (
        github.repository_host == expected.repository_host
        and github.repository_owner == expected.repository_owner
        and github.repository_name == expected.repository_name
    )


def evaluate_reconciliation(
    task_envelope: TaskEnvelope,
    *,
    reconciliation_input: ReconciliationEvaluationInput,
) -> ReconciliationResult:
    """Evaluate reconciliation outcome for a task using normalized external facts."""

    assert_valid_task_envelope(task_envelope)

    task_id = str(task_envelope["id"])
    reasons = [f"Reconciliation evaluated task {task_id!r} against normalized external facts"]
    categories: list[MismatchCategory] = []
    github_facts = reconciliation_input.github_facts
    linear_facts = reconciliation_input.linear_facts
    expected_code_context = reconciliation_input.expected_code_context

    if reconciliation_input.review_reasons and reconciliation_input.pending_reasons:
        raise ReconciliationInputError("Review-required and pending reconciliation reasons must not be mixed")

    if reconciliation_input.evidence_policy == "required" and reconciliation_input.evidence_status == "not_applicable":
        raise ReconciliationInputError("Required evidence policy cannot be paired with not_applicable evidence status")

    if reconciliation_input.pending_reasons:
        # Pending means the reconciliation layer still lacks enough external
        # facts to make a judgment. This is distinct from missing evidence,
        # where the required evidence should already exist but does not.
        reasons.extend(reconciliation_input.pending_reasons)
        return ReconciliationResult(
            task_id=task_id,
            outcome=ReconciliationOutcome.RECONCILIATION_PENDING,
            status=ReconciliationStatus.PENDING,
            blocking=False,
            terminal=False,
            mismatch_categories=(),
            reasons=tuple(reasons),
        )

    if reconciliation_input.review_reasons:
        reasons.extend(reconciliation_input.review_reasons)
        reasons.append("External facts require manual review before reconciliation can pass")
        return ReconciliationResult(
            task_id=task_id,
            outcome=ReconciliationOutcome.REVIEW_REQUIRED,
            status=ReconciliationStatus.REVIEW_REQUIRED,
            blocking=True,
            terminal=False,
            mismatch_categories=(),
            reasons=tuple(reasons),
        )

    if reconciliation_input.claimed_completion and reconciliation_input.evidence_policy == "required":
        if reconciliation_input.evidence_status in {"deferred", "pending", "insufficient"}:
            category = (
                MismatchCategory.MISSING_REQUIRED_ARTIFACT
                if reconciliation_input.evidence_status in {"deferred", "pending"}
                else MismatchCategory.MISSING_VALIDATED_ARTIFACT
            )
            _append_category(
                categories,
                reasons,
                category=category,
                reason="Claimed completion is missing required validated evidence support",
            )
            return ReconciliationResult(
                task_id=task_id,
                outcome=ReconciliationOutcome.MISSING_EVIDENCE,
                status=ReconciliationStatus.MISMATCH,
                blocking=True,
                terminal=False,
                mismatch_categories=tuple(categories),
                reasons=tuple(reasons),
            )

    if github_facts and not github_facts.artifact_found:
        _append_category(
            categories,
            reasons,
            category=MismatchCategory.GITHUB_ARTIFACT_NOT_FOUND,
            reason="Expected GitHub artifact facts could not be found",
        )
        return ReconciliationResult(
            task_id=task_id,
            outcome=ReconciliationOutcome.MISSING_EVIDENCE,
            status=ReconciliationStatus.MISMATCH,
            blocking=True,
            terminal=False,
            mismatch_categories=tuple(categories),
            reasons=tuple(reasons),
        )

    if linear_facts and not linear_facts.record_found:
        _append_category(
            categories,
            reasons,
            category=MismatchCategory.LINEAR_RECORD_NOT_FOUND,
            reason="Expected Linear record could not be found",
        )
        return ReconciliationResult(
            task_id=task_id,
            outcome=ReconciliationOutcome.REVIEW_REQUIRED,
            status=ReconciliationStatus.REVIEW_REQUIRED,
            blocking=True,
            terminal=False,
            mismatch_categories=tuple(categories),
            reasons=tuple(reasons),
        )

    if expected_code_context and github_facts:
        if not _repo_matches(expected_code_context, github_facts):
            _append_category(
                categories,
                reasons,
                category=MismatchCategory.WRONG_REPOSITORY,
                reason="GitHub evidence points to a different repository than expected",
            )
        if expected_code_context.branch_name and github_facts.branch_name != expected_code_context.branch_name:
            _append_category(
                categories,
                reasons,
                category=MismatchCategory.WRONG_BRANCH,
                reason="GitHub evidence points to a different branch than expected",
            )
        if categories:
            return ReconciliationResult(
                task_id=task_id,
                outcome=ReconciliationOutcome.WRONG_TARGET,
                status=ReconciliationStatus.MISMATCH,
                blocking=True,
                terminal=True,
                mismatch_categories=tuple(categories),
                reasons=tuple(reasons),
            )

    if github_facts and github_facts.review_state == "changes_requested" and reconciliation_input.claimed_completion:
        _append_category(
            categories,
            reasons,
            category=MismatchCategory.GITHUB_REVIEW_CONFLICT,
            reason="GitHub review state conflicts with a claimed completed outcome",
        )

    if github_facts and github_facts.changed_files_match is False:
        _append_category(
            categories,
            reasons,
            category=MismatchCategory.CHANGED_FILES_CONFLICT,
            reason="Changed-file evidence conflicts with the task's expected code scope",
        )

    internal_status = str(task_envelope["status"])
    if linear_facts and linear_facts.state:
        linear_done_states = {"done", "completed", "canceled"}
        harness_done_states = {"completed", "canceled", "failed"}
        if internal_status == "completed" and linear_facts.state not in linear_done_states:
            _append_category(
                categories,
                reasons,
                category=MismatchCategory.LINEAR_STATE_CONFLICT,
                reason="Harness marks the task completed while Linear still reports active work",
            )
        elif internal_status in {"executing", "assigned", "planned", "dispatch_ready", "blocked"} and linear_facts.state == "completed":
            _append_category(
                categories,
                reasons,
                category=MismatchCategory.LINEAR_STATE_CONFLICT,
                reason="Linear reports completion while Harness does not",
            )
        elif internal_status in harness_done_states and linear_facts.state == "in_progress" and internal_status != "failed":
            _append_category(
                categories,
                reasons,
                category=MismatchCategory.LINEAR_STATE_CONFLICT,
                reason="Linear state conflicts with Harness terminal state",
            )

    if reconciliation_input.claimed_completion and reconciliation_input.evidence_policy == "required":
        if reconciliation_input.evidence_status != "satisfied":
            _append_category(
                categories,
                reasons,
                category=MismatchCategory.EVIDENCE_POLICY_CONFLICT,
                reason="Claimed completion conflicts with the task's required evidence policy",
            )

    if categories:
        return ReconciliationResult(
            task_id=task_id,
            outcome=ReconciliationOutcome.CONTRADICTORY_FACTS,
            status=ReconciliationStatus.MISMATCH,
            blocking=True,
            terminal=False,
            mismatch_categories=tuple(categories),
            reasons=tuple(reasons),
        )

    reasons.extend(github_facts.reasons if github_facts else ())
    reasons.extend(linear_facts.reasons if linear_facts else ())
    reasons.append("No blocking reconciliation mismatch was detected")
    return ReconciliationResult(
        task_id=task_id,
        outcome=ReconciliationOutcome.NO_MISMATCH,
        status=ReconciliationStatus.PASSED,
        blocking=False,
        terminal=False,
        mismatch_categories=(),
        reasons=tuple(reasons),
    )


__all__ = [
    "ExpectedCodeContext",
    "GitHubArtifactFacts",
    "LinearFacts",
    "MismatchCategory",
    "ReconciliationEvaluationError",
    "ReconciliationEvaluationInput",
    "ReconciliationInputError",
    "ReconciliationOutcome",
    "ReconciliationResult",
    "evaluate_reconciliation",
]
