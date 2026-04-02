"""Canonical executor advisory models for execution events, artifacts, and provenance."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ExecutionAdvisoryValidationError(ValueError):
    """Raised when canonical execution advisory models are malformed."""


class ExecutionEventType(StrEnum):
    """Canonical execution event family emitted by executor adapters."""

    EXECUTION_STARTED = "execution_started"
    PROGRESS_REPORTED = "progress_reported"
    OUTPUT_ATTACHED = "output_attached"
    ARTIFACT_ATTACHED = "artifact_attached"
    EXECUTION_FAILED = "execution_failed"
    EXECUTION_SUCCEEDED = "execution_succeeded"
    EXECUTION_STALLED = "execution_stalled"
    EXECUTION_TIMED_OUT = "execution_timed_out"
    RETRY_SCHEDULED = "retry_scheduled"
    RETRY_STARTED = "retry_started"
    EXECUTION_CANCELED = "execution_canceled"


_TERMINAL_FAILURE_EVENTS: frozenset[ExecutionEventType] = frozenset(
    {
        ExecutionEventType.EXECUTION_FAILED,
        ExecutionEventType.EXECUTION_TIMED_OUT,
        ExecutionEventType.EXECUTION_CANCELED,
    }
)

_PROHIBITED_LIFECYCLE_KEYS: frozenset[str] = frozenset(
    {
        "target_status",
        "canonical_status",
        "lifecycle_status",
        "authorized_transition",
    }
)


def _require_non_empty(value: str | None, *, field_name: str) -> None:
    if value is None or not value.strip():
        raise ExecutionAdvisoryValidationError(f"{field_name} is required")


@dataclass(frozen=True)
class ExecutionProvenance:
    """Source provenance for normalized execution inputs."""

    source_system: str
    source_type: str
    source_id: str
    captured_by: str | None = None


@dataclass(frozen=True)
class ArtifactReference:
    """Canonical artifact reference emitted from executor flows."""

    artifact_type: str
    reference_id: str
    location: str | None = None
    external_id: str | None = None
    commit_sha: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    provenance: ExecutionProvenance | None = None


@dataclass(frozen=True)
class AdvisoryCompletionClaim:
    """Executor completion signal that remains advisory only."""

    claim_id: str
    reported_complete: bool
    confidence: str | None = None
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionEvent:
    """Canonical append-only execution event for one task attempt."""

    event_id: str
    task_id: str
    attempt_id: str
    event_type: ExecutionEventType
    occurred_at: str
    provenance: ExecutionProvenance
    artifact_references: tuple[ArtifactReference, ...] = ()
    advisory_completion: AdvisoryCompletionClaim | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeAdvisoryFacts:
    """Derived runtime verification facts from canonical execution events."""

    executor_reported_success: bool
    executor_reported_failure: bool
    terminal_failure: bool
    attempt_count: int


def _validate_no_lifecycle_authority(metadata: dict[str, Any], *, field_name: str) -> None:
    keys = set(metadata)
    forbidden = sorted(keys.intersection(_PROHIBITED_LIFECYCLE_KEYS))
    if forbidden:
        names = ", ".join(forbidden)
        raise ExecutionAdvisoryValidationError(
            f"{field_name} contains prohibited lifecycle authority fields: {names}"
        )


def validate_execution_provenance(provenance: ExecutionProvenance) -> ExecutionProvenance:
    """Validate canonical provenance requirements."""

    _require_non_empty(provenance.source_system, field_name="provenance.source_system")
    _require_non_empty(provenance.source_type, field_name="provenance.source_type")
    _require_non_empty(provenance.source_id, field_name="provenance.source_id")
    return provenance


def validate_artifact_reference(artifact_reference: ArtifactReference) -> ArtifactReference:
    """Validate canonical artifact reference requirements."""

    _require_non_empty(artifact_reference.artifact_type, field_name="artifact_reference.artifact_type")
    _require_non_empty(artifact_reference.reference_id, field_name="artifact_reference.reference_id")
    if not any((artifact_reference.location, artifact_reference.external_id, artifact_reference.commit_sha)):
        raise ExecutionAdvisoryValidationError(
            "artifact_reference must include at least one locator: location, external_id, or commit_sha"
        )
    _validate_no_lifecycle_authority(artifact_reference.metadata, field_name="artifact_reference.metadata")
    if artifact_reference.provenance is not None:
        validate_execution_provenance(artifact_reference.provenance)
    return artifact_reference


def validate_advisory_completion_claim(claim: AdvisoryCompletionClaim) -> AdvisoryCompletionClaim:
    """Validate completion claim remains advisory only."""

    _require_non_empty(claim.claim_id, field_name="advisory_completion.claim_id")
    _validate_no_lifecycle_authority(claim.metadata, field_name="advisory_completion.metadata")
    return claim


def validate_execution_event(event: ExecutionEvent) -> ExecutionEvent:
    """Validate canonical execution event structure and constraints."""

    _require_non_empty(event.event_id, field_name="event.event_id")
    _require_non_empty(event.task_id, field_name="event.task_id")
    _require_non_empty(event.attempt_id, field_name="event.attempt_id")
    _require_non_empty(event.occurred_at, field_name="event.occurred_at")
    validate_execution_provenance(event.provenance)
    _validate_no_lifecycle_authority(event.metadata, field_name="event.metadata")

    for artifact_reference in event.artifact_references:
        validate_artifact_reference(artifact_reference)

    if event.advisory_completion is not None:
        validate_advisory_completion_claim(event.advisory_completion)
    return event


def derive_runtime_advisory_facts(events: tuple[ExecutionEvent, ...]) -> RuntimeAdvisoryFacts:
    """Derive normalized runtime verification facts from append-only events."""

    if not events:
        return RuntimeAdvisoryFacts(
            executor_reported_success=False,
            executor_reported_failure=False,
            terminal_failure=False,
            attempt_count=0,
        )

    success = False
    failure = False
    last_terminal_was_failure = False
    attempt_ids: set[str] = set()

    for event in events:
        validate_execution_event(event)
        attempt_ids.add(event.attempt_id)

        if event.event_type is ExecutionEventType.EXECUTION_SUCCEEDED:
            success = True
            last_terminal_was_failure = False
        elif event.event_type in _TERMINAL_FAILURE_EVENTS:
            failure = True
            last_terminal_was_failure = True

        if event.advisory_completion is not None and event.advisory_completion.reported_complete:
            success = True

    terminal_failure = failure and not success and last_terminal_was_failure
    return RuntimeAdvisoryFacts(
        executor_reported_success=success,
        executor_reported_failure=failure,
        terminal_failure=terminal_failure,
        attempt_count=len(attempt_ids),
    )


__all__ = [
    "AdvisoryCompletionClaim",
    "ArtifactReference",
    "ExecutionAdvisoryValidationError",
    "ExecutionEvent",
    "ExecutionEventType",
    "ExecutionProvenance",
    "RuntimeAdvisoryFacts",
    "derive_runtime_advisory_facts",
    "validate_advisory_completion_claim",
    "validate_artifact_reference",
    "validate_execution_event",
    "validate_execution_provenance",
]
