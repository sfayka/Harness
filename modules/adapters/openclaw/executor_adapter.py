"""Minimal real OpenClaw executor adapter implementation.

This module isolates OpenClaw request/response translation while returning canonical
advisory execution facts consumed by Harness.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from modules.adapters.executor_adapter import ExecutorDispatchInput, ExecutorDispatchOutput
from modules.contracts.execution_advisory import (
    AdvisoryCompletionClaim,
    ArtifactReference,
    ExecutionEvent,
    ExecutionEventType,
    ExecutionProvenance,
    validate_artifact_reference,
    validate_execution_event,
)


class OpenClawAdapterError(ValueError):
    """Raised when OpenClaw adapter inputs or outputs are invalid."""


class OpenClawRuntimeClient(Protocol):
    """Transport abstraction for a minimal OpenClaw execution call."""

    def execute(self, request_payload: dict[str, Any]) -> dict[str, Any]:
        """Execute an OpenClaw run and return raw OpenClaw response payload."""


@dataclass(frozen=True)
class OpenClawExecutorAdapter:
    """Minimal real adapter that translates canonical input across the OpenClaw boundary."""

    runtime_client: OpenClawRuntimeClient

    adapter_name: str = "openclaw"

    def dispatch(self, dispatch_input: ExecutorDispatchInput) -> ExecutorDispatchOutput:
        request_payload = self._to_openclaw_request(dispatch_input)
        response_payload = self.runtime_client.execute(request_payload)
        return self._to_canonical_output(dispatch_input=dispatch_input, response_payload=response_payload)

    def _to_openclaw_request(self, dispatch_input: ExecutorDispatchInput) -> dict[str, Any]:
        return {
            "task": {
                "id": dispatch_input.task_id,
                "attempt_id": dispatch_input.attempt_id,
                "title": dispatch_input.title,
                "description": dispatch_input.description,
                "objective": dispatch_input.objective_summary,
                "acceptance_criteria": list(dispatch_input.acceptance_criteria),
                "constraints": list(dispatch_input.constraints),
                "required_artifacts": list(dispatch_input.required_artifact_types),
            },
            "context": {
                "references": list(dispatch_input.context_references),
                "origin_source": dispatch_input.metadata.get("origin_source"),
                "priority": dispatch_input.metadata.get("priority"),
            },
            "executor": {
                "target": dispatch_input.assigned_executor,
                "adapter": self.adapter_name,
            },
        }

    def _to_canonical_output(
        self,
        *,
        dispatch_input: ExecutorDispatchInput,
        response_payload: dict[str, Any],
    ) -> ExecutorDispatchOutput:
        if not isinstance(response_payload, dict):
            raise OpenClawAdapterError("OpenClaw response payload must be an object")

        run_id = _require_non_empty(response_payload.get("run_id"), field_name="response.run_id")

        artifacts = tuple(
            self._normalize_artifact(
                dispatch_input=dispatch_input,
                run_id=run_id,
                artifact_payload=artifact_payload,
                index=index,
            )
            for index, artifact_payload in enumerate(_require_list(response_payload.get("artifacts"), "response.artifacts"))
        )

        raw_events = _require_list(response_payload.get("events"), "response.events")
        if not raw_events:
            raw_events = [
                {
                    "id": f"{run_id}:started",
                    "type": "run_started",
                    "timestamp": _utc_now(),
                    "message": "OpenClaw run started",
                },
                {
                    "id": f"{run_id}:completed",
                    "type": "run_succeeded",
                    "timestamp": _utc_now(),
                    "message": "OpenClaw run completed",
                },
            ]

        completion_payload = response_payload.get("completion")
        completion_claim = self._normalize_completion_claim(completion_payload, run_id=run_id)

        canonical_events: list[ExecutionEvent] = []
        for index, event_payload in enumerate(raw_events):
            canonical_events.append(
                self._normalize_event(
                    dispatch_input=dispatch_input,
                    run_id=run_id,
                    event_payload=event_payload,
                    index=index,
                    artifacts=artifacts,
                    completion_claim=completion_claim,
                )
            )

        return ExecutorDispatchOutput(
            events=tuple(canonical_events),
            artifact_references=artifacts,
            metadata={
                "adapter": self.adapter_name,
                "openclaw_run_id": run_id,
                "advisory_only": True,
                "request_shape": "openclaw.execute.v1",
            },
        )

    def _normalize_event(
        self,
        *,
        dispatch_input: ExecutorDispatchInput,
        run_id: str,
        event_payload: Any,
        index: int,
        artifacts: tuple[ArtifactReference, ...],
        completion_claim: AdvisoryCompletionClaim | None,
    ) -> ExecutionEvent:
        if not isinstance(event_payload, dict):
            raise OpenClawAdapterError(f"response.events[{index}] must be an object")

        raw_type = _require_non_empty(event_payload.get("type"), field_name=f"response.events[{index}].type")
        event_type = _normalize_event_type(raw_type)

        event_id = _require_non_empty(event_payload.get("id"), field_name=f"response.events[{index}].id")
        occurred_at = _require_non_empty(
            event_payload.get("timestamp"),
            field_name=f"response.events[{index}].timestamp",
        )

        advisory_completion: AdvisoryCompletionClaim | None = None
        if completion_claim is not None and event_type in {
            ExecutionEventType.EXECUTION_SUCCEEDED,
            ExecutionEventType.EXECUTION_FAILED,
            ExecutionEventType.EXECUTION_TIMED_OUT,
            ExecutionEventType.EXECUTION_CANCELED,
        }:
            advisory_completion = completion_claim

        attached_artifacts: tuple[ArtifactReference, ...] = ()
        if event_type in {
            ExecutionEventType.ARTIFACT_ATTACHED,
            ExecutionEventType.OUTPUT_ATTACHED,
            ExecutionEventType.EXECUTION_SUCCEEDED,
        }:
            attached_artifacts = artifacts

        return validate_execution_event(
            ExecutionEvent(
                event_id=f"{dispatch_input.attempt_id}:{event_id}",
                task_id=dispatch_input.task_id,
                attempt_id=dispatch_input.attempt_id,
                event_type=event_type,
                occurred_at=occurred_at,
                provenance=ExecutionProvenance(
                    source_system="openclaw",
                    source_type="executor_event",
                    source_id=f"{run_id}:{event_id}",
                    captured_by="openclaw_adapter",
                ),
                artifact_references=attached_artifacts,
                advisory_completion=advisory_completion,
                metadata={
                    "adapter": self.adapter_name,
                    "openclaw_event_type": raw_type,
                    "openclaw_run_id": run_id,
                },
            )
        )

    def _normalize_artifact(
        self,
        *,
        dispatch_input: ExecutorDispatchInput,
        run_id: str,
        artifact_payload: Any,
        index: int,
    ) -> ArtifactReference:
        if not isinstance(artifact_payload, dict):
            raise OpenClawAdapterError(f"response.artifacts[{index}] must be an object")

        artifact_type = _require_non_empty(
            artifact_payload.get("type"),
            field_name=f"response.artifacts[{index}].type",
        )
        artifact_id = _require_non_empty(
            artifact_payload.get("id"),
            field_name=f"response.artifacts[{index}].id",
        )

        location = artifact_payload.get("url")
        external_id = artifact_payload.get("external_id")
        commit_sha = artifact_payload.get("commit_sha")

        return validate_artifact_reference(
            ArtifactReference(
                artifact_type=artifact_type,
                reference_id=f"{dispatch_input.attempt_id}:{artifact_id}",
                location=location if isinstance(location, str) and location.strip() else None,
                external_id=external_id if isinstance(external_id, str) and external_id.strip() else None,
                commit_sha=commit_sha if isinstance(commit_sha, str) and commit_sha.strip() else None,
                provenance=ExecutionProvenance(
                    source_system="openclaw",
                    source_type="executor_artifact",
                    source_id=f"{run_id}:{artifact_id}",
                    captured_by="openclaw_adapter",
                ),
                metadata={
                    "adapter": self.adapter_name,
                },
            )
        )

    def _normalize_completion_claim(
        self,
        completion_payload: Any,
        *,
        run_id: str,
    ) -> AdvisoryCompletionClaim | None:
        if completion_payload is None:
            return None
        if not isinstance(completion_payload, dict):
            raise OpenClawAdapterError("response.completion must be an object")

        reported_complete = bool(completion_payload.get("reported_complete"))
        confidence = completion_payload.get("confidence")
        reason = completion_payload.get("reason")

        return AdvisoryCompletionClaim(
            claim_id=f"{run_id}:completion",
            reported_complete=reported_complete,
            confidence=confidence if isinstance(confidence, str) and confidence.strip() else None,
            reason=reason if isinstance(reason, str) and reason.strip() else None,
            metadata={"advisory_only": True, "adapter": self.adapter_name},
        )


def _normalize_event_type(raw_type: str) -> ExecutionEventType:
    mapping = {
        "run_started": ExecutionEventType.EXECUTION_STARTED,
        "progress": ExecutionEventType.PROGRESS_REPORTED,
        "output": ExecutionEventType.OUTPUT_ATTACHED,
        "artifact_attached": ExecutionEventType.ARTIFACT_ATTACHED,
        "run_failed": ExecutionEventType.EXECUTION_FAILED,
        "run_succeeded": ExecutionEventType.EXECUTION_SUCCEEDED,
        "run_stalled": ExecutionEventType.EXECUTION_STALLED,
        "run_timed_out": ExecutionEventType.EXECUTION_TIMED_OUT,
        "retry_scheduled": ExecutionEventType.RETRY_SCHEDULED,
        "retry_started": ExecutionEventType.RETRY_STARTED,
        "run_canceled": ExecutionEventType.EXECUTION_CANCELED,
    }
    normalized = mapping.get(raw_type)
    if normalized is None:
        raise OpenClawAdapterError(f"Unsupported OpenClaw event type: {raw_type}")
    return normalized


def _require_non_empty(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OpenClawAdapterError(f"{field_name} is required")
    return value.strip()


def _require_list(value: Any, field_name: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise OpenClawAdapterError(f"{field_name} must be a list")
    return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = ["OpenClawAdapterError", "OpenClawExecutorAdapter", "OpenClawRuntimeClient"]
