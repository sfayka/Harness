"""Lifecycle enforcement primitives for canonical TaskEnvelope state movement."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from modules.contracts.task_envelope_validation import assert_valid_task_envelope

TaskEnvelope = dict[str, Any]
TransitionFacts = Mapping[str, Any]
PreconditionHook = Callable[[TaskEnvelope, str, str, TransitionFacts], str | None]


class LifecycleTransitionError(ValueError):
    """Base error for invalid lifecycle transition attempts."""


class ForbiddenTransitionError(LifecycleTransitionError):
    """Raised when a transition is not part of the canonical state graph."""


class TransitionAuthorityError(LifecycleTransitionError):
    """Raised when an unauthorized actor attempts a transition."""


class TransitionPreconditionError(LifecycleTransitionError):
    """Raised when transition preconditions are not met."""


@dataclass(frozen=True)
class TransitionResult:
    """Result of a successful lifecycle transition application."""

    task_envelope: TaskEnvelope
    from_status: str
    to_status: str
    changed_at: str
    actor: str
    reason: str | None
    status_history_entry: dict[str, Any]


_STATUSES = {
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

_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "intake_ready": {"planned", "blocked"},
    "planned": {"dispatch_ready", "blocked", "canceled"},
    "dispatch_ready": {"assigned", "blocked", "canceled"},
    "assigned": {"executing", "blocked", "failed", "canceled"},
    "executing": {"completed", "blocked", "in_review", "failed", "canceled"},
    "blocked": {"intake_ready", "planned", "dispatch_ready", "assigned", "executing", "in_review", "completed", "canceled"},
    "in_review": {"planned", "dispatch_ready", "assigned", "blocked", "completed", "failed", "canceled"},
    "completed": {"blocked", "in_review"},
    "failed": set(),
    "canceled": set(),
}

_AUTHORIZED_ACTORS: dict[tuple[str, str], set[str]] = {
    ("intake_ready", "planned"): {"planner"},
    ("intake_ready", "blocked"): {"intake", "clarification"},
    ("planned", "dispatch_ready"): {"planner"},
    ("planned", "blocked"): {"planner", "verification"},
    ("planned", "canceled"): {"operator", "manual_review"},
    ("dispatch_ready", "assigned"): {"dispatcher"},
    ("dispatch_ready", "blocked"): {"dispatcher", "operator", "manual_review"},
    ("dispatch_ready", "canceled"): {"operator", "manual_review"},
    ("assigned", "executing"): {"runtime"},
    ("assigned", "blocked"): {"dispatcher", "runtime", "operator", "manual_review"},
    ("assigned", "failed"): {"runtime", "verification"},
    ("assigned", "canceled"): {"operator", "manual_review"},
    ("executing", "completed"): {"verification"},
    ("executing", "in_review"): {"verification"},
    ("executing", "blocked"): {"runtime", "clarification", "verification", "manual_review"},
    ("executing", "failed"): {"runtime", "verification", "manual_review"},
    ("executing", "canceled"): {"operator", "manual_review"},
    ("completed", "blocked"): {"verification", "manual_review"},
    ("completed", "in_review"): {"verification", "manual_review"},
    ("blocked", "intake_ready"): {"clarification", "operator", "manual_review"},
    ("blocked", "planned"): {"planner", "clarification", "operator", "manual_review"},
    ("blocked", "dispatch_ready"): {"dispatcher", "operator", "manual_review"},
    ("blocked", "assigned"): {"dispatcher"},
    ("blocked", "executing"): {"runtime"},
    ("blocked", "in_review"): {"verification", "manual_review"},
    ("blocked", "completed"): {"verification", "manual_review"},
    ("blocked", "canceled"): {"operator", "manual_review"},
    ("in_review", "planned"): {"manual_review"},
    ("in_review", "dispatch_ready"): {"manual_review"},
    ("in_review", "assigned"): {"manual_review"},
    ("in_review", "blocked"): {"manual_review"},
    ("in_review", "completed"): {"manual_review"},
    ("in_review", "failed"): {"manual_review"},
    ("in_review", "canceled"): {"manual_review"},
}


def _iso_timestamp(value: Any | None = None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    raise ValueError("Expected now to be a datetime, ISO-8601 string, or None")


def _has_unresolved_clarification(task_envelope: TaskEnvelope) -> bool:
    clarification = task_envelope.get("clarification")
    if not clarification:
        return False

    if clarification.get("status") in {"required", "requested", "answered"}:
        return True

    for item in clarification.get("required_inputs", []):
        if item.get("required") and item.get("status") == "open":
            return True

    return False


def _has_active_assignment(task_envelope: TaskEnvelope) -> bool:
    assigned_executor = task_envelope.get("assigned_executor")
    return isinstance(assigned_executor, dict) and bool(assigned_executor.get("executor_type"))


def _completion_evidence_satisfied(task_envelope: TaskEnvelope) -> bool:
    evidence = task_envelope.get("artifacts", {}).get("completion_evidence", {})
    policy = evidence.get("policy")
    status = evidence.get("status")

    if policy in {"deferred", "advisory_only", "not_applicable"}:
        return True

    return policy == "required" and status == "satisfied"


def _reason_required(task_envelope: TaskEnvelope, from_status: str, to_status: str, facts: TransitionFacts) -> str | None:
    del task_envelope
    if to_status in {"blocked", "failed", "canceled"} and not facts.get("reason_provided", False):
        return f"Transition {from_status} -> {to_status} requires a reason"
    return None


def _clarification_must_be_resolved(
    task_envelope: TaskEnvelope, from_status: str, to_status: str, facts: TransitionFacts
) -> str | None:
    del from_status, facts
    if to_status in {"planned", "dispatch_ready", "assigned"} and _has_unresolved_clarification(task_envelope):
        return f"Transition to {to_status} requires clarification to be resolved"
    return None


def _assignment_required(
    task_envelope: TaskEnvelope, from_status: str, to_status: str, facts: TransitionFacts
) -> str | None:
    del from_status, facts
    if to_status == "assigned" and not _has_active_assignment(task_envelope):
        return "Transition to assigned requires assigned_executor to record the active assignment"
    return None


def _execution_start_required(
    task_envelope: TaskEnvelope, from_status: str, to_status: str, facts: TransitionFacts
) -> str | None:
    del from_status
    if to_status != "executing":
        return None
    if not _has_active_assignment(task_envelope):
        return "Transition to executing requires an active assignment"
    if not facts.get("execution_started", False):
        return "Transition to executing requires a real execution-start fact"
    return None


def _completion_requirements(
    task_envelope: TaskEnvelope, from_status: str, to_status: str, facts: TransitionFacts
) -> str | None:
    del from_status
    if to_status != "completed":
        return None

    if not facts.get("verification_passed", False):
        return "Transition to completed requires a passing verification decision"
    if not facts.get("acceptance_criteria_satisfied", False):
        return "Transition to completed requires acceptance criteria to be satisfied"
    if not facts.get("reconciliation_passed", False):
        return "Transition to completed requires non-blocking reconciliation"
    if not _completion_evidence_satisfied(task_envelope):
        return "Transition to completed requires completion evidence to be satisfied"
    return None


def _terminal_failure_required(
    task_envelope: TaskEnvelope, from_status: str, to_status: str, facts: TransitionFacts
) -> str | None:
    del task_envelope, from_status
    if to_status == "failed" and not facts.get("terminal_failure", False):
        return "Transition to failed requires a terminal failure determination"
    return None


def _blocked_reentry_requirements(
    task_envelope: TaskEnvelope, from_status: str, to_status: str, facts: TransitionFacts
) -> str | None:
    del facts
    if from_status != "blocked":
        return None
    if to_status in {"intake_ready", "planned", "dispatch_ready"} and _has_unresolved_clarification(task_envelope):
        return f"Transition blocked -> {to_status} requires the blocking clarification to be resolved"
    return None


_DEFAULT_PRECONDITION_HOOKS: tuple[PreconditionHook, ...] = (
    _reason_required,
    _clarification_must_be_resolved,
    _assignment_required,
    _execution_start_required,
    _completion_requirements,
    _terminal_failure_required,
    _blocked_reentry_requirements,
)


def validate_task_transition(
    task_envelope: TaskEnvelope,
    *,
    to_status: str,
    actor: str,
    reason: str | None = None,
    facts: TransitionFacts | None = None,
    precondition_hooks: list[PreconditionHook] | tuple[PreconditionHook, ...] = (),
) -> None:
    """Validate that a requested task transition is allowed under lifecycle policy."""

    assert_valid_task_envelope(task_envelope)

    from_status = task_envelope["status"]
    if from_status not in _STATUSES or to_status not in _STATUSES:
        raise ForbiddenTransitionError(f"Unknown lifecycle transition {from_status} -> {to_status}")

    if from_status == to_status:
        raise ForbiddenTransitionError(f"No-op lifecycle transition {from_status} -> {to_status} is not allowed")

    if to_status not in _ALLOWED_TRANSITIONS.get(from_status, set()):
        raise ForbiddenTransitionError(f"Forbidden lifecycle transition {from_status} -> {to_status}")

    allowed_actors = _AUTHORIZED_ACTORS.get((from_status, to_status), set())
    if actor not in allowed_actors:
        raise TransitionAuthorityError(
            f"Actor {actor!r} is not authorized for transition {from_status} -> {to_status}"
        )

    facts = dict(facts or {})
    facts["reason_provided"] = bool(reason and reason.strip())

    for hook in (*_DEFAULT_PRECONDITION_HOOKS, *precondition_hooks):
        error = hook(task_envelope, from_status, to_status, facts)
        if error:
            raise TransitionPreconditionError(error)


def apply_task_transition(
    task_envelope: TaskEnvelope,
    *,
    to_status: str,
    actor: str,
    reason: str | None = None,
    changed_by: str | None = None,
    now: datetime | str | None = None,
    facts: TransitionFacts | None = None,
    precondition_hooks: list[PreconditionHook] | tuple[PreconditionHook, ...] = (),
) -> TransitionResult:
    """Apply a validated lifecycle transition and append an audit history entry."""

    validate_task_transition(
        task_envelope,
        to_status=to_status,
        actor=actor,
        reason=reason,
        facts=facts,
        precondition_hooks=precondition_hooks,
    )

    changed_at = _iso_timestamp(now)
    from_status = task_envelope["status"]
    updated = deepcopy(task_envelope)
    updated["status"] = to_status
    updated["timestamps"]["updated_at"] = changed_at

    if to_status == "completed":
        updated["timestamps"]["completed_at"] = changed_at
    elif from_status == "completed":
        updated["timestamps"]["completed_at"] = None

    history_entry = {
        "from_status": from_status,
        "to_status": to_status,
        "changed_at": changed_at,
        "reason": reason,
        "changed_by": changed_by or actor,
    }
    updated.setdefault("status_history", []).append(history_entry)

    assert_valid_task_envelope(updated)

    return TransitionResult(
        task_envelope=updated,
        from_status=from_status,
        to_status=to_status,
        changed_at=changed_at,
        actor=actor,
        reason=reason,
        status_history_entry=history_entry,
    )


__all__ = [
    "ForbiddenTransitionError",
    "LifecycleTransitionError",
    "TransitionAuthorityError",
    "TransitionPreconditionError",
    "TransitionResult",
    "apply_task_transition",
    "validate_task_transition",
]
