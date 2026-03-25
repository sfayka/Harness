"""Narrow OpenClaw-informed client spike against the public Harness API."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class OpenClawHarnessSpikeError(ValueError):
    """Raised when the spike client receives malformed local inputs."""


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _require_non_empty(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OpenClawHarnessSpikeError(f"{field_name} is required")
    return value.strip()


def _optional_string(value: str | None, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise OpenClawHarnessSpikeError(f"{field_name} must be a string when provided")
    stripped = value.strip()
    return stripped or None


@dataclass(frozen=True)
class OpenClawSourceContext:
    """Minimal OpenClaw-style source metadata for ingress submission."""

    conversation_id: str
    message_id: str
    channel: str
    workspace_id: str | None = None
    user_id: str | None = None
    agent_id: str | None = None


@dataclass(frozen=True)
class OpenClawTaskIntent:
    """Reviewable task intent extracted from an OpenClaw-side interaction."""

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
    requested_by: str | None = None


@dataclass(frozen=True)
class OpenClawHarnessSpikeResult:
    """Structured result for one representative OpenClaw -> Harness flow."""

    task_id: str
    submission_status: int
    submission_action: str | None
    initial_task_status: str | None
    reevaluation_status: int
    reevaluation_action: str | None
    final_task_status: str | None
    read_model_status: int
    timeline_status: int
    evaluation_history_count: int


def build_task_submission_payload(
    *,
    intent: OpenClawTaskIntent,
    context: OpenClawSourceContext,
    external_facts: dict[str, Any] | None = None,
    claimed_completion: bool = False,
    acceptance_criteria_satisfied: bool = False,
    runtime_facts: dict[str, Any] | None = None,
    unresolved_conditions: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Build a canonical POST /tasks payload from OpenClaw-side intent."""

    task_id = _require_non_empty(intent.task_id, field_name="intent.task_id")
    title = _require_non_empty(intent.title, field_name="intent.title")
    description = _require_non_empty(intent.description, field_name="intent.description")

    if not intent.acceptance_criteria:
        raise OpenClawHarnessSpikeError("intent.acceptance_criteria must contain at least one item")

    created_at = _iso_now()
    task_envelope: dict[str, Any] = {
        "id": task_id,
        "title": title,
        "description": description,
        "origin": {
            "source_system": "openclaw",
            "source_type": "ingress_request",
            "source_id": _require_non_empty(context.message_id, field_name="context.message_id"),
            "ingress_id": _optional_string(context.conversation_id, field_name="context.conversation_id"),
            "ingress_name": "OpenClaw",
            "requested_by": _optional_string(intent.requested_by or context.user_id, field_name="requested_by"),
        },
        "status": intent.status,
        "timestamps": {
            "created_at": created_at,
            "updated_at": created_at,
            "completed_at": created_at if intent.status == "completed" else None,
        },
        "status_history": [],
        "objective": {
            "summary": _require_non_empty(intent.objective_summary or description, field_name="intent.objective_summary"),
            "deliverable_type": _require_non_empty(intent.deliverable_type, field_name="intent.deliverable_type"),
            "success_signal": _require_non_empty(intent.success_signal, field_name="intent.success_signal"),
        },
        "constraints": [],
        "acceptance_criteria": [
            {
                "id": f"ac-{index + 1}",
                "description": _require_non_empty(criterion, field_name=f"intent.acceptance_criteria[{index}]"),
                "required": True,
            }
            for index, criterion in enumerate(intent.acceptance_criteria)
        ],
        "parent_task_id": None,
        "child_task_ids": [],
        "dependencies": [],
        "assigned_executor": None,
        "required_capabilities": [],
        "priority": intent.priority,
        "artifacts": {
            "items": [dict(artifact) for artifact in intent.linked_artifacts],
            "completion_evidence": dict(intent.completion_evidence)
            if intent.completion_evidence is not None
            else {
                "policy": "deferred",
                "status": "deferred",
                "required_artifact_types": [],
                "validated_artifact_ids": [],
                "validation_method": "deferred",
                "validated_at": None,
                "validator": None,
                "notes": None,
            },
        },
        "observability": {
            "errors": [],
            "retries": {
                "attempt_count": 0,
                "max_attempts": 0,
                "last_retry_at": None,
            },
            "execution_metadata": {},
        },
        "extensions": {
            "openclaw": {
                "conversation_id": context.conversation_id,
                "message_id": context.message_id,
                "channel": _require_non_empty(context.channel, field_name="context.channel"),
                "workspace_id": context.workspace_id,
                "user_id": context.user_id,
                "agent_id": context.agent_id,
            }
        },
    }

    request_payload: dict[str, Any] = {
        "task_envelope": task_envelope,
        "external_facts": dict(external_facts or {}),
        "claimed_completion": claimed_completion,
        "acceptance_criteria_satisfied": acceptance_criteria_satisfied,
    }
    if runtime_facts is not None:
        request_payload["runtime_facts"] = dict(runtime_facts)
    if unresolved_conditions:
        request_payload["unresolved_conditions"] = list(unresolved_conditions)
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
        "external_facts": dict(external_facts or {}),
        "new_artifacts": [dict(artifact) for artifact in new_artifacts],
        "claimed_completion": claimed_completion,
        "acceptance_criteria_satisfied": acceptance_criteria_satisfied,
    }
    if completion_evidence is not None:
        request_payload["completion_evidence"] = dict(completion_evidence)
    if runtime_facts is not None:
        request_payload["runtime_facts"] = dict(runtime_facts)
    if unresolved_conditions:
        request_payload["unresolved_conditions"] = list(unresolved_conditions)
    if review_request is not None:
        request_payload["review_request"] = dict(review_request)
    if review_decision is not None:
        request_payload["review_decision"] = dict(review_decision)
    return {"request": request_payload}


class OpenClawHarnessSpikeClient:
    """Thin OpenClaw-style HTTP client for the public Harness API."""

    def __init__(self, base_url: str) -> None:
        self.base_url = _require_non_empty(base_url.rstrip("/"), field_name="base_url")

    def _request_json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with urlopen(request) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            try:
                return error.code, json.loads(error.read().decode("utf-8"))
            finally:
                error.close()

    def submit_task(
        self,
        *,
        intent: OpenClawTaskIntent,
        context: OpenClawSourceContext,
        external_facts: dict[str, Any] | None = None,
        claimed_completion: bool = False,
        acceptance_criteria_satisfied: bool = False,
        runtime_facts: dict[str, Any] | None = None,
        unresolved_conditions: tuple[str, ...] = (),
    ) -> tuple[int, dict[str, Any]]:
        payload = build_task_submission_payload(
            intent=intent,
            context=context,
            external_facts=external_facts,
            claimed_completion=claimed_completion,
            acceptance_criteria_satisfied=acceptance_criteria_satisfied,
            runtime_facts=runtime_facts,
            unresolved_conditions=unresolved_conditions,
        )
        return self._request_json("POST", "/tasks", payload)

    def reevaluate_task(
        self,
        task_id: str,
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
    ) -> tuple[int, dict[str, Any]]:
        payload = build_task_reevaluation_payload(
            external_facts=external_facts,
            new_artifacts=new_artifacts,
            completion_evidence=completion_evidence,
            claimed_completion=claimed_completion,
            acceptance_criteria_satisfied=acceptance_criteria_satisfied,
            runtime_facts=runtime_facts,
            unresolved_conditions=unresolved_conditions,
            review_request=review_request,
            review_decision=review_decision,
        )
        return self._request_json("POST", f"/tasks/{task_id}/reevaluate", payload)

    def get_task(self, task_id: str) -> tuple[int, dict[str, Any]]:
        return self._request_json("GET", f"/tasks/{task_id}")

    def get_task_read_model(self, task_id: str) -> tuple[int, dict[str, Any]]:
        return self._request_json("GET", f"/tasks/{task_id}/read-model")

    def get_task_timeline(self, task_id: str) -> tuple[int, dict[str, Any]]:
        return self._request_json("GET", f"/tasks/{task_id}/timeline")

    def get_evaluation_history(self, task_id: str) -> tuple[int, dict[str, Any]]:
        return self._request_json("GET", f"/tasks/{task_id}/evaluations")


def _demo_review_note_artifact() -> dict[str, Any]:
    return {
        "id": "artifact-openclaw-review-note-1",
        "type": "review_note",
        "title": "Operator confirmation",
        "description": "OpenClaw supplied the missing evidence note during reevaluation.",
        "location": None,
        "content_type": "text/plain",
        "external_id": None,
        "commit_sha": None,
        "pull_request_number": None,
        "review_state": None,
        "provenance": {
            "source_system": "openclaw",
            "source_type": "manual",
            "source_id": "message-review-note-1",
            "captured_by": "openclaw-spike",
        },
        "verification_status": "verified",
        "repository": None,
        "branch": None,
        "changed_files": [],
        "external_refs": [],
        "captured_at": "2026-03-25T16:00:00Z",
        "metadata": {
            "note_kind": "manual_confirmation",
        },
    }


def run_openclaw_spike_flow(*, base_url: str, task_id: str = "task-openclaw-spike-1") -> OpenClawHarnessSpikeResult:
    """Run one representative OpenClaw -> Harness flow through the public API."""

    client = OpenClawHarnessSpikeClient(base_url)
    context = OpenClawSourceContext(
        conversation_id="conv-openclaw-spike-1",
        message_id="msg-openclaw-spike-1",
        channel="cli",
        workspace_id="workspace-openclaw-spike",
        user_id="operator@example.com",
        agent_id="openclaw-assistant",
    )
    intent = OpenClawTaskIntent(
        task_id=task_id,
        title="Validate Harness API boundary from OpenClaw",
        description="Submit a task, observe the blocked result, then reevaluate with the missing evidence supplied.",
        acceptance_criteria=(
            "Harness returns a structured blocked result before the missing evidence exists.",
            "Harness accepts completion once the missing evidence is supplied.",
        ),
        objective_summary="Prove that OpenClaw can submit and reevaluate tasks through the Harness API boundary.",
        deliverable_type="integration_spike",
        success_signal="The task moves from blocked to completed through public API calls only.",
        status="completed",
        linked_artifacts=(),
        completion_evidence={
            "policy": "required",
            "status": "insufficient",
            "required_artifact_types": ["review_note"],
            "validated_artifact_ids": [],
            "validation_method": "manual_review",
            "validated_at": None,
            "validator": None,
            "notes": "OpenClaw has not yet provided the operator confirmation artifact.",
        },
        requested_by="operator@example.com",
    )

    submission_status, submission_payload = client.submit_task(
        intent=intent,
        context=context,
        external_facts={},
        claimed_completion=True,
        acceptance_criteria_satisfied=True,
        runtime_facts={"executor_reported_success": True, "attempt_count": 1},
    )
    if submission_status >= 400:
        raise RuntimeError(f"OpenClaw spike submission failed: {submission_payload}")

    read_model_status, _ = client.get_task_read_model(task_id)
    if read_model_status >= 400:
        raise RuntimeError(f"OpenClaw spike read-model fetch failed for {task_id}")

    reevaluation_status, reevaluation_payload = client.reevaluate_task(
        task_id,
        new_artifacts=(_demo_review_note_artifact(),),
        completion_evidence={
            "status": "satisfied",
            "validated_artifact_ids": ["artifact-openclaw-review-note-1"],
            "validated_at": "2026-03-25T16:02:00Z",
            "validator": {
                "source_system": "harness",
                "source_type": "verification",
                "source_id": "verification/openclaw-spike-1",
                "captured_by": "openclaw-spike",
            },
            "notes": "The missing review note arrived from the OpenClaw-side operator flow.",
        },
        claimed_completion=True,
        acceptance_criteria_satisfied=True,
        runtime_facts={"executor_reported_success": True, "attempt_count": 1},
    )
    if reevaluation_status >= 400:
        raise RuntimeError(f"OpenClaw spike reevaluation failed: {reevaluation_payload}")

    timeline_status, _ = client.get_task_timeline(task_id)
    history_status, history_payload = client.get_evaluation_history(task_id)
    if timeline_status >= 400 or history_status >= 400:
        raise RuntimeError(f"OpenClaw spike inspection failed for {task_id}")

    return OpenClawHarnessSpikeResult(
        task_id=task_id,
        submission_status=submission_status,
        submission_action=submission_payload.get("action"),
        initial_task_status=submission_payload.get("task_envelope", {}).get("status"),
        reevaluation_status=reevaluation_status,
        reevaluation_action=reevaluation_payload.get("action"),
        final_task_status=reevaluation_payload.get("task_envelope", {}).get("status"),
        read_model_status=read_model_status,
        timeline_status=timeline_status,
        evaluation_history_count=len(history_payload.get("evaluations", ())),
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the spike CLI parser."""

    parser = argparse.ArgumentParser(description="Run a narrow OpenClaw-informed client spike against the Harness API.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Harness API base URL")
    parser.add_argument("--task-id", default="task-openclaw-spike-1", help="Task id to use for the representative spike")
    parser.add_argument("--json", action="store_true", dest="as_json", help="Emit machine-readable JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the OpenClaw-informed Harness spike."""

    args = build_parser().parse_args(argv)
    result = run_openclaw_spike_flow(base_url=args.base_url, task_id=args.task_id)

    if args.as_json:
        print(json.dumps(asdict(result), indent=2, sort_keys=True))
    else:
        print("OpenClaw -> Harness Spike")
        print(f"task_id: {result.task_id}")
        print(f"submission: {result.submission_status} ({result.submission_action}) -> {result.initial_task_status}")
        print(f"reevaluation: {result.reevaluation_status} ({result.reevaluation_action}) -> {result.final_task_status}")
        print(f"read_model: {result.read_model_status}")
        print(f"timeline: {result.timeline_status}")
        print(f"evaluation_history_count: {result.evaluation_history_count}")

    return 0


__all__ = [
    "OpenClawHarnessSpikeClient",
    "OpenClawHarnessSpikeError",
    "OpenClawHarnessSpikeResult",
    "OpenClawSourceContext",
    "OpenClawTaskIntent",
    "build_task_reevaluation_payload",
    "build_task_submission_payload",
    "run_openclaw_spike_flow",
]


if __name__ == "__main__":
    raise SystemExit(main())
