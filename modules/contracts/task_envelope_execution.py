"""Canonical execution event, artifact, and provenance models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class ExecutionModelValidationError(ValueError):
    """Raised when canonical execution models are malformed."""


_EXECUTION_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "execution_started",
        "progress_reported",
        "output_attached",
        "artifact_attached",
        "execution_failed",
        "execution_succeeded",
        "execution_stalled",
        "execution_timed_out",
        "retry_scheduled",
        "retry_started",
        "execution_canceled",
    }
)


_ADVISORY_COMPLETION_OUTCOMES: frozenset[str] = frozenset(
    {
        "reported_success",
        "reported_failure",
        "reported_blocked",
    }
)


def _require_non_empty(value: str | None, *, field_name: str) -> None:
    if value is None or not value.strip():
        raise ExecutionModelValidationError(f"{field_name} is required")


@dataclass(frozen=True)
class ExecutionProvenance:
    """Source attribution for execution facts emitted to Harness."""

    source_system: str
    source_type: str
    source_id: str
    ingestion_id: str | None = None
    recorder: str | None = None


@dataclass(frozen=True)
class ExecutionArtifactReference:
    """Executor-emitted reference to an artifact candidate."""

    artifact_type: str
    reference_id: str
    uri: str | None = None
    content_hash: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AdvisoryCompletionClaim:
    """Advisory completion signal emitted by an executor/adapter."""

    outcome: str
    summary: str | None = None
    confidence: float | None = None
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExecutionEvent:
    """Canonical append-only execution event captured by Harness."""

    event_id: str
    task_id: str
    attempt_id: str
    event_type: str
    occurred_at: str
    provenance: ExecutionProvenance
    payload: dict[str, Any] = field(default_factory=dict)
    artifact_references: tuple[ExecutionArtifactReference, ...] = ()
    advisory_completion: AdvisoryCompletionClaim | None = None



def validate_execution_provenance(provenance: ExecutionProvenance) -> ExecutionProvenance:
    """Validate execution provenance."""

    _require_non_empty(provenance.source_system, field_name="provenance.source_system")
    _require_non_empty(provenance.source_type, field_name="provenance.source_type")
    _require_non_empty(provenance.source_id, field_name="provenance.source_id")
    return provenance



def validate_execution_artifact_reference(
    artifact_reference: ExecutionArtifactReference,
) -> ExecutionArtifactReference:
    """Validate an execution artifact reference."""

    _require_non_empty(artifact_reference.artifact_type, field_name="artifact_reference.artifact_type")
    _require_non_empty(artifact_reference.reference_id, field_name="artifact_reference.reference_id")
    return artifact_reference



def validate_advisory_completion_claim(
    advisory_completion: AdvisoryCompletionClaim,
) -> AdvisoryCompletionClaim:
    """Validate advisory completion semantics."""

    _require_non_empty(advisory_completion.outcome, field_name="advisory_completion.outcome")
    if advisory_completion.outcome not in _ADVISORY_COMPLETION_OUTCOMES:
        allowed = ", ".join(sorted(_ADVISORY_COMPLETION_OUTCOMES))
        raise ExecutionModelValidationError(
            f"advisory_completion.outcome must be one of: {allowed}"
        )

    if advisory_completion.confidence is not None:
        if advisory_completion.confidence < 0 or advisory_completion.confidence > 1:
            raise ExecutionModelValidationError("advisory_completion.confidence must be within [0, 1]")

    for index, reason in enumerate(advisory_completion.reasons):
        _require_non_empty(reason, field_name=f"advisory_completion.reasons[{index}]")

    return advisory_completion



def validate_execution_event(execution_event: ExecutionEvent) -> ExecutionEvent:
    """Validate canonical execution-event constraints."""

    _require_non_empty(execution_event.event_id, field_name="event_id")
    _require_non_empty(execution_event.task_id, field_name="task_id")
    _require_non_empty(execution_event.attempt_id, field_name="attempt_id")
    _require_non_empty(execution_event.event_type, field_name="event_type")
    _require_non_empty(execution_event.occurred_at, field_name="occurred_at")

    if execution_event.event_type not in _EXECUTION_EVENT_TYPES:
        allowed = ", ".join(sorted(_EXECUTION_EVENT_TYPES))
        raise ExecutionModelValidationError(f"event_type must be one of: {allowed}")

    validate_execution_provenance(execution_event.provenance)

    for index, artifact_reference in enumerate(execution_event.artifact_references):
        try:
            validate_execution_artifact_reference(artifact_reference)
        except ExecutionModelValidationError as error:
            raise ExecutionModelValidationError(
                f"artifact_references[{index}] invalid: {error}"
            ) from error

    if execution_event.advisory_completion is not None:
        validate_advisory_completion_claim(execution_event.advisory_completion)

    if "status" in execution_event.payload:
        raise ExecutionModelValidationError(
            "execution event payload must not include lifecycle-authoritative 'status'"
        )
    if "lifecycle_transition" in execution_event.payload:
        raise ExecutionModelValidationError(
            "execution event payload must not include lifecycle-authoritative 'lifecycle_transition'"
        )

    if execution_event.advisory_completion is not None and execution_event.event_type not in {
        "execution_succeeded",
        "execution_failed",
        "execution_stalled",
        "execution_timed_out",
        "execution_canceled",
    }:
        raise ExecutionModelValidationError(
            "advisory_completion is only valid on terminal execution events"
        )

    return execution_event


__all__ = [
    "AdvisoryCompletionClaim",
    "ExecutionArtifactReference",
    "ExecutionEvent",
    "ExecutionModelValidationError",
    "ExecutionProvenance",
    "validate_advisory_completion_claim",
    "validate_execution_artifact_reference",
    "validate_execution_event",
    "validate_execution_provenance",
]
