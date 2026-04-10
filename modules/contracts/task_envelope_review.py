"""Manual review request and review record primitives for Harness."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any


class ReviewTrigger(StrEnum):
    """Canonical reasons for entering manual review."""

    VERIFICATION = "verification"
    RECONCILIATION = "reconciliation"
    CLARIFICATION = "clarification"
    RUNTIME_ANOMALY = "runtime_anomaly"
    OPERATOR_ESCALATION = "operator_escalation"


class ReviewOutcome(StrEnum):
    """Canonical manual-review outcomes."""

    ACCEPT_COMPLETION = "accept_completion"
    KEEP_BLOCKED = "keep_blocked"
    REJECT_COMPLETION = "reject_completion"
    REQUIRE_CLARIFICATION = "require_clarification"
    MARK_FAILED = "mark_failed"
    AUTHORIZE_REDISPATCH = "authorize_redispatch"
    AUTHORIZE_REPLAN = "authorize_replan"
    AUTHORIZE_RETRY = "authorize_retry"
    CANCEL_TASK = "cancel_task"


class ReviewFollowUpAction(StrEnum):
    """Non-lifecycle follow-up actions authorized by a review decision."""

    NONE = "none"
    CLARIFICATION = "clarification"
    REDISPATCH = "redispatch"
    REPLAN = "replan"
    RETRY = "retry"


class ReviewValidationError(ValueError):
    """Raised when a review request or review record is malformed."""


@dataclass(frozen=True)
class ReviewerIdentity:
    """Auditable reviewer identity."""

    reviewer_id: str
    reviewer_name: str
    authority_role: str


@dataclass(frozen=True)
class ReviewRequest:
    """Explicit manual-review request."""

    review_request_id: str
    task_id: str
    requested_at: str
    requested_by: str
    trigger: ReviewTrigger
    summary: str
    presented_sections: tuple[str, ...]
    allowed_outcomes: tuple[ReviewOutcome, ...]
    prior_review_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReviewRecord:
    """Auditable review decision record."""

    review_id: str
    review_request_id: str
    task_id: str
    reviewer: ReviewerIdentity
    reviewed_at: str
    outcome: ReviewOutcome
    reasoning: str
    authorized_target_status: str
    follow_up_action: ReviewFollowUpAction = ReviewFollowUpAction.NONE
    supersedes_review_id: str | None = None
    basis_refs: tuple[str, ...] = ()
    preserves_history: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReviewDecisionResult:
    """Structured review decision output for lifecycle and verification consumers."""

    request: ReviewRequest
    record: ReviewRecord
    recommended_target_status: str
    follow_up_action: ReviewFollowUpAction


_ALLOWED_STATUSES = {
    "intake_ready",
    "planned",
    "dispatch_ready",
    "assigned",
    "executing",
    "blocked",
    "in_review",
    "completed",
    "failed",
    "canceled",
}

_OUTCOME_TO_TARGET_STATUS: dict[ReviewOutcome, str] = {
    ReviewOutcome.ACCEPT_COMPLETION: "completed",
    ReviewOutcome.KEEP_BLOCKED: "blocked",
    ReviewOutcome.REJECT_COMPLETION: "blocked",
    ReviewOutcome.REQUIRE_CLARIFICATION: "blocked",
    ReviewOutcome.MARK_FAILED: "failed",
    ReviewOutcome.AUTHORIZE_REDISPATCH: "dispatch_ready",
    ReviewOutcome.AUTHORIZE_REPLAN: "planned",
    ReviewOutcome.AUTHORIZE_RETRY: "assigned",
    ReviewOutcome.CANCEL_TASK: "canceled",
}

_OUTCOME_TO_FOLLOW_UP: dict[ReviewOutcome, ReviewFollowUpAction] = {
    ReviewOutcome.ACCEPT_COMPLETION: ReviewFollowUpAction.NONE,
    ReviewOutcome.KEEP_BLOCKED: ReviewFollowUpAction.NONE,
    ReviewOutcome.REJECT_COMPLETION: ReviewFollowUpAction.NONE,
    ReviewOutcome.REQUIRE_CLARIFICATION: ReviewFollowUpAction.CLARIFICATION,
    ReviewOutcome.MARK_FAILED: ReviewFollowUpAction.NONE,
    ReviewOutcome.AUTHORIZE_REDISPATCH: ReviewFollowUpAction.REDISPATCH,
    ReviewOutcome.AUTHORIZE_REPLAN: ReviewFollowUpAction.REPLAN,
    ReviewOutcome.AUTHORIZE_RETRY: ReviewFollowUpAction.RETRY,
    ReviewOutcome.CANCEL_TASK: ReviewFollowUpAction.NONE,
}

_MAX_FUTURE_TIMESTAMP_SKEW = timedelta(hours=6)


def _iso_timestamp(value: datetime | str | None = None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    raise ReviewValidationError("Expected an ISO-8601 string, datetime, or None")


def _require_not_too_far_in_future(value: datetime | str, *, field_name: str) -> str:
    normalized = _iso_timestamp(value)
    parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    if parsed > now + _MAX_FUTURE_TIMESTAMP_SKEW:
        raise ReviewValidationError(f"{field_name} must not be more than 6 hours in the future")
    return normalized


def _require_not_earlier_than(
    value: datetime | str,
    *,
    floor: datetime | str,
    field_name: str,
    floor_field_name: str,
) -> str:
    normalized = _iso_timestamp(value)
    floor_normalized = _iso_timestamp(floor)
    parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    floor_parsed = datetime.fromisoformat(floor_normalized.replace("Z", "+00:00"))
    if parsed < floor_parsed:
        raise ReviewValidationError(f"{field_name} must not be earlier than {floor_field_name}")
    return normalized


def _require_non_empty(value: str, *, field_name: str) -> None:
    if not value or not value.strip():
        raise ReviewValidationError(f"{field_name} is required")


def validate_review_request(review_request: ReviewRequest) -> ReviewRequest:
    """Validate canonical manual-review request metadata."""

    _require_non_empty(review_request.review_request_id, field_name="review_request_id")
    _require_non_empty(review_request.task_id, field_name="task_id")
    _require_non_empty(review_request.requested_by, field_name="requested_by")
    _require_non_empty(review_request.summary, field_name="summary")
    _require_not_too_far_in_future(review_request.requested_at, field_name="requested_at")

    if not review_request.presented_sections:
        raise ReviewValidationError("presented_sections must include at least one reviewed information surface")
    if not review_request.allowed_outcomes:
        raise ReviewValidationError("allowed_outcomes must include at least one policy-allowed outcome")
    if len(set(review_request.allowed_outcomes)) != len(review_request.allowed_outcomes):
        raise ReviewValidationError("allowed_outcomes must not contain duplicates")

    return review_request


def validate_reviewer_identity(reviewer: ReviewerIdentity) -> ReviewerIdentity:
    """Validate auditable reviewer identity."""

    _require_non_empty(reviewer.reviewer_id, field_name="reviewer.reviewer_id")
    _require_non_empty(reviewer.reviewer_name, field_name="reviewer.reviewer_name")
    _require_non_empty(reviewer.authority_role, field_name="reviewer.authority_role")
    return reviewer


def resolve_review_request(
    review_request: ReviewRequest,
    *,
    review_id: str,
    reviewer: ReviewerIdentity,
    outcome: ReviewOutcome,
    reasoning: str,
    reviewed_at: datetime | str | None = None,
    supersedes_review_id: str | None = None,
    basis_refs: tuple[str, ...] = (),
    metadata: dict[str, Any] | None = None,
) -> ReviewDecisionResult:
    """Create an auditable review record from a validated review request."""

    validate_review_request(review_request)
    validate_reviewer_identity(reviewer)
    _require_non_empty(review_id, field_name="review_id")
    _require_non_empty(reasoning, field_name="reasoning")

    if outcome not in review_request.allowed_outcomes:
        raise ReviewValidationError(
            f"Outcome {outcome.value!r} is not allowed for review request {review_request.review_request_id!r}"
        )
    if supersedes_review_id is not None and supersedes_review_id == review_id:
        raise ReviewValidationError("supersedes_review_id must not equal review_id")

    reviewed_at_iso = _iso_timestamp(reviewed_at)
    _require_not_too_far_in_future(reviewed_at_iso, field_name="reviewed_at")
    _require_not_earlier_than(
        reviewed_at_iso,
        floor=review_request.requested_at,
        field_name="reviewed_at",
        floor_field_name="requested_at",
    )
    target_status = _OUTCOME_TO_TARGET_STATUS[outcome]
    follow_up_action = _OUTCOME_TO_FOLLOW_UP[outcome]
    if target_status not in _ALLOWED_STATUSES:
        raise ReviewValidationError(f"Outcome {outcome.value!r} mapped to unsupported target status {target_status!r}")

    record = ReviewRecord(
        review_id=review_id,
        review_request_id=review_request.review_request_id,
        task_id=review_request.task_id,
        reviewer=reviewer,
        reviewed_at=reviewed_at_iso,
        outcome=outcome,
        reasoning=reasoning.strip(),
        authorized_target_status=target_status,
        follow_up_action=follow_up_action,
        supersedes_review_id=supersedes_review_id,
        basis_refs=basis_refs,
        preserves_history=True,
        metadata=dict(metadata or {}),
    )

    return ReviewDecisionResult(
        request=review_request,
        record=record,
        recommended_target_status=target_status,
        follow_up_action=follow_up_action,
    )


def validate_review_decision_result(review_decision: ReviewDecisionResult) -> ReviewDecisionResult:
    """Validate that a serialized review decision still matches canonical review policy."""

    validate_review_request(review_decision.request)
    validate_reviewer_identity(review_decision.record.reviewer)
    _require_not_too_far_in_future(review_decision.record.reviewed_at, field_name="reviewed_at")

    if review_decision.record.task_id != review_decision.request.task_id:
        raise ReviewValidationError("review_decision.record.task_id must match review_decision.request.task_id")
    if review_decision.record.review_request_id != review_decision.request.review_request_id:
        raise ReviewValidationError(
            "review_decision.record.review_request_id must match review_decision.request.review_request_id"
        )

    canonical_decision = resolve_review_request(
        review_decision.request,
        review_id=review_decision.record.review_id,
        reviewer=review_decision.record.reviewer,
        outcome=review_decision.record.outcome,
        reasoning=review_decision.record.reasoning,
        reviewed_at=review_decision.record.reviewed_at,
        supersedes_review_id=review_decision.record.supersedes_review_id,
        basis_refs=review_decision.record.basis_refs,
        metadata=review_decision.record.metadata,
    )

    if review_decision.record.authorized_target_status != canonical_decision.record.authorized_target_status:
        raise ReviewValidationError(
            "review_decision.record.authorized_target_status does not match the canonical outcome mapping"
        )
    if review_decision.record.follow_up_action != canonical_decision.record.follow_up_action:
        raise ReviewValidationError(
            "review_decision.record.follow_up_action does not match the canonical outcome mapping"
        )
    if review_decision.recommended_target_status != canonical_decision.recommended_target_status:
        raise ReviewValidationError(
            "review_decision.recommended_target_status does not match the canonical outcome mapping"
        )
    if review_decision.follow_up_action != canonical_decision.follow_up_action:
        raise ReviewValidationError(
            "review_decision.follow_up_action does not match the canonical outcome mapping"
        )

    return review_decision


def append_review_record(
    history: tuple[ReviewRecord, ...] | list[ReviewRecord],
    review_record: ReviewRecord,
) -> tuple[ReviewRecord, ...]:
    """Append a review record without erasing prior review history."""

    review_history = tuple(history)
    existing_review_ids = {item.review_id for item in review_history}
    if review_record.review_id in existing_review_ids:
        raise ReviewValidationError(f"review_id {review_record.review_id!r} already exists in review history")
    if review_record.supersedes_review_id and review_record.supersedes_review_id not in existing_review_ids:
        raise ReviewValidationError(
            f"supersedes_review_id {review_record.supersedes_review_id!r} does not exist in review history"
        )
    if not review_record.preserves_history:
        raise ReviewValidationError("Review records must preserve prior history")
    return (*review_history, review_record)


__all__ = [
    "ReviewDecisionResult",
    "ReviewFollowUpAction",
    "ReviewOutcome",
    "ReviewRecord",
    "ReviewRequest",
    "ReviewTrigger",
    "ReviewValidationError",
    "ReviewerIdentity",
    "append_review_record",
    "resolve_review_request",
    "validate_review_request",
    "validate_reviewer_identity",
]
