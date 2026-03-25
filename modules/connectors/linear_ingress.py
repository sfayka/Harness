"""Linear-shaped ingress adapter that translates upstream work items into canonical submission payloads."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any

from modules.connectors.linear_facts import LinearConnectorInputError, translate_linear_facts
from modules.intake.task_envelope import create_task_envelope


class LinearIngressInputError(ValueError):
    """Raised when a Linear-shaped ingress payload cannot be translated canonically."""


def _require_mapping(payload: Any, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise LinearIngressInputError(f"{field_name} must be a mapping")
    return payload


def _optional_mapping(payload: Any, *, field_name: str) -> Mapping[str, Any] | None:
    if payload is None:
        return None
    return _require_mapping(payload, field_name=field_name)


def _require_string(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LinearIngressInputError(f"{field_name} is required")
    return value.strip()


def _optional_string(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise LinearIngressInputError(f"{field_name} must be a string when provided")
    stripped = value.strip()
    return stripped or None


def _optional_mapping_list(value: Any, *, field_name: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise LinearIngressInputError(f"{field_name} must be a list of objects")

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


def _derive_task_id(payload: Mapping[str, Any], *, issue_id: str) -> str:
    task_reference = _optional_mapping(payload.get("task_reference"), field_name="task_reference")
    if task_reference is not None:
        harness_task_id = _optional_string(task_reference.get("harness_task_id"), field_name="task_reference.harness_task_id")
        if harness_task_id is not None:
            return harness_task_id

    explicit_task_id = _optional_string(payload.get("task_id"), field_name="task_id")
    if explicit_task_id is not None:
        return explicit_task_id
    return f"linear-{issue_id}"


def _normalize_priority(value: Any) -> str | None:
    if value is None:
        return None

    if isinstance(value, int):
        mapping = {
            0: "backlog",
            1: "critical",
            2: "high",
            3: "normal",
            4: "low",
        }
        if value not in mapping:
            raise LinearIngressInputError("priority integer must be one of 0, 1, 2, 3, or 4")
        return mapping[value]

    if isinstance(value, str):
        normalized = value.strip().lower()
        aliases = {
            "urgent": "critical",
            "critical": "critical",
            "high": "high",
            "normal": "normal",
            "medium": "normal",
            "low": "low",
            "backlog": "backlog",
            "none": "backlog",
        }
        if normalized not in aliases:
            raise LinearIngressInputError("priority string must map to a canonical Harness priority")
        return aliases[normalized]

    raise LinearIngressInputError("priority must be a string, integer, or null")


def _default_acceptance_criteria(issue_identifier: str | None) -> list[dict[str, Any]]:
    ref = issue_identifier or "the upstream work item"
    return [
        {
            "id": "linear-work-verified",
            "description": f"Harness can verify completion for {ref} using artifacts and reconciled external facts.",
            "required": True,
        }
    ]


def _build_task_envelope(payload: Mapping[str, Any]) -> dict[str, Any]:
    issue_payload = _require_mapping(payload.get("issue"), field_name="issue")
    issue_id = _require_string(issue_payload.get("id"), field_name="issue.id")
    issue_title = _require_string(issue_payload.get("title"), field_name="issue.title")
    issue_description = _require_string(issue_payload.get("description"), field_name="issue.description")
    issue_identifier = _optional_string(
        issue_payload.get("identifier") or issue_payload.get("key") or issue_payload.get("issueKey"),
        field_name="issue.identifier",
    )

    intake_input: dict[str, Any] = {
        "id": _derive_task_id(payload, issue_id=issue_id),
        "title": issue_title,
        "description": issue_description,
        "origin": {
            "source_system": "linear",
            "source_type": "synchronization",
            "source_id": issue_id,
            "ingress_name": "Linear",
            "ingress_id": issue_identifier,
            "requested_by": _optional_string(payload.get("requested_by"), field_name="requested_by"),
        },
        "objective": payload.get("objective"),
        "constraints": payload.get("constraints"),
        "acceptance_criteria": payload.get("acceptance_criteria") or _default_acceptance_criteria(issue_identifier),
    }

    task_envelope = create_task_envelope(intake_input)

    task_status = _optional_string(payload.get("task_status"), field_name="task_status")
    if task_status is not None:
        task_envelope["status"] = task_status
        if task_status == "completed":
            task_envelope["timestamps"]["completed_at"] = task_envelope["timestamps"]["updated_at"]

    assigned_executor = _optional_mapping(payload.get("assigned_executor"), field_name="assigned_executor")
    if assigned_executor is not None:
        task_envelope["assigned_executor"] = dict(assigned_executor)

    priority = _normalize_priority(payload.get("priority"))
    if priority is not None:
        task_envelope["priority"] = priority

    linked_artifacts = _optional_mapping_list(payload.get("linked_artifacts"), field_name="linked_artifacts")
    if linked_artifacts:
        task_envelope["artifacts"]["items"] = deepcopy(linked_artifacts)

    completion_evidence = _optional_mapping(payload.get("completion_evidence"), field_name="completion_evidence")
    if completion_evidence is not None:
        task_envelope["artifacts"]["completion_evidence"].update(dict(completion_evidence))

    labels = payload.get("labels")
    if labels is not None:
        if not isinstance(labels, list) or not all(isinstance(label, str) and label.strip() for label in labels):
            raise LinearIngressInputError("labels must be a list of non-empty strings")
        labels = [label.strip() for label in labels]
    else:
        labels = []

    task_envelope["extensions"] = {
        "linear": {
            "issue_id": issue_id,
            "issue_identifier": issue_identifier,
            "labels": labels,
            "project": _to_jsonable(payload.get("project")),
            "state": _to_jsonable(payload.get("state") or payload.get("status")),
            "task_reference": _to_jsonable(payload.get("task_reference")),
            "metadata": _to_jsonable(payload.get("metadata", {})),
        }
    }

    return task_envelope


def translate_linear_submission_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Translate a Linear-shaped ingress payload into the canonical POST /tasks request body."""

    payload = _require_mapping(payload, field_name="linear_ingress_payload")
    task_envelope = _build_task_envelope(payload)
    linear_facts = translate_linear_facts(payload)

    external_facts_payload = _optional_mapping(payload.get("external_facts"), field_name="external_facts")
    canonical_external_facts = (
        {str(key): _to_jsonable(value) for key, value in external_facts_payload.items()}
        if external_facts_payload is not None
        else {}
    )
    canonical_external_facts["linear_facts"] = _to_jsonable(linear_facts)

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
            raise LinearIngressInputError("unresolved_conditions must be a list of non-empty strings")
        request_payload["unresolved_conditions"] = [item.strip() for item in unresolved_conditions]

    return {"request": request_payload}


__all__ = [
    "LinearIngressInputError",
    "translate_linear_submission_payload",
]
