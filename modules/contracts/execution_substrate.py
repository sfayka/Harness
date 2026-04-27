"""Canonical execution-substrate event models.

These models describe events from a Symphony-like runner. They are distinct
from executor events because the runner owns workspace/session orchestration,
not task completion truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ExecutionSubstrateValidationError(ValueError):
    """Raised when execution-substrate events are malformed."""


class ExecutionSubstrateEventType(StrEnum):
    """Canonical event family emitted by Symphony-like runner substrates."""

    DISPATCH_REQUESTED = "dispatch_requested"
    DISPATCH_STARTED = "dispatch_started"
    WORKSPACE_PREPARED = "workspace_prepared"
    RUNNER_SESSION_STARTED = "runner_session_started"
    RUN_HEARTBEAT = "run_heartbeat"
    PROGRESS_REPORTED = "progress_reported"
    ARTIFACT_REPORTED = "artifact_reported"
    HANDOFF_REPORTED = "handoff_reported"
    RUN_STALLED = "run_stalled"
    RUN_TIMED_OUT = "run_timed_out"
    RUN_FAILED = "run_failed"
    RETRY_SCHEDULED = "retry_scheduled"
    RETRY_STARTED = "retry_started"
    RUN_CANCELLED = "run_cancelled"
    RUN_COMPLETED_BY_EXECUTOR = "run_completed_by_executor"


_PROHIBITED_LIFECYCLE_KEYS: frozenset[str] = frozenset(
    {
        "accepted_completion",
        "authorized_transition",
        "canonical_status",
        "completion_authorized",
        "harness_status",
        "lifecycle_status",
        "target_status",
        "verified_complete",
    }
)


def _require_non_empty(value: str | None, *, field_name: str) -> None:
    if value is None or not value.strip():
        raise ExecutionSubstrateValidationError(f"{field_name} is required")


def _validate_no_lifecycle_authority(payload: dict[str, Any], *, field_name: str) -> None:
    forbidden = sorted(set(payload).intersection(_PROHIBITED_LIFECYCLE_KEYS))
    if forbidden:
        names = ", ".join(forbidden)
        raise ExecutionSubstrateValidationError(
            f"{field_name} contains prohibited lifecycle authority fields: {names}"
        )


@dataclass(frozen=True)
class ExecutionSubstrateProvenance:
    """Source attribution for a runner event."""

    source_system: str
    source_type: str
    source_id: str
    captured_by: str | None = None


@dataclass(frozen=True)
class ExecutionSubstrateArtifactReference:
    """Artifact reference reported by a runner before Harness verification."""

    artifact_type: str
    reported_by: str
    reported_at: str
    source_attempt_id: str
    verification_status: str = "unverified"
    repository: str | None = None
    branch: str | None = None
    commit_sha: str | None = None
    pr_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionSubstrateEvent:
    """Append-only advisory event from a Symphony-like runner."""

    event_id: str
    task_id: str
    attempt_id: str
    runner_kind: str
    runner_session_id: str
    executor_kind: str
    workspace_id: str
    event_type: ExecutionSubstrateEventType
    occurred_at: str
    provenance: ExecutionSubstrateProvenance
    payload: dict[str, Any] = field(default_factory=dict)
    artifact_references: tuple[ExecutionSubstrateArtifactReference, ...] = ()


def validate_execution_substrate_provenance(
    provenance: ExecutionSubstrateProvenance,
) -> ExecutionSubstrateProvenance:
    """Validate runner event provenance."""

    _require_non_empty(provenance.source_system, field_name="provenance.source_system")
    _require_non_empty(provenance.source_type, field_name="provenance.source_type")
    _require_non_empty(provenance.source_id, field_name="provenance.source_id")
    return provenance


def validate_execution_substrate_artifact_reference(
    artifact_reference: ExecutionSubstrateArtifactReference,
) -> ExecutionSubstrateArtifactReference:
    """Validate an unverified runner-reported artifact reference."""

    _require_non_empty(artifact_reference.artifact_type, field_name="artifact_reference.artifact_type")
    _require_non_empty(artifact_reference.reported_by, field_name="artifact_reference.reported_by")
    _require_non_empty(artifact_reference.reported_at, field_name="artifact_reference.reported_at")
    _require_non_empty(
        artifact_reference.source_attempt_id,
        field_name="artifact_reference.source_attempt_id",
    )
    _require_non_empty(
        artifact_reference.verification_status,
        field_name="artifact_reference.verification_status",
    )
    if artifact_reference.verification_status == "verified":
        raise ExecutionSubstrateValidationError(
            "runner-reported artifacts must not start with verification_status=verified"
        )
    if not any(
        (
            artifact_reference.repository,
            artifact_reference.branch,
            artifact_reference.commit_sha,
            artifact_reference.pr_url,
        )
    ):
        raise ExecutionSubstrateValidationError(
            "artifact_reference must include at least one locator: repository, branch, commit_sha, or pr_url"
        )
    _validate_no_lifecycle_authority(
        artifact_reference.metadata,
        field_name="artifact_reference.metadata",
    )
    return artifact_reference


def validate_execution_substrate_event(event: ExecutionSubstrateEvent) -> ExecutionSubstrateEvent:
    """Validate a Symphony-like runner event as advisory-only execution input."""

    _require_non_empty(event.event_id, field_name="event.event_id")
    _require_non_empty(event.task_id, field_name="event.task_id")
    _require_non_empty(event.attempt_id, field_name="event.attempt_id")
    _require_non_empty(event.runner_kind, field_name="event.runner_kind")
    _require_non_empty(event.runner_session_id, field_name="event.runner_session_id")
    _require_non_empty(event.executor_kind, field_name="event.executor_kind")
    _require_non_empty(event.workspace_id, field_name="event.workspace_id")
    _require_non_empty(event.occurred_at, field_name="event.occurred_at")
    validate_execution_substrate_provenance(event.provenance)
    _validate_no_lifecycle_authority(event.payload, field_name="event.payload")

    for artifact_reference in event.artifact_references:
        validate_execution_substrate_artifact_reference(artifact_reference)
    return event


__all__ = [
    "ExecutionSubstrateArtifactReference",
    "ExecutionSubstrateEvent",
    "ExecutionSubstrateEventType",
    "ExecutionSubstrateProvenance",
    "ExecutionSubstrateValidationError",
    "validate_execution_substrate_artifact_reference",
    "validate_execution_substrate_event",
    "validate_execution_substrate_provenance",
]
