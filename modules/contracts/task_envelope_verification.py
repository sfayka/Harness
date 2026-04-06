"""Verification decision primitives for canonical TaskEnvelope completion policy."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import re

from modules.contracts.failure_classification import FailureClassification, classify_verification_outcome
from modules.contracts.task_envelope_evidence import CompletionEvidenceValidationResult
from modules.contracts.task_envelope_validation import assert_valid_task_envelope

TaskEnvelope = dict[str, object]
_OBSERVABLE_ACCEPTANCE_HINTS = (
    "api",
    "artifact",
    "branch",
    "build",
    "command",
    "commit",
    "dashboard",
    "document",
    "endpoint",
    "evidence",
    "external facts",
    "file",
    "github",
    "issue",
    "linear",
    "log",
    "output",
    "page",
    "pull request",
    "read-model",
    "read model",
    "reconcile",
    "reconciled",
    "reevaluate",
    "reevaluation",
    "response",
    "route",
    "schema",
    "screenshot",
    "status code",
    "test",
    "timeline",
    "url",
    "verification",
)
_GENERIC_VAGUE_PHRASES = (
    "works",
    "working",
    "done",
    "complete",
    "completed",
    "correct",
    "correctly",
    "proper",
    "properly",
    "looks good",
    "good quality",
    "high quality",
    "without bugs",
    "bug free",
    "production ready",
    "ready for production",
    "clean code",
    "well written",
)
_TAUTOLOGICAL_SUCCESS_PHRASES = (
    "task satisfies declared acceptance criteria",
    "successful completion means the task is complete",
    "the task is done",
)


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
class AcceptanceCriteriaAssessment:
    """Conservative automatic-completion safety check for acceptance criteria quality."""

    automatic_completion_safe: bool
    required_criteria_count: int
    concrete_required_criteria_count: int
    flagged_criteria: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()


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
    acceptance_criteria_assessment: AcceptanceCriteriaAssessment
    reasons: tuple[str, ...]
    failure_classification: FailureClassification


def _base_reasons(task_id: str, decision_input: VerificationDecisionInput) -> list[str]:
    reasons = [f"Verification evaluated task {task_id!r} against canonical completion policy"]
    if decision_input.runtime_facts.executor_reported_success:
        reasons.append("Executor-reported success was treated as advisory input only")
    if decision_input.runtime_facts.executor_reported_failure:
        reasons.append("Runtime reported execution failure")
    return reasons


def _evidence_insufficiency_reasons(
    task_envelope: TaskEnvelope,
    evidence_result: CompletionEvidenceValidationResult,
) -> tuple[str, ...]:
    evidence = dict(task_envelope.get("artifacts", {}).get("completion_evidence", {}) or {})
    policy = evidence.get("policy")
    status = evidence.get("status")

    if evidence_result.missing_required_artifact_types:
        missing = ", ".join(sorted(evidence_result.missing_required_artifact_types))
        return (f"Completion evidence is missing required artifact types: {missing}",)

    if policy == "deferred":
        return ("Completion evidence policy is deferred and does not yet authorize completion",)

    if policy == "required" and status != "satisfied":
        return (f"Completion evidence uses required policy but status is {status!r}",)

    if policy == "not_applicable":
        return ("Completion evidence policy is not_applicable and does not authorize completion",)

    if policy == "required" and not evidence_result.validated_artifact_ids:
        return ("Required completion evidence does not cite any validated artifact ids",)

    return ("Validated evidence is not sufficient for the declared evidence policy",)


def _normalize_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().lower().split())


def _looks_concrete_enough(description: str) -> bool:
    normalized = _normalize_text(description)
    if not normalized:
        return False
    if any(phrase in normalized for phrase in _TAUTOLOGICAL_SUCCESS_PHRASES):
        return False

    words = re.findall(r"[a-z0-9_/.\-]+", normalized)
    if len(words) < 5:
        return False

    has_anchor = any(hint in normalized for hint in _OBSERVABLE_ACCEPTANCE_HINTS)
    has_structural_signal = (
        any(char.isdigit() for char in normalized)
        or "`" in description
        or "/" in description
        or "_" in normalized
        or "-" in normalized
    )
    if has_anchor or has_structural_signal:
        return True

    return not any(phrase in normalized for phrase in _GENERIC_VAGUE_PHRASES)


def assess_acceptance_criteria(task_envelope: TaskEnvelope) -> AcceptanceCriteriaAssessment:
    """Assess whether required acceptance criteria are concrete enough for automatic completion."""

    acceptance_criteria = task_envelope.get("acceptance_criteria")
    required_items = (
        [
            criterion
            for criterion in acceptance_criteria
            if isinstance(criterion, dict) and criterion.get("required", True) is not False
        ]
        if isinstance(acceptance_criteria, list)
        else []
    )

    concrete_count = 0
    flagged: list[str] = []
    for criterion in required_items:
        criterion_id = str(criterion.get("id") or "acceptance-criterion")
        description = str(criterion.get("description") or "")
        if _looks_concrete_enough(description):
            concrete_count += 1
            continue
        flagged.append(f"{criterion_id}: {description}")

    reasons: list[str] = []
    if required_items and concrete_count == 0:
        reasons.append(
            "Required acceptance criteria are too vague for automatic completion and need more observable success conditions."
        )
        if flagged:
            reasons.append("Flagged criteria: " + "; ".join(flagged))

    success_signal = _normalize_text(((task_envelope.get("objective") or {}).get("success_signal")))
    if reasons and success_signal and any(phrase in success_signal for phrase in _TAUTOLOGICAL_SUCCESS_PHRASES):
        reasons.append("Objective success signal is tautological and does not add measurable completion evidence.")

    return AcceptanceCriteriaAssessment(
        automatic_completion_safe=not reasons,
        required_criteria_count=len(required_items),
        concrete_required_criteria_count=concrete_count,
        flagged_criteria=tuple(flagged),
        reasons=tuple(reasons),
    )


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
    acceptance_criteria_assessment = assess_acceptance_criteria(task_envelope)

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
        outcome = VerificationOutcome.VERIFICATION_DEFERRED
        return VerificationDecisionResult(
            task_id=task_id,
            outcome=outcome,
            target_status=None,
            claimed_completion=False,
            accepted_completion=False,
            requires_review=False,
            is_terminal=False,
            verification_passed=False,
            evidence_is_valid=evidence_result.is_valid,
            evidence_is_sufficient=evidence_result.is_sufficient,
            reconciliation_status=decision_input.reconciliation_facts.status,
            acceptance_criteria_assessment=acceptance_criteria_assessment,
            reasons=tuple(reasons),
            failure_classification=classify_verification_outcome(
                outcome=outcome,
                runtime_failure_observed=decision_input.runtime_facts.executor_reported_failure,
                reason=reasons[-1],
            ),
        )

    if decision_input.runtime_facts.terminal_failure:
        reasons.append("Runtime facts indicate terminal execution failure")
        outcome = VerificationOutcome.TERMINAL_INVALID
        return VerificationDecisionResult(
            task_id=task_id,
            outcome=outcome,
            target_status="failed",
            claimed_completion=True,
            accepted_completion=False,
            requires_review=False,
            is_terminal=True,
            verification_passed=False,
            evidence_is_valid=evidence_result.is_valid,
            evidence_is_sufficient=evidence_result.is_sufficient,
            reconciliation_status=decision_input.reconciliation_facts.status,
            acceptance_criteria_assessment=acceptance_criteria_assessment,
            reasons=tuple(reasons),
            failure_classification=classify_verification_outcome(
                outcome=outcome,
                runtime_failure_observed=decision_input.runtime_facts.executor_reported_failure,
                reason=reasons[-1],
            ),
        )

    if decision_input.review_reasons or decision_input.reconciliation_facts.status == ReconciliationStatus.REVIEW_REQUIRED:
        reasons.extend(decision_input.review_reasons)
        reasons.extend(decision_input.reconciliation_facts.reasons)
        reasons.append("Automatic verification cannot safely accept completion")
        outcome = VerificationOutcome.REVIEW_REQUIRED
        return VerificationDecisionResult(
            task_id=task_id,
            outcome=outcome,
            target_status="in_review",
            claimed_completion=True,
            accepted_completion=False,
            requires_review=True,
            is_terminal=False,
            verification_passed=False,
            evidence_is_valid=evidence_result.is_valid,
            evidence_is_sufficient=evidence_result.is_sufficient,
            reconciliation_status=decision_input.reconciliation_facts.status,
            acceptance_criteria_assessment=acceptance_criteria_assessment,
            reasons=tuple(reasons),
            failure_classification=classify_verification_outcome(
                outcome=outcome,
                runtime_failure_observed=decision_input.runtime_facts.executor_reported_failure,
                reason=reasons[-1],
            ),
        )

    if decision_input.reconciliation_facts.status == ReconciliationStatus.MISMATCH:
        reasons.extend(decision_input.reconciliation_facts.reasons)
        if decision_input.reconciliation_facts.terminal:
            reasons.append("External mismatch is terminal under verification policy")
            outcome = VerificationOutcome.TERMINAL_INVALID
            return VerificationDecisionResult(
                task_id=task_id,
                outcome=outcome,
                target_status="failed",
                claimed_completion=True,
                accepted_completion=False,
                requires_review=False,
                is_terminal=True,
                verification_passed=False,
                evidence_is_valid=evidence_result.is_valid,
                evidence_is_sufficient=evidence_result.is_sufficient,
                reconciliation_status=decision_input.reconciliation_facts.status,
                acceptance_criteria_assessment=acceptance_criteria_assessment,
                reasons=tuple(reasons),
                failure_classification=classify_verification_outcome(
                    outcome=outcome,
                    runtime_failure_observed=decision_input.runtime_facts.executor_reported_failure,
                    reason=reasons[-1],
                ),
            )

        reasons.append("External mismatch prevents completion from being preserved")
        outcome = VerificationOutcome.EXTERNAL_MISMATCH
        return VerificationDecisionResult(
            task_id=task_id,
            outcome=outcome,
            target_status="blocked",
            claimed_completion=True,
            accepted_completion=False,
            requires_review=False,
            is_terminal=False,
            verification_passed=False,
            evidence_is_valid=evidence_result.is_valid,
            evidence_is_sufficient=evidence_result.is_sufficient,
            reconciliation_status=decision_input.reconciliation_facts.status,
            acceptance_criteria_assessment=acceptance_criteria_assessment,
            reasons=tuple(reasons),
            failure_classification=classify_verification_outcome(
                outcome=outcome,
                runtime_failure_observed=decision_input.runtime_facts.executor_reported_failure,
                reason=reasons[-1],
            ),
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
        outcome = VerificationOutcome.BLOCKED_UNRESOLVED_CONDITIONS
        return VerificationDecisionResult(
            task_id=task_id,
            outcome=outcome,
            target_status="blocked",
            claimed_completion=True,
            accepted_completion=False,
            requires_review=False,
            is_terminal=False,
            verification_passed=False,
            evidence_is_valid=evidence_result.is_valid,
            evidence_is_sufficient=evidence_result.is_sufficient,
            reconciliation_status=decision_input.reconciliation_facts.status,
            acceptance_criteria_assessment=acceptance_criteria_assessment,
            reasons=tuple(reasons),
            failure_classification=classify_verification_outcome(
                outcome=outcome,
                runtime_failure_observed=decision_input.runtime_facts.executor_reported_failure,
                reason=reasons[-1],
            ),
        )

    if not decision_input.acceptance_criteria_satisfied:
        reasons.append("Acceptance criteria are not yet satisfied strongly enough for completion")
        outcome = VerificationOutcome.BLOCKED_UNRESOLVED_CONDITIONS
        return VerificationDecisionResult(
            task_id=task_id,
            outcome=outcome,
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
            failure_classification=classify_verification_outcome(
                outcome=outcome,
                runtime_failure_observed=decision_input.runtime_facts.executor_reported_failure,
                reason=reasons[-1],
            ),
        )

    if not evidence_result.is_sufficient:
        reasons.extend(_evidence_insufficiency_reasons(task_envelope, evidence_result))
        outcome = VerificationOutcome.INSUFFICIENT_EVIDENCE
        return VerificationDecisionResult(
            task_id=task_id,
            outcome=outcome,
            target_status="blocked",
            claimed_completion=True,
            accepted_completion=False,
            requires_review=False,
            is_terminal=False,
            verification_passed=False,
            evidence_is_valid=evidence_result.is_valid,
            evidence_is_sufficient=False,
            reconciliation_status=decision_input.reconciliation_facts.status,
            acceptance_criteria_assessment=acceptance_criteria_assessment,
            reasons=tuple(reasons),
            failure_classification=classify_verification_outcome(
                outcome=outcome,
                runtime_failure_observed=decision_input.runtime_facts.executor_reported_failure,
                reason=reasons[-1],
            ),
        )

    if not acceptance_criteria_assessment.automatic_completion_safe:
        reasons.extend(acceptance_criteria_assessment.reasons)
        reasons.append("Automatic verification cannot safely accept completion on vague acceptance criteria.")
        outcome = VerificationOutcome.REVIEW_REQUIRED
        return VerificationDecisionResult(
            task_id=task_id,
            outcome=outcome,
            target_status="in_review",
            claimed_completion=True,
            accepted_completion=False,
            requires_review=True,
            is_terminal=False,
            verification_passed=False,
            evidence_is_valid=evidence_result.is_valid,
            evidence_is_sufficient=evidence_result.is_sufficient,
            reconciliation_status=decision_input.reconciliation_facts.status,
            acceptance_criteria_assessment=acceptance_criteria_assessment,
            reasons=tuple(reasons),
            failure_classification=classify_verification_outcome(
                outcome=outcome,
                runtime_failure_observed=decision_input.runtime_facts.executor_reported_failure,
                reason=reasons[-1],
            ),
        )

    reasons.append("Acceptance criteria, evidence, and reconciliation all support completion")
    outcome = VerificationOutcome.ACCEPTED_COMPLETION
    return VerificationDecisionResult(
        task_id=task_id,
        outcome=outcome,
        target_status="completed",
        claimed_completion=True,
        accepted_completion=True,
        requires_review=False,
        is_terminal=False,
        verification_passed=True,
        evidence_is_valid=evidence_result.is_valid,
        evidence_is_sufficient=evidence_result.is_sufficient,
        reconciliation_status=decision_input.reconciliation_facts.status,
        acceptance_criteria_assessment=acceptance_criteria_assessment,
        reasons=tuple(reasons),
        failure_classification=classify_verification_outcome(
            outcome=outcome,
            runtime_failure_observed=decision_input.runtime_facts.executor_reported_failure,
            reason=reasons[-1],
        ),
    )


__all__ = [
    "AcceptanceCriteriaAssessment",
    "ReconciliationFacts",
    "ReconciliationStatus",
    "RuntimeVerificationFacts",
    "VerificationDecisionError",
    "VerificationDecisionInput",
    "VerificationDecisionResult",
    "VerificationInputError",
    "VerificationOutcome",
    "assess_acceptance_criteria",
    "evaluate_verification_decision",
]
