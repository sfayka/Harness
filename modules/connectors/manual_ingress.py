"""Manual ingress adapter that translates operator-provided task intent into canonical submission payloads."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any

from modules.intake.task_envelope import create_task_envelope

_ALLOWED_MANUAL_INGRESS_STATUSES = frozenset({"intake_ready", "planned", "dispatch_ready", "assigned", "blocked"})
_EXECUTION_ARTIFACT_TYPES = frozenset({"branch", "commit", "pull_request", "changed_file"})


class ManualIngressInputError(ValueError):
    """Raised when a manual-ingress payload cannot be translated into canonical submission input."""


def _require_mapping(payload: Any, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise ManualIngressInputError(f"{field_name} must be a mapping")
    return payload


def _optional_mapping(payload: Any, *, field_name: str) -> Mapping[str, Any] | None:
    if payload is None:
        return None
    return _require_mapping(payload, field_name=field_name)


def _require_string(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManualIngressInputError(f"{field_name} is required")
    return value.strip()


def _optional_string(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ManualIngressInputError(f"{field_name} must be a string when provided")
    stripped = value.strip()
    return stripped or None


def _optional_mapping_list(value: Any, *, field_name: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ManualIngressInputError(f"{field_name} must be a list of objects")

    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        normalized.append(dict(_require_mapping(item, field_name=f"{field_name}[{index}]")))
    return normalized


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


def _validate_manual_ingress_contract(payload: Mapping[str, Any]) -> None:
    task_status = _optional_string(payload.get("task_status"), field_name="task_status")
    if task_status is not None and task_status not in _ALLOWED_MANUAL_INGRESS_STATUSES:
        allowed_statuses = ", ".join(sorted(_ALLOWED_MANUAL_INGRESS_STATUSES))
        raise ManualIngressInputError(f"task_status must be one of {allowed_statuses} for manual ingress")
    if bool(payload.get("claimed_completion", False)):
        raise ManualIngressInputError(
            "Manual ingress cannot claim completion; completion must flow through executor/reporting paths"
        )
    if bool(payload.get("acceptance_criteria_satisfied", False)):
        raise ManualIngressInputError(
            "Manual ingress cannot assert acceptance_criteria_satisfied on initial handoff"
        )
    runtime_facts = _optional_mapping(payload.get("runtime_facts"), field_name="runtime_facts")
    if runtime_facts:
        raise ManualIngressInputError(
            "Manual ingress cannot submit runtime_facts; execution telemetry must come from execution or reevaluation paths"
        )
    linked_artifacts = _optional_mapping_list(payload.get("linked_artifacts"), field_name="linked_artifacts")
    for artifact in linked_artifacts:
        artifact_type = str(artifact.get("type") or "").strip()
        if artifact_type in _EXECUTION_ARTIFACT_TYPES:
            raise ManualIngressInputError(
                "Manual ingress cannot attach repository execution artifacts; execution proof must come from execution or reevaluation paths"
            )
    if payload.get("completion_evidence") is not None:
        raise ManualIngressInputError(
            "Manual ingress cannot submit completion_evidence; evidence validation belongs to reevaluation and verification"
        )


def _build_task_envelope(payload: Mapping[str, Any]) -> dict[str, Any]:
    task_payload = _require_mapping(payload.get("task"), field_name="task")

    intake_input: dict[str, Any] = {
        "id": _optional_string(payload.get("task_id"), field_name="task_id"),
        "title": _require_string(task_payload.get("title"), field_name="task.title"),
        "description": _require_string(task_payload.get("description"), field_name="task.description"),
        "origin": {
            "source_system": "manual",
            "source_type": _optional_string(task_payload.get("source_type"), field_name="task.source_type")
            or "manual",
            "source_id": _optional_string(task_payload.get("source_id"), field_name="task.source_id")
            or _require_string(task_payload.get("title"), field_name="task.title"),
            "ingress_name": _optional_string(task_payload.get("ingress_name"), field_name="task.ingress_name"),
            "ingress_id": _optional_string(task_payload.get("ingress_id"), field_name="task.ingress_id"),
            "requested_by": _optional_string(task_payload.get("requested_by"), field_name="task.requested_by"),
        },
        "objective": task_payload.get("objective"),
        "constraints": task_payload.get("constraints"),
        "acceptance_criteria": task_payload.get("acceptance_criteria"),
    }

    intake_input = {key: value for key, value in intake_input.items() if value is not None}
    task_envelope = create_task_envelope(intake_input)

    task_status = _optional_string(payload.get("task_status"), field_name="task_status")
    if task_status is not None:
        task_envelope["status"] = task_status
        if task_status == "completed":
            task_envelope["timestamps"]["completed_at"] = task_envelope["timestamps"]["updated_at"]

    assigned_executor = _optional_mapping(payload.get("assigned_executor"), field_name="assigned_executor")
    if assigned_executor is not None:
        task_envelope["assigned_executor"] = dict(assigned_executor)

    priority = _optional_string(payload.get("priority"), field_name="priority")
    if priority is not None:
        task_envelope["priority"] = priority

    linked_artifacts = _optional_mapping_list(payload.get("linked_artifacts"), field_name="linked_artifacts")
    if linked_artifacts:
        task_envelope["artifacts"]["items"] = deepcopy(linked_artifacts)

    completion_evidence = _optional_mapping(payload.get("completion_evidence"), field_name="completion_evidence")
    if completion_evidence is not None:
        task_envelope["artifacts"]["completion_evidence"].update(dict(completion_evidence))

    task_envelope["extensions"] = {
        "manual": {
            "submission": {
                "metadata": _to_jsonable(payload.get("metadata") or {}),
            }
        }
    }

    return task_envelope


def translate_manual_submission_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Translate a manual-ingress payload into a canonical ``POST /tasks`` request body."""

    payload = _require_mapping(payload, field_name="manual_ingress_payload")
    _validate_manual_ingress_contract(payload)
    task_envelope = _build_task_envelope(payload)

    external_facts_payload = _optional_mapping(payload.get("external_facts"), field_name="external_facts")
    canonical_external_facts = (
        {str(key): _to_jsonable(value) for key, value in external_facts_payload.items()}
        if external_facts_payload is not None
        else {}
    )

    request_payload: dict[str, Any] = {
        "task_envelope": task_envelope,
        "external_facts": canonical_external_facts,
        "claimed_completion": bool(payload.get("claimed_completion", False)),
        "acceptance_criteria_satisfied": bool(payload.get("acceptance_criteria_satisfied", False)),
    }

    runtime_facts = _optional_mapping(payload.get("runtime_facts"), field_name="runtime_facts")
    if runtime_facts is not None:
        request_payload["runtime_facts"] = dict(runtime_facts)

    unresolved_conditions = payload.get("unresolved_conditions")
    if unresolved_conditions is not None:
        if not isinstance(unresolved_conditions, list) or not all(
            isinstance(item, str) and item.strip() for item in unresolved_conditions
        ):
            raise ManualIngressInputError("unresolved_conditions must be a list of non-empty strings")
        request_payload["unresolved_conditions"] = [item.strip() for item in unresolved_conditions]

    return {"request": request_payload}


__all__ = [
    "ManualIngressInputError",
    "translate_manual_submission_payload",
]
