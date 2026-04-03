"""Failure classification primitives for execution and evaluation outcomes."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

class FailureType(StrEnum):
    """Canonical machine-readable failure types."""

    NONE = "none"
    BOOTSTRAP_FAILURE = "bootstrap_failure"
    DISPATCH_FAILURE = "dispatch_failure"
    EXECUTOR_FAILURE = "executor_failure"
    CONTRACT_VIOLATION = "contract_violation"
    EVIDENCE_INSUFFICIENT = "evidence_insufficient"
    RECONCILIATION_MISMATCH = "reconciliation_mismatch"
    REVIEW_REQUIRED = "review_required"


class FailureSource(StrEnum):
    """System layer where failure truth was determined."""

    NONE = "none"
    DISPATCH = "dispatch"
    EXECUTOR = "executor"
    EVALUATION = "evaluation"


@dataclass(frozen=True)
class FailureClassification:
    """Explicit, auditable failure classification output."""

    failure_type: FailureType
    source: FailureSource
    reason: str
    terminal: bool
    recoverable: bool
    category: FailureType = field(init=False)
    retryable: bool = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "category", self.failure_type)
        object.__setattr__(self, "retryable", self.recoverable)


def classify_verification_outcome(
    *,
    outcome: str,
    runtime_failure_observed: bool,
    reason: str,
) -> FailureClassification:
    """Map verification outcomes to stable failure classes."""

    if outcome == "accepted_completion":
        return FailureClassification(
            failure_type=FailureType.NONE,
            source=FailureSource.NONE,
            reason=reason,
            terminal=False,
            recoverable=False,
        )

    if outcome == "verification_deferred":
        return FailureClassification(
            failure_type=FailureType.NONE,
            source=FailureSource.NONE,
            reason=reason,
            terminal=False,
            recoverable=False,
        )

    if outcome == "review_required":
        return FailureClassification(
            failure_type=FailureType.REVIEW_REQUIRED,
            source=FailureSource.EVALUATION,
            reason=reason,
            terminal=False,
            recoverable=False,
        )

    if outcome == "insufficient_evidence":
        return FailureClassification(
            failure_type=FailureType.EVIDENCE_INSUFFICIENT,
            source=FailureSource.EVALUATION,
            reason=reason,
            terminal=False,
            recoverable=False,
        )

    if outcome == "external_mismatch":
        return FailureClassification(
            failure_type=FailureType.RECONCILIATION_MISMATCH,
            source=FailureSource.EVALUATION,
            reason=reason,
            terminal=True,
            recoverable=False,
        )

    if outcome == "terminal_invalid" and runtime_failure_observed:
        return FailureClassification(
            failure_type=FailureType.EXECUTOR_FAILURE,
            source=FailureSource.EXECUTOR,
            reason=reason,
            terminal=True,
            recoverable=True,
        )

    if outcome in {"terminal_invalid", "blocked_unresolved_conditions"}:
        return FailureClassification(
            failure_type=FailureType.CONTRACT_VIOLATION,
            source=FailureSource.EVALUATION,
            reason=reason,
            terminal=outcome == "terminal_invalid",
            recoverable=False,
        )

    return FailureClassification(
        failure_type=FailureType.CONTRACT_VIOLATION,
        source=FailureSource.EVALUATION,
        reason=reason,
        terminal=False,
        recoverable=False,
    )


__all__ = [
    "FailureType",
    "FailureClassification",
    "FailureSource",
    "classify_verification_outcome",
]
