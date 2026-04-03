"""Failure classification primitives for execution and evaluation outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

class FailureCategory(StrEnum):
    """Stable failure categories used by retry and diagnosis workflows."""

    NONE = "none"
    ENVIRONMENT_BOOTSTRAP_FAILURE = "environment_bootstrap_failure"
    EXECUTOR_RUNTIME_FAILURE = "executor_runtime_failure"
    EXTERNAL_AVAILABILITY_FAILURE = "external_availability_failure"
    CONTRACT_VIOLATION = "contract_violation"
    ARTIFACT_VALIDATION_FAILURE = "artifact_validation_failure"
    EVIDENCE_INSUFFICIENCY = "evidence_insufficiency"
    RECONCILIATION_MISMATCH = "reconciliation_mismatch"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"


class FailureNature(StrEnum):
    """High-level class for retry and policy handling."""

    NONE = "none"
    TRANSIENT = "transient"
    SEMANTIC = "semantic"
    CONTRACT = "contract"


@dataclass(frozen=True)
class FailureClassification:
    """Explicit, auditable failure classification output."""

    category: FailureCategory
    nature: FailureNature
    retryable: bool
    reason: str


def classify_verification_outcome(
    *,
    outcome: str,
    runtime_failure_observed: bool,
    reason: str,
) -> FailureClassification:
    """Map verification outcomes to stable failure classes."""

    if outcome == "accepted_completion":
        return FailureClassification(
            category=FailureCategory.NONE,
            nature=FailureNature.NONE,
            retryable=False,
            reason=reason,
        )

    if outcome == "verification_deferred":
        return FailureClassification(
            category=FailureCategory.NONE,
            nature=FailureNature.NONE,
            retryable=False,
            reason=reason,
        )

    if outcome == "review_required":
        return FailureClassification(
            category=FailureCategory.MANUAL_REVIEW_REQUIRED,
            nature=FailureNature.SEMANTIC,
            retryable=False,
            reason=reason,
        )

    if outcome == "insufficient_evidence":
        return FailureClassification(
            category=FailureCategory.EVIDENCE_INSUFFICIENCY,
            nature=FailureNature.SEMANTIC,
            retryable=False,
            reason=reason,
        )

    if outcome == "external_mismatch":
        return FailureClassification(
            category=FailureCategory.RECONCILIATION_MISMATCH,
            nature=FailureNature.SEMANTIC,
            retryable=False,
            reason=reason,
        )

    if outcome == "terminal_invalid" and runtime_failure_observed:
        return FailureClassification(
            category=FailureCategory.EXECUTOR_RUNTIME_FAILURE,
            nature=FailureNature.TRANSIENT,
            retryable=True,
            reason=reason,
        )

    if outcome in {"terminal_invalid", "blocked_unresolved_conditions"}:
        return FailureClassification(
            category=FailureCategory.CONTRACT_VIOLATION,
            nature=FailureNature.CONTRACT,
            retryable=False,
            reason=reason,
        )

    return FailureClassification(
        category=FailureCategory.CONTRACT_VIOLATION,
        nature=FailureNature.CONTRACT,
        retryable=False,
        reason=reason,
    )


__all__ = [
    "FailureCategory",
    "FailureClassification",
    "FailureNature",
    "classify_verification_outcome",
]
