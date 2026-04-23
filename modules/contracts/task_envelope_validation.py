"""Validation helpers for the canonical TaskEnvelope schema."""

from __future__ import annotations

from jsonschema import Draft202012Validator
from typing import Any

from modules.contracts.schema_loader import load_task_envelope_schema


_SCHEMA = load_task_envelope_schema()
_VALIDATOR = Draft202012Validator(_SCHEMA)


def validate_task_envelope(task_envelope: dict[str, Any]) -> list[str]:
    """Return schema validation errors for a TaskEnvelope."""

    errors = []
    for error in _VALIDATOR.iter_errors(task_envelope):
        path = "/" + "/".join(str(part) for part in error.absolute_path)
        errors.append(f"{path if path != '/' else '/'} {error.message}")
    return sorted(errors)


def assert_valid_task_envelope(task_envelope: dict[str, Any]) -> dict[str, Any]:
    """Raise ValueError if the TaskEnvelope is not valid."""

    errors = validate_task_envelope(task_envelope)
    if errors:
        raise ValueError("Invalid TaskEnvelope: " + "; ".join(errors))
    return task_envelope
