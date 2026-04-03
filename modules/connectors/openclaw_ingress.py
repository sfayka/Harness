"""OpenClaw-shaped ingress adapter for canonical Harness task submission."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any

from .ingress_request_builder import (
    IngressRequestBuilderError,
    IngressSourceContext,
    IngressTaskIntent,
    build_task_submission_payload,
)


class OpenClawIngressInputError(ValueError):
    """Raised when an OpenClaw-shaped ingress payload cannot be normalized canonically."""


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
    try:
        canonical_payload = build_task_submission_payload(
            intent=_build_task_intent(payload),
            context=_build_openclaw_context(payload),
            external_facts=_to_jsonable(_optional_mapping(payload.get("external_facts"), field_name="external_facts")),
            claimed_completion=bool(payload.get("claimed_completion", False)),
            acceptance_criteria_satisfied=bool(payload.get("acceptance_criteria_satisfied", False)),
            runtime_facts=_to_jsonable(_optional_mapping(payload.get("runtime_facts"), field_name="runtime_facts")),
            unresolved_conditions=_optional_non_empty_string_list(
                payload.get("unresolved_conditions"),
                field_name="unresolved_conditions",
            ),
        )
    except IngressRequestBuilderError as error:
        raise OpenClawIngressInputError(str(error)) from error

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
