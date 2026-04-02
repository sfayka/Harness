"""Executor adapter interface and stub implementation.

This module defines a canonical executor-agnostic boundary for dispatching work to
executor runtimes while preserving Harness control-plane authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from modules.contracts.execution_advisory import (
    AdvisoryCompletionClaim,
    ArtifactReference,
    ExecutionEvent,
    ExecutionEventType,
    ExecutionProvenance,
    validate_artifact_reference,
    validate_execution_event,
)


class ExecutorAdapterInputError(ValueError):
    """Raised when canonical executor input cannot be constructed."""


@dataclass(frozen=True)
class ExecutorDispatchInput:
    """Canonical input accepted by any executor adapter implementation."""

    task_id: str
    attempt_id: str
    title: str
    description: str
    objective_summary: str
    acceptance_criteria: tuple[str, ...]
    constraints: tuple[str, ...]
    required_artifact_types: tuple[str, ...]
    context_references: tuple[str, ...]
    assigned_executor: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_task_envelope(
        cls,
        task_envelope: dict[str, Any],
        *,
        attempt_id: str,
        assigned_executor: str,
        context_references: tuple[str, ...] = (),
    ) -> "ExecutorDispatchInput":
        """Build canonical executor input from ``TaskEnvelope``-derived data."""

        if not isinstance(task_envelope, dict):
            raise ExecutorAdapterInputError("task_envelope must be an object")

        task_id = _require_non_empty(task_envelope.get("id"), field_name="task_envelope.id")
        title = _require_non_empty(task_envelope.get("title"), field_name="task_envelope.title")
        description = _require_non_empty(
            task_envelope.get("description"), field_name="task_envelope.description"
        )

        objective = task_envelope.get("objective")
        if not isinstance(objective, dict):
            raise ExecutorAdapterInputError("task_envelope.objective must be an object")
        objective_summary = _require_non_empty(
            objective.get("summary"), field_name="task_envelope.objective.summary"
        )

        acceptance = task_envelope.get("acceptance_criteria")
        if not isinstance(acceptance, list) or not acceptance:
            raise ExecutorAdapterInputError("task_envelope.acceptance_criteria must be a non-empty list")

        acceptance_criteria: list[str] = []
        for index, criterion in enumerate(acceptance):
            if not isinstance(criterion, dict):
                raise ExecutorAdapterInputError(
                    f"task_envelope.acceptance_criteria[{index}] must be an object"
                )
            acceptance_criteria.append(
                _require_non_empty(
                    criterion.get("description"),
                    field_name=f"task_envelope.acceptance_criteria[{index}].description",
                )
            )

        constraints_raw = task_envelope.get("constraints")
        if constraints_raw is None:
            constraints_raw = []
        if not isinstance(constraints_raw, list):
            raise ExecutorAdapterInputError("task_envelope.constraints must be a list")

        constraints: list[str] = []
        for index, constraint in enumerate(constraints_raw):
            if not isinstance(constraint, dict):
                raise ExecutorAdapterInputError(f"task_envelope.constraints[{index}] must be an object")
            constraints.append(
                _require_non_empty(
                    constraint.get("description"),
                    field_name=f"task_envelope.constraints[{index}].description",
                )
            )

        completion_evidence = (
            ((task_envelope.get("artifacts") or {}).get("completion_evidence") or {})
            if isinstance(task_envelope.get("artifacts"), dict)
            else {}
        )
        required_artifact_types = tuple(
            str(value)
            for value in completion_evidence.get("required_artifact_types", [])
            if isinstance(value, str) and value.strip()
        )

        metadata = {
            "origin_source": ((task_envelope.get("origin") or {}).get("source_system")),
            "priority": task_envelope.get("priority"),
        }

        return cls(
            task_id=task_id,
            attempt_id=_require_non_empty(attempt_id, field_name="attempt_id"),
            title=title,
            description=description,
            objective_summary=objective_summary,
            acceptance_criteria=tuple(acceptance_criteria),
            constraints=tuple(constraints),
            required_artifact_types=required_artifact_types,
            context_references=tuple(context_references),
            assigned_executor=_require_non_empty(assigned_executor, field_name="assigned_executor"),
            metadata=metadata,
        )


@dataclass(frozen=True)
class ExecutorDispatchOutput:
    """Canonical advisory output from executor adapters."""

    events: tuple[ExecutionEvent, ...]
    artifact_references: tuple[ArtifactReference, ...]
    metadata: dict[str, Any] = field(default_factory=dict)


class ExecutorAdapter(Protocol):
    """Executor-agnostic dispatch protocol for adapter implementations."""

    adapter_name: str

    def dispatch(self, dispatch_input: ExecutorDispatchInput) -> ExecutorDispatchOutput:
        """Execute work and return canonical advisory output."""


class StubExecutorAdapter:
    """Contract-compliant stub adapter with advisory-only outputs."""

    adapter_name = "stub-executor"

    def __init__(self, *, now_provider: Callable[[], str] | None = None) -> None:
        self._now_provider = now_provider or _utc_now

    def dispatch(self, dispatch_input: ExecutorDispatchInput) -> ExecutorDispatchOutput:
        started_at = self._now_provider()
        succeeded_at = self._now_provider()

        started_event = validate_execution_event(
            ExecutionEvent(
                event_id=f"{dispatch_input.attempt_id}:started",
                task_id=dispatch_input.task_id,
                attempt_id=dispatch_input.attempt_id,
                event_type=ExecutionEventType.EXECUTION_STARTED,
                occurred_at=started_at,
                provenance=_event_provenance(
                    source_id=f"{dispatch_input.attempt_id}:started",
                    adapter_name=self.adapter_name,
                ),
                metadata={
                    "adapter": self.adapter_name,
                    "mode": "stub",
                },
            )
        )

        artifact_reference = validate_artifact_reference(
            ArtifactReference(
                artifact_type="execution_log",
                reference_id=f"{dispatch_input.attempt_id}:log",
                location=f"stub://executions/{dispatch_input.task_id}/{dispatch_input.attempt_id}/log",
                provenance=_event_provenance(
                    source_id=f"{dispatch_input.attempt_id}:log",
                    adapter_name=self.adapter_name,
                ),
                metadata={
                    "advisory": True,
                },
            )
        )

        completed_event = validate_execution_event(
            ExecutionEvent(
                event_id=f"{dispatch_input.attempt_id}:completed",
                task_id=dispatch_input.task_id,
                attempt_id=dispatch_input.attempt_id,
                event_type=ExecutionEventType.EXECUTION_SUCCEEDED,
                occurred_at=succeeded_at,
                provenance=_event_provenance(
                    source_id=f"{dispatch_input.attempt_id}:completed",
                    adapter_name=self.adapter_name,
                ),
                artifact_references=(artifact_reference,),
                advisory_completion=AdvisoryCompletionClaim(
                    claim_id=f"{dispatch_input.attempt_id}:claim",
                    reported_complete=True,
                    confidence="low",
                    reason="stub adapter emits non-authoritative completion claim",
                    metadata={"advisory_only": True},
                ),
                metadata={
                    "adapter": self.adapter_name,
                    "executor_run_id": f"stub-run-{dispatch_input.attempt_id}",
                },
            )
        )

        return ExecutorDispatchOutput(
            events=(started_event, completed_event),
            artifact_references=(artifact_reference,),
            metadata={
                "adapter": self.adapter_name,
                "advisory_only": True,
                "event_count": 2,
            },
        )


def _require_non_empty(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExecutorAdapterInputError(f"{field_name} is required")
    return value.strip()


def _event_provenance(*, source_id: str, adapter_name: str) -> ExecutionProvenance:
    return ExecutionProvenance(
        source_system=adapter_name,
        source_type="executor_event",
        source_id=source_id,
        captured_by="executor_adapter",
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = [
    "ExecutorAdapter",
    "ExecutorAdapterInputError",
    "ExecutorDispatchInput",
    "ExecutorDispatchOutput",
    "StubExecutorAdapter",
]
