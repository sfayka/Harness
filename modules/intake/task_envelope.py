"""TaskEnvelope construction for intake-owned fields."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from modules.contracts.task_envelope_validation import assert_valid_task_envelope


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


def _normalize_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or value.strip() == "":
        raise ValueError(f"Expected non-empty string for {field_name}")
    return value.strip()


def _normalize_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    return _normalize_string(value, "optional string")


def _normalize_constraints(constraints: Any | None) -> list[dict[str, Any]]:
    if constraints is None:
        return []

    if not isinstance(constraints, list):
        raise ValueError("Expected constraints to be a list")

    normalized: list[dict[str, Any]] = []
    for index, constraint in enumerate(constraints):
        if not isinstance(constraint, dict):
            raise ValueError(f"Expected constraints[{index}] to be an object")

        normalized.append(
            {
                "type": _normalize_string(constraint.get("type"), f"constraints[{index}].type"),
                "description": _normalize_string(
                    constraint.get("description"),
                    f"constraints[{index}].description",
                ),
                "required": constraint.get("required", True) is not False,
            }
        )
    return normalized


def _normalize_acceptance_criteria(
    acceptance_criteria: Any | None,
) -> list[dict[str, Any]]:
    if not isinstance(acceptance_criteria, list):
        raise ValueError("Expected acceptance_criteria to be a list")

    if not acceptance_criteria:
        raise ValueError("Expected acceptance_criteria to contain at least one item")

    normalized: list[dict[str, Any]] = []
    for index, criterion in enumerate(acceptance_criteria):
        if not isinstance(criterion, dict):
            raise ValueError(f"Expected acceptance_criteria[{index}] to be an object")

        normalized.append(
            {
                "id": _normalize_string(
                    criterion.get("id", f"criterion-{index + 1}"),
                    f"acceptance_criteria[{index}].id",
                ),
                "description": _normalize_string(
                    criterion.get("description"),
                    f"acceptance_criteria[{index}].description",
                ),
                "required": criterion.get("required", True) is not False,
            }
        )
    return normalized


def _normalize_origin(origin: Any) -> dict[str, Any]:
    if not isinstance(origin, dict):
        raise ValueError("Expected origin to be an object")

    return {
        "source_system": _normalize_string(origin.get("source_system"), "origin.source_system"),
        "source_type": _normalize_string(origin.get("source_type"), "origin.source_type"),
        "source_id": _normalize_string(origin.get("source_id"), "origin.source_id"),
        "ingress_id": _normalize_optional_string(origin.get("ingress_id")),
        "ingress_name": _normalize_optional_string(origin.get("ingress_name")),
        "requested_by": _normalize_optional_string(origin.get("requested_by")),
    }


def _normalize_objective(intake_input: dict[str, Any]) -> dict[str, str]:
    objective = intake_input.get("objective")
    if objective is not None and not isinstance(objective, dict):
        raise ValueError("Expected objective to be an object when provided")

    objective = objective or {}

    return {
        "summary": _normalize_string(
            objective.get("summary", intake_input.get("description")),
            "objective.summary",
        ),
        "deliverable_type": _normalize_string(
            objective.get("deliverable_type", "unspecified"),
            "objective.deliverable_type",
        ),
        "success_signal": _normalize_string(
            objective.get(
                "success_signal",
                "Task satisfies declared acceptance criteria.",
            ),
            "objective.success_signal",
        ),
    }


def create_task_envelope(
    intake_input: dict[str, Any],
    *,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    """Construct a schema-valid TaskEnvelope from intake-owned inputs only."""

    if not isinstance(intake_input, dict):
        raise ValueError("Expected intake_input to be an object")

    timestamp = _iso_timestamp(now)
    task_id = intake_input.get("id", str(uuid4()))

    task_envelope: dict[str, Any] = {
        "id": _normalize_string(task_id, "id"),
        "title": _normalize_string(intake_input.get("title"), "title"),
        "description": _normalize_string(intake_input.get("description"), "description"),
        "origin": _normalize_origin(intake_input.get("origin")),
        "status": "intake_ready",
        "timestamps": {
            "created_at": timestamp,
            "updated_at": timestamp,
            "completed_at": None,
        },
        "status_history": [],
        "objective": _normalize_objective(intake_input),
        "constraints": _normalize_constraints(intake_input.get("constraints")),
        "acceptance_criteria": _normalize_acceptance_criteria(
            intake_input.get("acceptance_criteria")
        ),
        "parent_task_id": None,
        "child_task_ids": [],
        "dependencies": [],
        "assigned_executor": None,
        "required_capabilities": [],
        "priority": "normal",
        "artifacts": {
            "pr_links": [],
            "commit_shas": [],
            "logs": [],
            "outputs": [],
        },
        "observability": {
            "errors": [],
            "retries": {
                "attempt_count": 0,
                "max_attempts": 0,
                "last_retry_at": None,
            },
            "execution_metadata": {
                "schema_required_deferred_fields": [
                    "parent_task_id",
                    "child_task_ids",
                    "dependencies",
                    "assigned_executor",
                    "required_capabilities",
                    "priority",
                    "artifacts",
                    "observability",
                ]
            },
        },
    }

    return assert_valid_task_envelope(task_envelope)
