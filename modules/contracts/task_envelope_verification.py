"""Verification decision primitives for canonical TaskEnvelope completion policy."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from modules.contracts.task_envelope_evidence import CompletionEvidenceValidationResult
from modules.contracts.task_envelope_validation import assert_valid_task_envelope

TaskEnvelope = dict[str, object]


class VerificationOutcome(StrEnum):
    """Canonical verification outcome classes.

    VERIFICATION_DEFERRED means verification cannot yet make a final policy
    decision at all. It does not direct a lifecycle move by itself.

    BLOCKED_UNRESOLVED_CONDITIONS means verification has enough context to
    recommend the control-plane outcome remain blocked until specific missing
    conditions are resolved.
    """

    ACCEPTED_COMPLETION = "accepted_completion"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    EXTERNAL_MISMATCH = "external_mismatch"
    REVIEW_REQUIRED = "review_required"
    BLOCKED_UNRESOLVED_CONDITIONS = "blocked_unresolved_conditions"
    TERMINAL_INVALID = "terminal_invalid"
    VERIFICATION_DEFERRED = "verification_deferred"


class ReconciliationStatus(StrEnum):
    """Normalized reconciliation statuses that verification consumes."""

    PASSED = "passed"
    PENDING = "pending"
    MISMATCH = "mismatch"
    REVIEW_REQUIRED = "review_required"
    NOT_APPLICABLE = "not_applicable"


class VerificationDecisionError(ValueError):
    """Base error for invalid verification decision attempts."""


class VerificationInputError(VerificationDecisionError):
    """Raised when verification inputs are malformed or contradictory."""


@dataclass(frozen=True)
class RuntimeVerificationFacts:
    """Normalized runtime facts consumed by verification."""

    executor_reported_success: bool = False
    executor_reported_failure: bool = False
    terminal_failure: bool = False
    attempt_count: int = 0
    latest_attempt_outcome: str | None = None


@dataclass(frozen=True)
class ReconciliationFacts:
    """Normalized reconciliation facts consumed by verification."""

    status: ReconciliationStatus = ReconciliationStatus.PENDING
    blocking: bool = False
    terminal: bool = False
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class VerificationDecisionInput:
    """Structured input bundle for reusable verification evaluation."""

    claimed_completion: bool
    acceptance_criteria_satisfied: bool
    evidence_result: CompletionEvidenceValidationResult
    runtime_facts: RuntimeVerificationFacts = field(default_factory=RuntimeVerificationFacts)
    reconciliation_facts: ReconciliationFacts = field(default_factory=ReconciliationFacts)
    unresolved_conditions: tuple[str, ...] = ()
    review_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class VerificationDecisionResult:
    """Structured verification decision outcome."""

    task_id: str
    outcome: VerificationOutcome
    target_status: str | None
    claimed_completion: bool
    accepted_completion: bool
    requires_review: bool
    is_terminal: bool
    verification_passed: bool
    evidence_is_valid: bool
    evidence_is_sufficient: bool
    reconciliation_status: ReconciliationStatus
    reasons: tuple[str, ...]


def _base_reasons(task_id: str, decision_input: VerificationDecisionInput) -> list[str]:
    reasons = [f"Verification evaluated task {task_id!r} against canonical completion policy"]
    if decision_input.runtime_facts.executor_reported_success:
        reasons.append("Executor-reported success was treated as advisory input only")
    if decision_input.runtime_facts.executor_reported_failure:
        reasons.append("Runtime reported execution failure")
    return reasons


def evaluate_verification_decision(
    task_envelope: TaskEnvelope,
    *,
    decision_input: VerificationDecisionInput,
) -> VerificationDecisionResult:
    """Evaluate verification outcome for a task using normalized policy inputs."""

    assert_valid_task_envelope(task_envelope)

    task_id = str(task_envelope["id"])
    evidence_result = decision_input.evidence_result
    reasons = _base_reasons(task_id, decision_input)

    if not evidence_result.is_valid:
        raise VerificationInputError(
            "Verification requires structurally valid evidence inputs; "
            "run evidence validation and resolve invalid evidence before policy evaluation"
        )

    if decision_input.reconciliation_facts.terminal and decision_input.reconciliation_facts.status != ReconciliationStatus.MISMATCH:
        raise VerificationInputError("Terminal reconciliation facts require mismatch status")

    if decision_input.review_reasons and decision_input.reconciliation_facts.status == ReconciliationStatus.PASSED:
        reasons.append("Manual-review requirement was raised independently of reconciliation")

    if not decision_input.claimed_completion:
        # No completion claim means verification is not yet in a position to make
        # a final completion-policy decision. This is deferred evaluation, not a
        # blocked control-plane outcome.
        reasons.append("No completion claim is currently being evaluated")
        return VerificationDecisionResult(
            task_id=task_id,
            outcome=VerificationOutcome.VERIFICATION_DEFERRED,
            target_status=None,
            claimed_completion=False,
            accepted_completion=False,
            requires_review=False,
            is_terminal=False,
            verification_passed=False,
            evidence_is_valid=evidence_result.is_valid,
            evidence_is_sufficient=evidence_result.is_sufficient,
            reconciliation_status=decision_input.reconciliation_facts.status,
            reasons=tuple(reasons),
        )

    if decision_input.runtime_facts.terminal_failure:
        reasons.append("Runtime facts indicate terminal execution failure")
        return VerificationDecisionResult(
            task_id=task_id,
            outcome=VerificationOutcome.TERMINAL_INVALID,
            target_status="failed",
            claimed_completion=True,
            accepted_completion=False,
            requires_review=False,
            is_terminal=True,
            verification_passed=False,
            evidence_is_valid=evidence_result.is_valid,
            evidence_is_sufficient=evidence_result.is_sufficient,
            reconciliation_status=decision_input.reconciliation_facts.status,
            reasons=tuple(reasons),
        )

    if decision_input.review_reasons or decision_input.reconciliation_facts.status == ReconciliationStatus.REVIEW_REQUIRED:
        reasons.extend(decision_input.review_reasons)
        reasons.extend(decision_input.reconciliation_facts.reasons)
        reasons.append("Automatic verification cannot safely accept completion")
        return VerificationDecisionResult(
            task_id=task_id,
            outcome=VerificationOutcome.REVIEW_REQUIRED,
            target_status="in_review",
            claimed_completion=True,
            accepted_completion=False,
            requires_review=True,
            is_terminal=False,
            verification_passed=False,
            evidence_is_valid=evidence_result.is_valid,
            evidence_is_sufficient=evidence_result.is_sufficient,
            reconciliation_status=decision_input.reconciliation_facts.status,
            reasons=tuple(reasons),
        )

    if decision_input.reconciliation_facts.status == ReconciliationStatus.MISMATCH:
        reasons.extend(decision_input.reconciliation_facts.reasons)
        if decision_input.reconciliation_facts.terminal:
            reasons.append("External mismatch is terminal under verification policy")
            return VerificationDecisionResult(
                task_id=task_id,
                outcome=VerificationOutcome.TERMINAL_INVALID,
                target_status="failed",
                claimed_completion=True,
                accepted_completion=False,
                requires_review=False,
                is_terminal=True,
                verification_passed=False,
                evidence_is_valid=evidence_result.is_valid,
                evidence_is_sufficient=evidence_result.is_sufficient,
                reconciliation_status=decision_input.reconciliation_facts.status,
                reasons=tuple(reasons),
            )

        reasons.append("External mismatch prevents completion from being preserved")
        return VerificationDecisionResult(
            task_id=task_id,
            outcome=VerificationOutcome.EXTERNAL_MISMATCH,
            target_status="blocked",
            claimed_completion=True,
            accepted_completion=False,
            requires_review=False,
            is_terminal=False,
            verification_passed=False,
            evidence_is_valid=evidence_result.is_valid,
            evidence_is_sufficient=evidence_result.is_sufficient,
            reconciliation_status=decision_input.reconciliation_facts.status,
            reasons=tuple(reasons),
        )

    unresolved_conditions = list(decision_input.unresolved_conditions)
    if decision_input.reconciliation_facts.status == ReconciliationStatus.PENDING:
        unresolved_conditions.append("Reconciliation is still pending")

    if unresolved_conditions:
        # At this point there is an active completion claim, but verification has
        # identified concrete unresolved conditions. The control-plane outcome
        # should therefore remain blocked rather than merely deferred.
        reasons.extend(unresolved_conditions)
        reasons.append("Verification is blocked by unresolved conditions")
        return VerificationDecisionResult(
            task_id=task_id,
            outcome=VerificationOutcome.BLOCKED_UNRESOLVED_CONDITIONS,
            target_status="blocked",
            claimed_completion=True,
            accepted_completion=False,
            requires_review=False,
            is_terminal=False,
            verification_passed=False,
            evidence_is_valid=evidence_result.is_valid,
            evidence_is_sufficient=evidence_result.is_sufficient,
            reconciliation_status=decision_input.reconciliation_facts.status,
            reasons=tuple(reasons),
        )

    if not decision_input.acceptance_criteria_satisfied:
        reasons.append("Acceptance criteria are not yet satisfied strongly enough for completion")
        return VerificationDecisionResult(
            task_id=task_id,
            outcome=VerificationOutcome.BLOCKED_UNRESOLVED_CONDITIONS,
            target_status="blocked",
            claimed_completion=True,
            accepted_completion=False,
            requires_review=False,
            is_terminal=False,
            verification_passed=False,
            evidence_is_valid=evidence_result.is_valid,
            evidence_is_sufficient=evidence_result.is_sufficient,
            reconciliation_status=decision_input.reconciliation_facts.status,
            reasons=tuple(reasons),
        )

    if not evidence_result.is_sufficient:
        reasons.append("Validated evidence is not sufficient for the declared evidence policy")
        return VerificationDecisionResult(
            task_id=task_id,
            outcome=VerificationOutcome.INSUFFICIENT_EVIDENCE,
            target_status="blocked",
            claimed_completion=True,
            accepted_completion=False,
            requires_review=False,
            is_terminal=False,
            verification_passed=False,
            evidence_is_valid=evidence_result.is_valid,
            evidence_is_sufficient=False,
            reconciliation_status=decision_input.reconciliation_facts.status,
            reasons=tuple(reasons),
        )

    reasons.append("Acceptance criteria, evidence, and reconciliation all support completion")
    return VerificationDecisionResult(
        task_id=task_id,
        outcome=VerificationOutcome.ACCEPTED_COMPLETION,
        target_status="completed",
        claimed_completion=True,
        accepted_completion=True,
        requires_review=False,
        is_terminal=False,
        verification_passed=True,
        evidence_is_valid=evidence_result.is_valid,
        evidence_is_sufficient=evidence_result.is_sufficient,
        reconciliation_status=decision_input.reconciliation_facts.status,
        reasons=tuple(reasons),
    )


__all__ = [
    "ReconciliationFacts",
    "ReconciliationStatus",
    "RuntimeVerificationFacts",
    "VerificationDecisionError",
    "VerificationDecisionInput",
    "VerificationDecisionResult",
    "VerificationInputError",
    "VerificationOutcome",
    "evaluate_verification_decision",
]
