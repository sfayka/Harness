"""Linear connector scaffolding that translates vendor-shaped inputs into normalized facts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from modules.contracts.task_envelope_external_facts import (
    ExternalFactValidationError,
    LinearFacts,
    LinearProjectFact,
    LinearTaskReference,
    LinearWorkflowFact,
    validate_linear_facts,
)


class LinearConnectorInputError(ValueError):
    """Raised when Linear-shaped connector input is malformed."""


def _require_mapping(payload: Any, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise LinearConnectorInputError(f"{field_name} must be a mapping")
    return payload


def _optional_mapping(payload: Any, *, field_name: str) -> Mapping[str, Any] | None:
    if payload is None:
        return None
    return _require_mapping(payload, field_name=field_name)


def _require_string(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LinearConnectorInputError(f"{field_name} is required")
    return value.strip()


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise LinearConnectorInputError("Expected string or null value")
    stripped = value.strip()
    return stripped or None


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise LinearConnectorInputError("Expected bool or null value")
    return value


def _optional_string_sequence(value: Any, *, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise LinearConnectorInputError(f"{field_name} must be a list or tuple of strings")

    normalized: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise LinearConnectorInputError(f"{field_name}[{index}] must be a non-empty string")
        normalized.append(item.strip())
    return tuple(normalized)


def translate_linear_workflow(workflow_payload: Mapping[str, Any]) -> LinearWorkflowFact:
    """Translate a Linear-shaped workflow/state payload into a normalized workflow fact."""

    workflow_payload = _require_mapping(workflow_payload, field_name="workflow")
    return LinearWorkflowFact(
        workflow_id=_require_string(workflow_payload.get("id"), field_name="workflow.id"),
        workflow_name=_require_string(
            workflow_payload.get("name") or workflow_payload.get("label"),
            field_name="workflow.name",
        ),
        state_type=_optional_string(
            workflow_payload.get("state_type")
            or workflow_payload.get("type")
            or workflow_payload.get("stateType")
        ),
    )


def translate_linear_project(project_payload: Mapping[str, Any]) -> LinearProjectFact:
    """Translate a Linear-shaped project payload into a normalized project fact."""

    project_payload = _require_mapping(project_payload, field_name="project")
    return LinearProjectFact(
        project_id=_require_string(project_payload.get("id"), field_name="project.id"),
        project_name=_optional_string(project_payload.get("name")),
    )


def translate_linear_task_reference(task_reference_payload: Mapping[str, Any]) -> LinearTaskReference:
    """Translate a Linear-shaped task reference payload into a normalized task reference."""

    task_reference_payload = _require_mapping(task_reference_payload, field_name="task_reference")
    return LinearTaskReference(
        harness_task_id=_optional_string(
            task_reference_payload.get("harness_task_id") or task_reference_payload.get("taskId")
        ),
        external_ref=_optional_string(
            task_reference_payload.get("external_ref") or task_reference_payload.get("externalRef")
        ),
    )


def translate_linear_facts(payload: Mapping[str, Any]) -> LinearFacts:
    """Translate a Linear-shaped payload bundle into validated normalized facts."""

    payload = _require_mapping(payload, field_name="linear_payload")
    record_found = payload.get("record_found", True)
    if not isinstance(record_found, bool):
        raise LinearConnectorInputError("record_found must be a boolean")

    issue_payload = _optional_mapping(payload.get("issue"), field_name="issue")
    raw_state_payload = payload.get("state") or payload.get("status")
    project_payload = _optional_mapping(payload.get("project"), field_name="project")
    task_reference_payload = _optional_mapping(payload.get("task_reference"), field_name="task_reference")

    issue_id = None
    issue_key = None
    if issue_payload is not None:
        issue_id = _optional_string(issue_payload.get("id"))
        issue_key = _optional_string(
            issue_payload.get("identifier")
            or issue_payload.get("key")
            or issue_payload.get("issueKey")
        )

    state_name = _optional_string(payload.get("state_name"))
    workflow = None
    if isinstance(raw_state_payload, Mapping):
        workflow = translate_linear_workflow(raw_state_payload)
        state_name = workflow.workflow_name
    elif raw_state_payload is not None:
        state_name = _optional_string(raw_state_payload)

    linear_facts = LinearFacts(
        record_found=record_found,
        issue_id=issue_id,
        issue_key=issue_key,
        state=state_name,
        workflow=workflow,
        project=translate_linear_project(project_payload) if project_payload is not None else None,
        task_reference=(
            translate_linear_task_reference(task_reference_payload) if task_reference_payload is not None else None
        ),
        reasons=_optional_string_sequence(payload.get("reasons"), field_name="reasons"),
    )

    try:
        return validate_linear_facts(linear_facts)
    except ExternalFactValidationError as error:
        raise LinearConnectorInputError(str(error)) from error


__all__ = [
    "LinearConnectorInputError",
    "translate_linear_facts",
    "translate_linear_project",
    "translate_linear_task_reference",
    "translate_linear_workflow",
]
