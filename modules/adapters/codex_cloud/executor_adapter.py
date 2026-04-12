"""Codex Cloud executor adapter with repo/bootstrap preflight enforcement."""

from __future__ import annotations

import re
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

_EXPECTED_REPO_ROOT = "/workspace/Harness"
_EXPECTED_REMOTE_URL = "https://github.com/sfayka/Harness.git"
_BOOTSTRAP_COMMAND = "bash /workspace/Harness/scripts/codex-cloud-setup.sh"
_PREFLIGHT_COMMANDS = ("pwd", "git remote -v", "cat .codex-bootstrap-proof")


class CodexCloudAdapterError(ValueError):
    """Raised when Codex Cloud adapter inputs or outputs are invalid."""


class CodexCloudRuntimeClient(Protocol):
    """Transport abstraction for a Codex Cloud execution call."""

    def execute(self, request_payload: dict[str, Any]) -> dict[str, Any]:
        """Execute a Codex Cloud run and return raw runtime payload."""


@dataclass(frozen=True)
class CodexCloudExecutorAdapter:
    """Translate canonical dispatch input across the Codex Cloud execution boundary."""

    runtime_client: CodexCloudRuntimeClient

    adapter_name: str = "codex-cloud"

    def dispatch(self, dispatch_input: ExecutorDispatchInput) -> ExecutorDispatchOutput:
        request_payload = self._to_codex_cloud_request(dispatch_input)
        response_payload = self.runtime_client.execute(request_payload)
        return self._to_canonical_output(dispatch_input=dispatch_input, response_payload=response_payload)

    def _to_codex_cloud_request(self, dispatch_input: ExecutorDispatchInput) -> dict[str, Any]:
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
                "branch_hint": _branch_hint(dispatch_input.task_id),
            },
            "context": {
                "references": list(dispatch_input.context_references),
                "origin_source": dispatch_input.metadata.get("origin_source"),
                "priority": dispatch_input.metadata.get("priority"),
            },
            "execution": {
                "executor": dispatch_input.assigned_executor,
                "adapter": self.adapter_name,
                "bootstrap_command": _BOOTSTRAP_COMMAND,
                "preflight_commands": list(_PREFLIGHT_COMMANDS),
            },
        }

    def _to_canonical_output(
        self,
        *,
        dispatch_input: ExecutorDispatchInput,
        response_payload: dict[str, Any],
    ) -> ExecutorDispatchOutput:
        if not isinstance(response_payload, dict):
            raise CodexCloudAdapterError("Codex Cloud response payload must be an object")

        run_id = _require_non_empty(response_payload.get("run_id"), field_name="response.run_id")
        preflight = _require_mapping(response_payload.get("preflight"), field_name="response.preflight")
        preflight_reason = _validate_preflight(preflight)
        preflight_passed = preflight_reason is None

        if preflight_passed:
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
                    {"id": "started", "type": "run_started", "timestamp": _utc_now()},
                    {"id": "completed", "type": "run_succeeded", "timestamp": _utc_now()},
                ]
            completion_claim = self._normalize_completion_claim(response_payload.get("completion"), run_id=run_id)
            events = tuple(
                self._normalize_event(
                    dispatch_input=dispatch_input,
                    run_id=run_id,
                    event_payload=event_payload,
                    index=index,
                    artifacts=artifacts,
                    completion_claim=completion_claim,
                )
                for index, event_payload in enumerate(raw_events)
            )
        else:
            artifacts = ()
            events = (
                _started_event(dispatch_input=dispatch_input, run_id=run_id),
                _failed_preflight_event(
                    dispatch_input=dispatch_input,
                    run_id=run_id,
                    reason=preflight_reason,
                ),
            )

        return ExecutorDispatchOutput(
            events=events,
            artifact_references=artifacts,
            metadata={
                "adapter": self.adapter_name,
                "codex_cloud_run_id": run_id,
                "advisory_only": True,
                "request_shape": "codex-cloud.execute.v1",
                "preflight_passed": preflight_passed,
                "preflight_failure_reason": preflight_reason,
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
            raise CodexCloudAdapterError(f"response.events[{index}] must be an object")
        raw_type = _require_non_empty(event_payload.get("type"), field_name=f"response.events[{index}].type")
        event_type = _normalize_event_type(raw_type)
        event_id = _require_non_empty(event_payload.get("id"), field_name=f"response.events[{index}].id")
        occurred_at = _require_non_empty(event_payload.get("timestamp"), field_name=f"response.events[{index}].timestamp")

        advisory_completion: AdvisoryCompletionClaim | None = None
        if completion_claim is not None and event_type == ExecutionEventType.EXECUTION_SUCCEEDED:
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
                provenance=_provenance(run_id=run_id, source_id=event_id, source_type="executor_event"),
                artifact_references=attached_artifacts,
                advisory_completion=advisory_completion,
                metadata={
                    "adapter": self.adapter_name,
                    "codex_cloud_event_type": raw_type,
                    "codex_cloud_run_id": run_id,
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
            raise CodexCloudAdapterError(f"response.artifacts[{index}] must be an object")
        artifact_type = _require_non_empty(artifact_payload.get("type"), field_name=f"response.artifacts[{index}].type")
        artifact_id = _require_non_empty(artifact_payload.get("id"), field_name=f"response.artifacts[{index}].id")
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
                provenance=_provenance(run_id=run_id, source_id=artifact_id, source_type="executor_artifact"),
                metadata={"adapter": self.adapter_name},
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
            raise CodexCloudAdapterError("response.completion must be an object")
        return AdvisoryCompletionClaim(
            claim_id=f"{run_id}:completion",
            reported_complete=bool(completion_payload.get("reported_complete")),
            confidence=(
                completion_payload.get("confidence")
                if isinstance(completion_payload.get("confidence"), str) and completion_payload.get("confidence").strip()
                else None
            ),
            reason=(
                completion_payload.get("reason")
                if isinstance(completion_payload.get("reason"), str) and completion_payload.get("reason").strip()
                else None
            ),
            metadata={"advisory_only": True, "adapter": self.adapter_name},
        )


def _require_non_empty(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CodexCloudAdapterError(f"{field_name} is required")
    return value.strip()


def _require_mapping(value: Any, *, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CodexCloudAdapterError(f"{field_name} must be an object")
    return value


def _require_list(value: Any, field_name: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise CodexCloudAdapterError(f"{field_name} must be a list")
    return value


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
        raise CodexCloudAdapterError(f"Unsupported Codex Cloud event type: {raw_type}")
    return normalized


def _branch_hint(task_id: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", task_id.strip().lower()).strip("-")
    if not slug:
        slug = "task"
    return f"codex/{slug}"


def _validate_preflight(preflight: dict[str, Any]) -> str | None:
    pwd = _require_non_empty(preflight.get("pwd"), field_name="response.preflight.pwd")
    git_remote_v = _require_non_empty(preflight.get("git_remote_v"), field_name="response.preflight.git_remote_v")
    bootstrap_proof = preflight.get("bootstrap_proof")
    if bootstrap_proof is None or not isinstance(bootstrap_proof, str):
        return "Codex Cloud preflight failed: bootstrap proof is missing"
    if pwd != _EXPECTED_REPO_ROOT:
        return f"Codex Cloud preflight failed: wrong repository root {pwd!r}"
    if _EXPECTED_REMOTE_URL not in git_remote_v or "origin" not in git_remote_v:
        return "Codex Cloud preflight failed: origin remote does not match the canonical Harness repository"
    if not bootstrap_proof.strip():
        return "Codex Cloud preflight failed: bootstrap proof is missing"
    return None


def _provenance(*, run_id: str, source_id: str, source_type: str) -> ExecutionProvenance:
    return ExecutionProvenance(
        source_system="codex-cloud",
        source_type=source_type,
        source_id=f"{run_id}:{source_id}",
        captured_by="codex_cloud_adapter",
    )


def _started_event(*, dispatch_input: ExecutorDispatchInput, run_id: str) -> ExecutionEvent:
    return validate_execution_event(
        ExecutionEvent(
            event_id=f"{dispatch_input.attempt_id}:started",
            task_id=dispatch_input.task_id,
            attempt_id=dispatch_input.attempt_id,
            event_type=ExecutionEventType.EXECUTION_STARTED,
            occurred_at=_utc_now(),
            provenance=_provenance(run_id=run_id, source_id="started", source_type="executor_event"),
            metadata={"adapter": "codex-cloud", "codex_cloud_run_id": run_id},
        )
    )


def _failed_preflight_event(
    *,
    dispatch_input: ExecutorDispatchInput,
    run_id: str,
    reason: str,
) -> ExecutionEvent:
    return validate_execution_event(
        ExecutionEvent(
            event_id=f"{dispatch_input.attempt_id}:preflight-failed",
            task_id=dispatch_input.task_id,
            attempt_id=dispatch_input.attempt_id,
            event_type=ExecutionEventType.EXECUTION_FAILED,
            occurred_at=_utc_now(),
            provenance=_provenance(run_id=run_id, source_id="preflight-failed", source_type="executor_event"),
            metadata={
                "adapter": "codex-cloud",
                "codex_cloud_run_id": run_id,
                "preflight_failure_reason": reason,
            },
        )
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = ["CodexCloudAdapterError", "CodexCloudExecutorAdapter", "CodexCloudRuntimeClient"]
