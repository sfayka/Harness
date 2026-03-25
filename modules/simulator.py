"""OpenClaw-style ingress simulator that exercises the public Harness HTTP API."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from modules.contracts.task_envelope_review import (
    ReviewOutcome,
    ReviewRequest,
    ReviewTrigger,
    ReviewerIdentity,
    resolve_review_request,
)
from modules.demo_cases import build_demo_request


def _to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _to_jsonable(val) for key, val in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _to_jsonable(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    return value


def _canonical_payload(case_name: str) -> dict[str, Any]:
    return {"request": _to_jsonable(build_demo_request(case_name))}


def _customize_canonical_payload(
    payload: dict[str, Any],
    *,
    task_id_override: str | None = None,
    task_title_override: str | None = None,
    origin_source_id_override: str | None = None,
) -> dict[str, Any]:
    customized = deepcopy(payload)
    request = customized.get("request")
    if not isinstance(request, dict):
        return customized

    task_envelope = request.get("task_envelope")
    if isinstance(task_envelope, dict):
        if task_id_override is not None:
            task_envelope["id"] = task_id_override
        if task_title_override is not None:
            task_envelope["title"] = task_title_override
        origin = task_envelope.get("origin")
        if isinstance(origin, dict) and origin_source_id_override is not None:
            origin["source_id"] = origin_source_id_override

    review_request = request.get("review_request")
    if isinstance(review_request, dict) and task_id_override is not None:
        review_request["task_id"] = task_id_override

    return customized


def _review_note_artifact(artifact_id: str = "artifact-review-note-sim-1") -> dict[str, Any]:
    return {
        "id": artifact_id,
        "type": "review_note",
        "title": "Manual evidence note",
        "description": "The missing evidence was confirmed during simulator re-evaluation.",
        "location": None,
        "content_type": "text/plain",
        "external_id": None,
        "commit_sha": None,
        "pull_request_number": None,
        "review_state": None,
        "provenance": {
            "source_system": "harness",
            "source_type": "manual_review",
            "source_id": f"review/{artifact_id}",
            "captured_by": "openclaw-simulator",
        },
        "verification_status": "verified",
        "repository": None,
        "branch": None,
        "changed_files": [],
        "external_refs": [],
        "captured_at": "2026-03-25T12:00:00Z",
        "metadata": {},
    }


def _progress_artifact(artifact_id: str = "artifact-progress-sim-1") -> dict[str, Any]:
    return {
        "id": artifact_id,
        "type": "progress_artifact",
        "title": "Progress update",
        "description": "The worker reports incremental progress before completion evidence is ready.",
        "location": None,
        "content_type": "application/json",
        "external_id": None,
        "commit_sha": None,
        "pull_request_number": None,
        "review_state": None,
        "provenance": {
            "source_system": "codex",
            "source_type": "executor_report",
            "source_id": f"progress/{artifact_id}",
            "captured_by": "openclaw-simulator",
        },
        "verification_status": "informational",
        "repository": None,
        "branch": None,
        "changed_files": [],
        "external_refs": [],
        "captured_at": "2026-03-25T12:05:00Z",
        "metadata": {
            "completed_items": "2",
            "remaining_items": "1",
        },
    }


def _handoff_artifact(artifact_id: str = "artifact-handoff-sim-1") -> dict[str, Any]:
    return {
        "id": artifact_id,
        "type": "handoff_artifact",
        "title": "Session handoff",
        "description": "The task is being handed off across sessions before verification can complete.",
        "location": None,
        "content_type": "application/json",
        "external_id": None,
        "commit_sha": None,
        "pull_request_number": None,
        "review_state": None,
        "provenance": {
            "source_system": "codex",
            "source_type": "executor_report",
            "source_id": f"handoff/{artifact_id}",
            "captured_by": "openclaw-simulator",
        },
        "verification_status": "informational",
        "repository": None,
        "branch": None,
        "changed_files": [],
        "external_refs": [],
        "captured_at": "2026-03-25T12:10:00Z",
        "metadata": {
            "resume_hint": "Continue after artifact sync completes.",
        },
    }


@dataclass(frozen=True)
class SimulationStepResult:
    """One recorded API interaction in a simulator scenario."""

    name: str
    method: str
    path: str
    http_status: int
    action: str | None
    target_status: str | None
    task_status: str | None
    task_id: str | None
    request_payload: dict[str, Any] | None
    payload: dict[str, Any]


@dataclass(frozen=True)
class SimulationResult:
    """Structured result for one end-to-end simulator scenario."""

    scenario_name: str
    final_task_id: str | None
    final_task_status: str | None
    steps: tuple[SimulationStepResult, ...]
    task_snapshot: dict[str, Any] | None
    evaluation_history: tuple[dict[str, Any], ...]


class HarnessSimulatorClient:
    """Thin HTTP client that uses only the public Harness API surface."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

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

    def submit_task(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        return self._request_json("POST", "/tasks", payload)

    def reevaluate_task(self, task_id: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        return self._request_json("POST", f"/tasks/{task_id}/reevaluate", payload)

    def get_task(self, task_id: str) -> tuple[int, dict[str, Any]]:
        return self._request_json("GET", f"/tasks/{task_id}")

    def get_evaluation_history(self, task_id: str) -> tuple[int, dict[str, Any]]:
        return self._request_json("GET", f"/tasks/{task_id}/evaluations")


class _ScenarioContext:
    def __init__(
        self,
        *,
        task_id_override: str | None = None,
        task_title_override: str | None = None,
        origin_source_id_override: str | None = None,
    ) -> None:
        self.task_id: str | None = None
        self.steps: list[SimulationStepResult] = []
        self.task_id_override = task_id_override
        self.task_title_override = task_title_override
        self.origin_source_id_override = origin_source_id_override

    def canonical_payload(self, case_name: str) -> dict[str, Any]:
        return _customize_canonical_payload(
            _canonical_payload(case_name),
            task_id_override=self.task_id_override,
            task_title_override=self.task_title_override,
            origin_source_id_override=self.origin_source_id_override,
        )

    def record(
        self,
        *,
        name: str,
        method: str,
        path: str,
        http_status: int,
        request_payload: dict[str, Any] | None,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        task_envelope = payload.get("task_envelope")
        task_id = payload.get("task_envelope", {}).get("id") if isinstance(task_envelope, dict) else None
        if task_id is None and "task" in payload and isinstance(payload["task"], dict):
            task_id = payload["task"].get("id")
        if task_id is None and "task_id" in payload:
            task_id = payload.get("task_id")
        if task_id is not None:
            self.task_id = str(task_id)

        self.steps.append(
            SimulationStepResult(
                name=name,
                method=method,
                path=path,
                http_status=http_status,
                action=payload.get("action"),
                target_status=payload.get("target_status"),
                task_status=(task_envelope or payload.get("task") or {}).get("status")
                if isinstance(task_envelope or payload.get("task"), dict)
                else None,
                task_id=self.task_id,
                request_payload=deepcopy(request_payload),
                payload=payload,
            )
        )
        return payload


def _submit_step(client: HarnessSimulatorClient, context: _ScenarioContext, name: str, payload: dict[str, Any]) -> dict[str, Any]:
    status, response_payload = client.submit_task(payload)
    return context.record(
        name=name,
        method="POST",
        path="/tasks",
        http_status=status,
        request_payload=payload,
        payload=response_payload,
    )


def _reevaluate_step(
    client: HarnessSimulatorClient,
    context: _ScenarioContext,
    name: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if context.task_id is None:
        raise ValueError("task_id is required before reevaluation")
    path = f"/tasks/{context.task_id}/reevaluate"
    status, response_payload = client.reevaluate_task(context.task_id, payload)
    return context.record(
        name=name,
        method="POST",
        path=path,
        http_status=status,
        request_payload=payload,
        payload=response_payload,
    )


def _fetch_final_state(client: HarnessSimulatorClient, context: _ScenarioContext) -> tuple[dict[str, Any] | None, tuple[dict[str, Any], ...]]:
    if context.task_id is None:
        return None, ()

    _, task_payload = client.get_task(context.task_id)
    _, history_payload = client.get_evaluation_history(context.task_id)
    return task_payload.get("task"), tuple(history_payload.get("evaluations", ()))


def _review_request_payload(task_id: str) -> dict[str, Any]:
    request = ReviewRequest(
        review_request_id="review-request-sim-1",
        task_id=task_id,
        requested_at="2026-03-25T12:15:00Z",
        requested_by="verification",
        trigger=ReviewTrigger.RECONCILIATION,
        summary="Manual review is required before completion can be accepted.",
        presented_sections=("task_state", "evidence", "reconciliation"),
        allowed_outcomes=(ReviewOutcome.ACCEPT_COMPLETION, ReviewOutcome.KEEP_BLOCKED),
    )
    return _to_jsonable(request)


def _review_decision_payload(task_id: str) -> dict[str, Any]:
    request = ReviewRequest(
        review_request_id="review-request-sim-1",
        task_id=task_id,
        requested_at="2026-03-25T12:15:00Z",
        requested_by="verification",
        trigger=ReviewTrigger.RECONCILIATION,
        summary="Manual review is required before completion can be accepted.",
        presented_sections=("task_state", "evidence", "reconciliation"),
        allowed_outcomes=(ReviewOutcome.ACCEPT_COMPLETION,),
    )
    decision = resolve_review_request(
        request,
        review_id="review-sim-1",
        reviewer=ReviewerIdentity(
            reviewer_id="operator-1",
            reviewer_name="Simulator Reviewer",
            authority_role="operator",
        ),
        outcome=ReviewOutcome.ACCEPT_COMPLETION,
        reasoning="The reviewed facts support accepted completion.",
    )
    return _to_jsonable(decision)


def _scenario_successful_completion(
    client: HarnessSimulatorClient,
    *,
    task_id_override: str | None = None,
    task_title_override: str | None = None,
    origin_source_id_override: str | None = None,
) -> SimulationResult:
    context = _ScenarioContext(
        task_id_override=task_id_override,
        task_title_override=task_title_override,
        origin_source_id_override=origin_source_id_override,
    )
    _submit_step(client, context, "submit", context.canonical_payload("accepted_completion"))
    task_snapshot, history = _fetch_final_state(client, context)
    return SimulationResult("successful_completion", context.task_id, task_snapshot.get("status") if task_snapshot else None, tuple(context.steps), task_snapshot, history)


def _scenario_missing_evidence_then_completed(
    client: HarnessSimulatorClient,
    *,
    task_id_override: str | None = None,
    task_title_override: str | None = None,
    origin_source_id_override: str | None = None,
) -> SimulationResult:
    context = _ScenarioContext(
        task_id_override=task_id_override,
        task_title_override=task_title_override,
        origin_source_id_override=origin_source_id_override,
    )
    initial_payload = context.canonical_payload("blocked_insufficient_evidence")
    _submit_step(client, context, "submit", initial_payload)
    _reevaluate_step(
        client,
        context,
        "provide_missing_evidence",
        {
            "request": {
                "new_artifacts": [_review_note_artifact()],
                "completion_evidence": {
                    "validated_artifact_ids": [
                        "artifact-pr-1",
                        "artifact-commit-1",
                        "artifact-review-note-sim-1",
                    ]
                },
                "external_facts": deepcopy(context.canonical_payload("accepted_completion")["request"]["external_facts"]),
                "claimed_completion": True,
                "acceptance_criteria_satisfied": True,
                "runtime_facts": deepcopy(initial_payload["request"]["runtime_facts"]),
            }
        },
    )
    task_snapshot, history = _fetch_final_state(client, context)
    return SimulationResult("missing_evidence_then_completed", context.task_id, task_snapshot.get("status") if task_snapshot else None, tuple(context.steps), task_snapshot, history)


def _scenario_wrong_target_corrected(
    client: HarnessSimulatorClient,
    *,
    task_id_override: str | None = None,
    task_title_override: str | None = None,
    origin_source_id_override: str | None = None,
) -> SimulationResult:
    context = _ScenarioContext(
        task_id_override=task_id_override,
        task_title_override=task_title_override,
        origin_source_id_override=origin_source_id_override,
    )
    initial_payload = context.canonical_payload("accepted_completion")
    wrong_target_payload = deepcopy(initial_payload)
    wrong_target_payload["request"]["task_envelope"]["status"] = "blocked"
    wrong_target_payload["request"]["task_envelope"]["timestamps"]["completed_at"] = None
    wrong_target_payload["request"]["external_facts"]["github_facts"]["branch"]["name"] = "codex/wrong-target"

    _submit_step(client, context, "submit", wrong_target_payload)
    _reevaluate_step(
        client,
        context,
        "correct_artifact_target",
        {
            "request": {
                "external_facts": deepcopy(initial_payload["request"]["external_facts"]),
                "claimed_completion": True,
                "acceptance_criteria_satisfied": True,
                "runtime_facts": deepcopy(initial_payload["request"]["runtime_facts"]),
            }
        },
    )
    task_snapshot, history = _fetch_final_state(client, context)
    return SimulationResult("wrong_target_corrected", context.task_id, task_snapshot.get("status") if task_snapshot else None, tuple(context.steps), task_snapshot, history)


def _scenario_review_required_then_completed(
    client: HarnessSimulatorClient,
    *,
    task_id_override: str | None = None,
    task_title_override: str | None = None,
    origin_source_id_override: str | None = None,
) -> SimulationResult:
    context = _ScenarioContext(
        task_id_override=task_id_override,
        task_title_override=task_title_override,
        origin_source_id_override=origin_source_id_override,
    )
    accepted_payload = context.canonical_payload("accepted_completion")
    review_payload = {
        "request": deepcopy(accepted_payload["request"]),
    }
    review_payload["request"]["task_envelope"]["status"] = "blocked"
    review_payload["request"]["task_envelope"]["timestamps"]["completed_at"] = None
    review_payload["request"]["review_request"] = _review_request_payload(review_payload["request"]["task_envelope"]["id"])
    review_payload["request"]["external_facts"] = deepcopy(context.canonical_payload("review_required")["request"]["external_facts"])

    _submit_step(client, context, "submit", review_payload)
    _reevaluate_step(
        client,
        context,
        "resolve_review",
        {
            "request": {
                "review_decision": _review_decision_payload(context.task_id or review_payload["request"]["task_envelope"]["id"]),
            }
        },
    )
    task_snapshot, history = _fetch_final_state(client, context)
    return SimulationResult("review_required_then_completed", context.task_id, task_snapshot.get("status") if task_snapshot else None, tuple(context.steps), task_snapshot, history)


def _scenario_contradictory_facts_rollback(
    client: HarnessSimulatorClient,
    *,
    task_id_override: str | None = None,
    task_title_override: str | None = None,
    origin_source_id_override: str | None = None,
) -> SimulationResult:
    context = _ScenarioContext(
        task_id_override=task_id_override,
        task_title_override=task_title_override,
        origin_source_id_override=origin_source_id_override,
    )
    accepted_payload = context.canonical_payload("accepted_completion")
    _submit_step(client, context, "submit", accepted_payload)
    _reevaluate_step(
        client,
        context,
        "introduce_contradictory_facts",
        {
            "request": {
                "external_facts": deepcopy(context.canonical_payload("blocked_reconciliation_mismatch")["request"]["external_facts"]),
                "claimed_completion": True,
                "acceptance_criteria_satisfied": True,
                "runtime_facts": deepcopy(accepted_payload["request"]["runtime_facts"]),
            }
        },
    )
    _reevaluate_step(
        client,
        context,
        "resolve_contradiction",
        {
            "request": {
                "external_facts": deepcopy(accepted_payload["request"]["external_facts"]),
                "claimed_completion": True,
                "acceptance_criteria_satisfied": True,
                "runtime_facts": deepcopy(accepted_payload["request"]["runtime_facts"]),
            }
        },
    )
    task_snapshot, history = _fetch_final_state(client, context)
    return SimulationResult("contradictory_facts_rollback", context.task_id, task_snapshot.get("status") if task_snapshot else None, tuple(context.steps), task_snapshot, history)


def _scenario_contradictory_facts_blocked(
    client: HarnessSimulatorClient,
    *,
    task_id_override: str | None = None,
    task_title_override: str | None = None,
    origin_source_id_override: str | None = None,
) -> SimulationResult:
    context = _ScenarioContext(
        task_id_override=task_id_override,
        task_title_override=task_title_override,
        origin_source_id_override=origin_source_id_override,
    )
    accepted_payload = context.canonical_payload("accepted_completion")
    _submit_step(client, context, "submit", accepted_payload)
    _reevaluate_step(
        client,
        context,
        "introduce_contradictory_facts",
        {
            "request": {
                "external_facts": deepcopy(context.canonical_payload("blocked_reconciliation_mismatch")["request"]["external_facts"]),
                "claimed_completion": True,
                "acceptance_criteria_satisfied": True,
                "runtime_facts": deepcopy(accepted_payload["request"]["runtime_facts"]),
            }
        },
    )
    task_snapshot, history = _fetch_final_state(client, context)
    return SimulationResult(
        "contradictory_facts_blocked",
        context.task_id,
        task_snapshot.get("status") if task_snapshot else None,
        tuple(context.steps),
        task_snapshot,
        history,
    )


def _scenario_long_running_handoff(
    client: HarnessSimulatorClient,
    *,
    task_id_override: str | None = None,
    task_title_override: str | None = None,
    origin_source_id_override: str | None = None,
) -> SimulationResult:
    context = _ScenarioContext(
        task_id_override=task_id_override,
        task_title_override=task_title_override,
        origin_source_id_override=origin_source_id_override,
    )
    initial_payload = context.canonical_payload("blocked_insufficient_evidence")
    _submit_step(client, context, "submit", initial_payload)
    _reevaluate_step(
        client,
        context,
        "append_progress_artifact",
        {
            "request": {
                "new_artifacts": [_progress_artifact()],
                "external_facts": deepcopy(initial_payload["request"]["external_facts"]),
                "claimed_completion": True,
                "acceptance_criteria_satisfied": True,
                "runtime_facts": deepcopy(initial_payload["request"]["runtime_facts"]),
            }
        },
    )
    _reevaluate_step(
        client,
        context,
        "append_handoff_artifact",
        {
            "request": {
                "new_artifacts": [_handoff_artifact()],
                "external_facts": deepcopy(initial_payload["request"]["external_facts"]),
                "claimed_completion": True,
                "acceptance_criteria_satisfied": True,
                "runtime_facts": deepcopy(initial_payload["request"]["runtime_facts"]),
            }
        },
    )
    _reevaluate_step(
        client,
        context,
        "complete_after_handoff",
        {
            "request": {
                "new_artifacts": [_review_note_artifact()],
                "completion_evidence": {
                    "validated_artifact_ids": [
                        "artifact-pr-1",
                        "artifact-commit-1",
                        "artifact-review-note-sim-1",
                    ]
                },
                "external_facts": deepcopy(context.canonical_payload("accepted_completion")["request"]["external_facts"]),
                "claimed_completion": True,
                "acceptance_criteria_satisfied": True,
                "runtime_facts": deepcopy(initial_payload["request"]["runtime_facts"]),
            }
        },
    )
    task_snapshot, history = _fetch_final_state(client, context)
    return SimulationResult("long_running_handoff", context.task_id, task_snapshot.get("status") if task_snapshot else None, tuple(context.steps), task_snapshot, history)


_SCENARIOS = {
    "successful_completion": _scenario_successful_completion,
    "missing_evidence_then_completed": _scenario_missing_evidence_then_completed,
    "wrong_target_corrected": _scenario_wrong_target_corrected,
    "review_required_then_completed": _scenario_review_required_then_completed,
    "contradictory_facts_blocked": _scenario_contradictory_facts_blocked,
    "contradictory_facts_rollback": _scenario_contradictory_facts_rollback,
    "long_running_handoff": _scenario_long_running_handoff,
}


def list_scenarios() -> tuple[str, ...]:
    """Return the supported OpenClaw-style simulator scenarios."""

    return tuple(_SCENARIOS.keys())


def run_scenario(
    scenario_name: str,
    *,
    base_url: str = "http://127.0.0.1:8000",
    task_id_override: str | None = None,
    task_title_override: str | None = None,
    origin_source_id_override: str | None = None,
) -> SimulationResult:
    """Run one simulator scenario entirely through the public Harness HTTP API."""

    if scenario_name not in _SCENARIOS:
        raise ValueError(f"Unknown simulator scenario {scenario_name!r}")
    return _SCENARIOS[scenario_name](
        HarnessSimulatorClient(base_url),
        task_id_override=task_id_override,
        task_title_override=task_title_override,
        origin_source_id_override=origin_source_id_override,
    )


def _format_step(step: SimulationStepResult) -> str:
    lines = [
        f"- {step.name}: {step.method} {step.path} -> {step.http_status}",
        f"  action={step.action} target_status={step.target_status} task_status={step.task_status}",
    ]
    return "\n".join(lines)


def _format_text_result(result: SimulationResult) -> str:
    lines = [
        f"scenario: {result.scenario_name}",
        f"final_task_id: {result.final_task_id}",
        f"final_task_status: {result.final_task_status}",
        "steps:",
    ]
    lines.extend(_format_step(step) for step in result.steps)
    lines.append(f"evaluation_count: {len(result.evaluation_history)}")
    if result.task_snapshot is not None:
        artifact_count = len(result.task_snapshot.get("artifacts", {}).get("items", []))
        lines.append(f"artifact_count: {artifact_count}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    """Build the simulator CLI parser."""

    parser = argparse.ArgumentParser(description="Run an OpenClaw-style ingress simulator against the Harness API.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Harness API base URL")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List simulator scenarios")
    list_parser.add_argument("--json", action="store_true", dest="as_json", help="Emit machine-readable JSON output")

    run_parser = subparsers.add_parser("run", help="Run one simulator scenario")
    run_parser.add_argument("scenario_name", choices=list_scenarios(), help="Simulator scenario to run")
    run_parser.add_argument("--json", action="store_true", dest="as_json", help="Emit machine-readable JSON output")

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the OpenClaw-style ingress simulator."""

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "list":
        scenarios = list_scenarios()
        if args.as_json:
            print(json.dumps({"scenarios": list(scenarios)}, indent=2, sort_keys=True))
        else:
            print("\n".join(scenarios))
        return 0

    result = run_scenario(args.scenario_name, base_url=args.base_url)
    payload = _to_jsonable(result)
    if args.as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(_format_text_result(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
