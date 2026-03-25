"""Thin ingress-side builders for canonical Harness submission payloads."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from modules.contracts.task_envelope_validation import assert_valid_task_envelope
from modules.intake.task_envelope import create_task_envelope


class IngressRequestBuilderError(ValueError):
    """Raised when higher-level ingress inputs cannot produce canonical payloads."""


def _require_non_empty(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IngressRequestBuilderError(f"{field_name} is required")
    return value.strip()


def _optional_string(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise IngressRequestBuilderError(f"{field_name} must be a string when provided")
    stripped = value.strip()
    return stripped or None


def _normalize_string_tuple(values: tuple[str, ...], *, field_name: str) -> tuple[str, ...]:
    normalized: list[str] = []
    for index, value in enumerate(values):
        normalized.append(_require_non_empty(value, field_name=f"{field_name}[{index}]"))
    return tuple(normalized)


@dataclass(frozen=True)
class IngressSourceContext:
    """Ingress-owned source metadata carried into the canonical task boundary."""

    source_system: str
    source_id: str
    ingress_name: str | None = None
    ingress_id: str | None = None
    requested_by: str | None = None
    source_type: str = "ingress_request"
    extension_namespace: str | None = None
    extension_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IngressTaskIntent:
    """Higher-level ingress task intent converted into a canonical submission payload."""

    task_id: str
    title: str
    description: str
    acceptance_criteria: tuple[str, ...]
    objective_summary: str | None = None
    deliverable_type: str = "unspecified"
    success_signal: str = "Task satisfies declared acceptance criteria."
    status: str = "intake_ready"
    priority: str = "normal"
    linked_artifacts: tuple[dict[str, Any], ...] = ()
    completion_evidence: dict[str, Any] | None = None
    constraints: tuple[dict[str, Any], ...] = ()
    requested_by: str | None = None


def _build_origin(context: IngressSourceContext) -> dict[str, Any]:
    return {
        "source_system": _require_non_empty(context.source_system, field_name="context.source_system"),
        "source_type": _require_non_empty(context.source_type, field_name="context.source_type"),
        "source_id": _require_non_empty(context.source_id, field_name="context.source_id"),
        "ingress_id": _optional_string(context.ingress_id, field_name="context.ingress_id"),
        "ingress_name": _optional_string(context.ingress_name, field_name="context.ingress_name"),
        "requested_by": _optional_string(context.requested_by, field_name="context.requested_by"),
    }


def _default_completion_evidence() -> dict[str, Any]:
    return {
        "policy": "deferred",
        "status": "deferred",
        "required_artifact_types": [],
        "validated_artifact_ids": [],
        "validation_method": "deferred",
        "validated_at": None,
        "validator": None,
        "notes": None,
    }


def build_task_submission_payload(
    *,
    intent: IngressTaskIntent,
    context: IngressSourceContext,
    external_facts: dict[str, Any] | None = None,
    claimed_completion: bool = False,
    acceptance_criteria_satisfied: bool = False,
    runtime_facts: dict[str, Any] | None = None,
    unresolved_conditions: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Build a canonical POST /tasks payload from ingress-side inputs."""

    normalized_acceptance_criteria = _normalize_string_tuple(
        intent.acceptance_criteria,
        field_name="intent.acceptance_criteria",
    )
    if not normalized_acceptance_criteria:
        raise IngressRequestBuilderError("intent.acceptance_criteria must contain at least one item")

    task_envelope = create_task_envelope(
        {
            "id": _require_non_empty(intent.task_id, field_name="intent.task_id"),
            "title": _require_non_empty(intent.title, field_name="intent.title"),
            "description": _require_non_empty(intent.description, field_name="intent.description"),
            "origin": {
                **_build_origin(context),
                "requested_by": _optional_string(intent.requested_by or context.requested_by, field_name="requested_by"),
            },
            "objective": {
                "summary": _require_non_empty(
                    intent.objective_summary or intent.description,
                    field_name="intent.objective_summary",
                ),
                "deliverable_type": _require_non_empty(
                    intent.deliverable_type,
                    field_name="intent.deliverable_type",
                ),
                "success_signal": _require_non_empty(
                    intent.success_signal,
                    field_name="intent.success_signal",
                ),
            },
            "constraints": [deepcopy(item) for item in intent.constraints],
            "acceptance_criteria": [
                {"id": f"ac-{index + 1}", "description": criterion, "required": True}
                for index, criterion in enumerate(normalized_acceptance_criteria)
            ],
        }
    )

    task_envelope["status"] = _require_non_empty(intent.status, field_name="intent.status")
    if task_envelope["status"] == "completed":
        task_envelope["timestamps"]["completed_at"] = task_envelope["timestamps"]["updated_at"]
    else:
        task_envelope["timestamps"]["completed_at"] = None

    task_envelope["priority"] = _require_non_empty(intent.priority, field_name="intent.priority")
    task_envelope["artifacts"]["items"] = [deepcopy(artifact) for artifact in intent.linked_artifacts]
    task_envelope["artifacts"]["completion_evidence"] = (
        deepcopy(intent.completion_evidence)
        if intent.completion_evidence is not None
        else _default_completion_evidence()
    )

    if context.extension_namespace:
        task_envelope["extensions"] = {
            _require_non_empty(context.extension_namespace, field_name="context.extension_namespace"): deepcopy(
                context.extension_payload
            )
        }

    request_payload: dict[str, Any] = {
        "task_envelope": assert_valid_task_envelope(task_envelope),
        "external_facts": deepcopy(external_facts or {}),
        "claimed_completion": claimed_completion,
        "acceptance_criteria_satisfied": acceptance_criteria_satisfied,
    }
    if runtime_facts is not None:
        request_payload["runtime_facts"] = deepcopy(runtime_facts)
    if unresolved_conditions:
        request_payload["unresolved_conditions"] = list(
            _normalize_string_tuple(unresolved_conditions, field_name="unresolved_conditions")
        )
    return {"request": request_payload}


def build_task_reevaluation_payload(
    *,
    external_facts: dict[str, Any] | None = None,
    new_artifacts: tuple[dict[str, Any], ...] = (),
    completion_evidence: dict[str, Any] | None = None,
    claimed_completion: bool = False,
    acceptance_criteria_satisfied: bool = False,
    runtime_facts: dict[str, Any] | None = None,
    unresolved_conditions: tuple[str, ...] = (),
    review_request: dict[str, Any] | None = None,
    review_decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a canonical POST /tasks/<id>/reevaluate payload."""

    request_payload: dict[str, Any] = {
        "external_facts": deepcopy(external_facts or {}),
        "new_artifacts": [deepcopy(artifact) for artifact in new_artifacts],
        "claimed_completion": claimed_completion,
        "acceptance_criteria_satisfied": acceptance_criteria_satisfied,
    }
    if completion_evidence is not None:
        request_payload["completion_evidence"] = deepcopy(completion_evidence)
    if runtime_facts is not None:
        request_payload["runtime_facts"] = deepcopy(runtime_facts)
    if unresolved_conditions:
        request_payload["unresolved_conditions"] = list(
            _normalize_string_tuple(unresolved_conditions, field_name="unresolved_conditions")
        )
    if review_request is not None:
        request_payload["review_request"] = deepcopy(review_request)
    if review_decision is not None:
        request_payload["review_decision"] = deepcopy(review_decision)
    return {"request": request_payload}


__all__ = [
    "IngressRequestBuilderError",
    "IngressSourceContext",
    "IngressTaskIntent",
    "build_task_reevaluation_payload",
    "build_task_submission_payload",
]
