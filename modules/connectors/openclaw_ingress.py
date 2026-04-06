"""OpenClaw-shaped ingress adapter for canonical Harness task submission."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any

from modules.contracts.task_envelope_lifecycle import apply_task_transition
from modules.contracts.task_envelope_validation import assert_valid_task_envelope

from .ingress_request_builder import (
    IngressRequestBuilderError,
    IngressSourceContext,
    IngressTaskIntent,
    build_task_submission_payload,
)


class OpenClawIngressInputError(ValueError):
    """Raised when an OpenClaw-shaped ingress payload cannot be normalized canonically."""


_ALLOWED_OPENCLAW_HANDOFF_STATUSES = frozenset({"intake_ready", "planned"})


def _require_mapping(payload: Any, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise OpenClawIngressInputError(f"{field_name} must be a mapping")
    return payload


def _optional_mapping(payload: Any, *, field_name: str) -> Mapping[str, Any] | None:
    if payload is None:
        return None
    return _require_mapping(payload, field_name=field_name)


def _require_string(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OpenClawIngressInputError(f"{field_name} is required")
    return value.strip()


def _optional_string(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise OpenClawIngressInputError(f"{field_name} must be a string when provided")
    stripped = value.strip()
    return stripped or None


def _optional_non_empty_string_list(value: Any, *, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise OpenClawIngressInputError(f"{field_name} must be a list of non-empty strings")
    return tuple(item.strip() for item in value)


def _to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _to_jsonable(val) for key, val in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _to_jsonable(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    return value


def _validate_openclaw_handoff_contract(payload: Mapping[str, Any]) -> None:
    task = _require_mapping(payload.get("task"), field_name="task")
    metadata = _optional_mapping(payload.get("metadata"), field_name="metadata") or {}
    task_status = _optional_string(task.get("status"), field_name="task.status") or "intake_ready"
    if task_status not in _ALLOWED_OPENCLAW_HANDOFF_STATUSES:
        allowed_statuses = ", ".join(sorted(_ALLOWED_OPENCLAW_HANDOFF_STATUSES))
        raise OpenClawIngressInputError(
            f"task.status must be one of {allowed_statuses} for OpenClaw ingress handoff"
        )
    if bool(payload.get("claimed_completion", False)):
        raise OpenClawIngressInputError(
            "OpenClaw ingress cannot claim completion; completion must flow through executor/reporting paths"
        )
    if bool(payload.get("acceptance_criteria_satisfied", False)):
        raise OpenClawIngressInputError(
            "OpenClaw ingress cannot assert acceptance_criteria_satisfied on initial handoff"
        )
    runtime_facts = _optional_mapping(payload.get("runtime_facts"), field_name="runtime_facts")
    if runtime_facts:
        raise OpenClawIngressInputError(
            "OpenClaw ingress cannot submit executor runtime_facts; execution telemetry must come from execution or reevaluation paths"
        )
    if task_status == "planned":
        if _optional_string(task.get("objective_summary"), field_name="task.objective_summary") is None:
            raise OpenClawIngressInputError(
                "OpenClaw ingress planned handoff requires task.objective_summary"
            )
        deliverable_type = _optional_string(
            task.get("objective_deliverable_type"),
            field_name="task.objective_deliverable_type",
        )
        if deliverable_type is None or deliverable_type == "unspecified":
            raise OpenClawIngressInputError(
                "OpenClaw ingress planned handoff requires a non-default task.objective_deliverable_type"
            )
        if _optional_string(task.get("objective_success_signal"), field_name="task.objective_success_signal") is None:
            raise OpenClawIngressInputError(
                "OpenClaw ingress planned handoff requires task.objective_success_signal"
            )
        if _optional_string(metadata.get("plan_summary"), field_name="metadata.plan_summary") is None:
            raise OpenClawIngressInputError(
                "OpenClaw ingress planned handoff requires metadata.plan_summary"
            )
        unresolved_conditions = _optional_non_empty_string_list(
            payload.get("unresolved_conditions"),
            field_name="unresolved_conditions",
        )
        if unresolved_conditions:
            raise OpenClawIngressInputError(
                "OpenClaw ingress planned handoff cannot include unresolved_conditions; unresolved ambiguity must stay intake_ready or blocked"
            )


def _infer_need_type(condition: str) -> str:
    normalized = condition.strip().lower()
    if "ambig" in normalized or "unclear" in normalized or "multiple" in normalized:
        return "ambiguous"
    if "missing" in normalized or "not provided" in normalized or "unknown" in normalized:
        return "missing"
    return "incomplete"


def _with_openclaw_clarification_handoff(
    *,
    canonical_payload: dict[str, Any],
    unresolved_conditions: tuple[str, ...],
) -> dict[str, Any]:
    if not unresolved_conditions:
        return canonical_payload

    request_payload = dict(canonical_payload["request"])
    task_envelope = deepcopy(request_payload["task_envelope"])
    transition = apply_task_transition(
        task_envelope,
        to_status="blocked",
        actor="clarification",
        reason=f"OpenClaw handoff contains unresolved conditions: {unresolved_conditions[0]}",
        facts={"reason_provided": True},
    )
    blocked_task = transition.task_envelope
    requested_at = blocked_task["timestamps"]["updated_at"]
    blocked_task["clarification"] = {
        "status": "required",
        "blocking_reason": "missing_information",
        "resume_target_status": "intake_ready",
        "required_inputs": [
            {
                "id": f"openclaw-input-{index + 1}",
                "label": f"Required clarification {index + 1}",
                "description": condition,
                "required": True,
                "need_type": _infer_need_type(condition),
                "status": "open",
                "value_summary": None,
            }
            for index, condition in enumerate(unresolved_conditions)
        ],
        "questions": [],
        "responses": [],
        "requested_at": requested_at,
        "resolved_at": None,
        "requested_by": "openclaw-ingress",
        "resolution_summary": None,
    }
    request_payload["task_envelope"] = assert_valid_task_envelope(blocked_task)
    request_payload.pop("unresolved_conditions", None)
    return {"request": request_payload}


def _build_openclaw_context(payload: Mapping[str, Any]) -> IngressSourceContext:
    context = _require_mapping(payload.get("context"), field_name="context")
    conversation_id = _require_string(context.get("conversation_id"), field_name="context.conversation_id")
    message_id = _require_string(context.get("message_id"), field_name="context.message_id")

    extension_payload = {
        "conversation_id": conversation_id,
        "message_id": message_id,
        "channel": _require_string(context.get("channel"), field_name="context.channel"),
        "workspace_id": _optional_string(context.get("workspace_id"), field_name="context.workspace_id"),
        "user_id": _optional_string(context.get("user_id"), field_name="context.user_id"),
        "agent_id": _optional_string(context.get("agent_id"), field_name="context.agent_id"),
    }

    return IngressSourceContext(
        source_system="openclaw",
        source_id=message_id,
        ingress_name="OpenClaw",
        ingress_id=conversation_id,
        requested_by=_optional_string(payload.get("requested_by"), field_name="requested_by")
        or extension_payload["user_id"],
        extension_namespace="openclaw",
        extension_payload=extension_payload,
    )


def _build_task_intent(payload: Mapping[str, Any]) -> IngressTaskIntent:
    task = _require_mapping(payload.get("task"), field_name="task")
    context = _require_mapping(payload.get("context"), field_name="context")
    task_id = _optional_string(payload.get("task_id"), field_name="task_id") or _require_string(
        context.get("message_id"),
        field_name="context.message_id",
    )
    constraints = tuple(
        {
            "type": "ingress_constraint",
            "description": item,
            "required": True,
        }
        for item in _optional_non_empty_string_list(task.get("constraints"), field_name="task.constraints")
    )
    return IngressTaskIntent(
        task_id=task_id,
        title=_require_string(task.get("title"), field_name="task.title"),
        description=_require_string(task.get("description"), field_name="task.description"),
        acceptance_criteria=_optional_non_empty_string_list(task.get("acceptance_criteria"), field_name="task.acceptance_criteria"),
        objective_summary=_optional_string(task.get("objective_summary"), field_name="task.objective_summary"),
        deliverable_type=_optional_string(
            task.get("objective_deliverable_type"),
            field_name="task.objective_deliverable_type",
        )
        or "unspecified",
        success_signal=_optional_string(task.get("objective_success_signal"), field_name="task.objective_success_signal")
        or "Task satisfies declared acceptance criteria.",
        constraints=constraints,
        priority=_optional_string(task.get("priority"), field_name="task.priority") or "normal",
        status=_optional_string(task.get("status"), field_name="task.status") or "intake_ready",
    )


def translate_openclaw_submission_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Translate an OpenClaw ingress payload into canonical ``POST /tasks`` input."""

    payload = _require_mapping(payload, field_name="openclaw_ingress_payload")
    _validate_openclaw_handoff_contract(payload)
    unresolved_conditions = _optional_non_empty_string_list(
        payload.get("unresolved_conditions"),
        field_name="unresolved_conditions",
    )
    try:
        canonical_payload = build_task_submission_payload(
            intent=_build_task_intent(payload),
            context=_build_openclaw_context(payload),
            external_facts=_to_jsonable(_optional_mapping(payload.get("external_facts"), field_name="external_facts")),
            claimed_completion=bool(payload.get("claimed_completion", False)),
            acceptance_criteria_satisfied=bool(payload.get("acceptance_criteria_satisfied", False)),
            runtime_facts=_to_jsonable(_optional_mapping(payload.get("runtime_facts"), field_name="runtime_facts")),
            unresolved_conditions=(),
        )
    except IngressRequestBuilderError as error:
        raise OpenClawIngressInputError(str(error)) from error

    canonical_payload = _with_openclaw_clarification_handoff(
        canonical_payload=canonical_payload,
        unresolved_conditions=unresolved_conditions,
    )

    metadata = _to_jsonable(_optional_mapping(payload.get("metadata"), field_name="metadata") or {})
    if metadata:
        request_payload = canonical_payload["request"]
        task_envelope = request_payload["task_envelope"]
        openclaw_extension = dict(task_envelope.get("extensions", {}).get("openclaw") or {})
        openclaw_extension["metadata"] = metadata
        task_envelope["extensions"] = {"openclaw": openclaw_extension}
    return canonical_payload


__all__ = [
    "OpenClawIngressInputError",
    "translate_openclaw_submission_payload",
]
