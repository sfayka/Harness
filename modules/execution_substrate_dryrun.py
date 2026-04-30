"""Deterministic local dry run for Symphony-like execution-substrate events."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from typing import Any

from modules.adapters.symphony import SymphonyExecutionSubstrateAdapter
from modules.api import HarnessApiService
from modules.contracts.execution_substrate import (
    ExecutionSubstrateIntent,
    ExecutionSubstrateIntentType,
)
from modules.demo_cases import build_demo_request
from modules.intake.task_envelope import create_task_envelope
from modules.runtime_scenario_builders import to_jsonable
from modules.store import FileBackedHarnessStore


@dataclass(frozen=True)
class ExecutionSubstrateDryRunResult:
    """Structured result from the local execution-substrate dry run."""

    task_id: str
    event_statuses: tuple[int, ...]
    final_task_status: str | None
    accepted_completion: bool
    substrate_event_count: int
    latest_event_type: str | None
    latest_runner_session_id: str | None
    latest_workspace_id: str | None
    timeline_event_count: int


@dataclass(frozen=True)
class ExecutionSubstrateIntentDryRunResult:
    """Structured result from polling and consuming execution-substrate intents."""

    task_id: str
    initial_task_status: str | None
    intent_status: int
    intent_count: int
    consumed_intent_type: str | None
    event_statuses: tuple[int, ...]
    final_task_status: str | None
    accepted_completion: bool
    substrate_event_count: int
    latest_event_type: str | None


@dataclass(frozen=True)
class ExecutionSubstrateHandoffDryRunResult:
    """Structured result from rendering a Symphony-compatible handoff payload."""

    task_id: str
    initial_task_status: str | None
    intent_status: int
    intent_count: int
    rendered_intent_type: str | None
    handoff_mode: str
    events_url: str
    completion_authority: str
    runner_completion_is_truth: bool
    safe_to_execute_live: bool


def _disposable_task(task_id: str) -> dict[str, Any]:
    return create_task_envelope(
        {
            "id": task_id,
            "title": "Disposable Symphony substrate dry run",
            "description": "Exercise advisory runner events without live work execution.",
            "origin": {
                "source_system": "harness",
                "source_type": "system_generated",
                "source_id": f"dryrun/{task_id}",
            },
            "acceptance_criteria": [
                {
                    "id": "ac-1",
                    "description": "Runner handoff remains advisory until Harness verifies artifacts.",
                    "required": True,
                }
            ],
        },
        now="2026-04-28T13:00:00Z",
    )


def _runner_event_payload(
    *,
    task_id: str,
    event_id: str,
    attempt_id: str,
    event_type: str,
    occurred_at: str,
    payload: dict[str, Any] | None = None,
    artifact_references: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    runner_session_id = "symphony-dryrun-session-1"
    return {
        "event": {
            "event_id": event_id,
            "task_id": task_id,
            "attempt_id": attempt_id,
            "runner_kind": "symphony",
            "runner_session_id": runner_session_id,
            "executor_kind": "codex_app_server",
            "workspace_id": f"disposable/{task_id}",
            "event_type": event_type,
            "occurred_at": occurred_at,
            "provenance": {
                "source_system": "symphony-dryrun",
                "source_type": "runner_event",
                "source_id": f"{runner_session_id}:{event_id}",
                "captured_by": "execution_substrate_dryrun",
            },
            "payload": payload or {},
            "artifact_references": artifact_references or [],
        }
    }


def _event_sequence(task_id: str) -> tuple[dict[str, Any], ...]:
    attempt_id = "attempt-symphony-dryrun-1"
    return (
        _runner_event_payload(
            task_id=task_id,
            event_id="substrate-event-1",
            attempt_id=attempt_id,
            event_type="workspace_prepared",
            occurred_at="2026-04-28T13:01:00Z",
            payload={"workspace_policy": "disposable"},
        ),
        _runner_event_payload(
            task_id=task_id,
            event_id="substrate-event-2",
            attempt_id=attempt_id,
            event_type="runner_session_started",
            occurred_at="2026-04-28T13:02:00Z",
            payload={"concurrency_slot": "local-dryrun"},
        ),
        _runner_event_payload(
            task_id=task_id,
            event_id="substrate-event-3",
            attempt_id=attempt_id,
            event_type="run_heartbeat",
            occurred_at="2026-04-28T13:03:00Z",
            payload={"status": "running"},
        ),
        _runner_event_payload(
            task_id=task_id,
            event_id="substrate-event-4",
            attempt_id=attempt_id,
            event_type="artifact_reported",
            occurred_at="2026-04-28T13:04:00Z",
            artifact_references=[
                {
                    "artifact_type": "pull_request",
                    "repository": "KnoxAnalytics/HARNESS-DISPOSABLE",
                    "branch": "codex/symphony-dryrun",
                    "pr_url": "https://github.com/KnoxAnalytics/HARNESS-DISPOSABLE/pull/1",
                    "reported_by": "symphony-dryrun",
                    "reported_at": "2026-04-28T13:04:00Z",
                    "source_attempt_id": attempt_id,
                }
            ],
        ),
        _runner_event_payload(
            task_id=task_id,
            event_id="substrate-event-5",
            attempt_id=attempt_id,
            event_type="run_completed_by_executor",
            occurred_at="2026-04-28T13:05:00Z",
            payload={
                "reported_complete": True,
                "handoff_state": "human_review",
                "summary": "Dry-run executor reports handoff ready for Harness verification.",
            },
        ),
    )


def _intent_creation_payload(task_id: str) -> dict[str, Any]:
    payload = {"request": to_jsonable(build_demo_request("blocked_insufficient_evidence"))}
    payload["request"]["task_envelope"]["id"] = task_id
    payload["request"]["runtime_facts"] = {
        "executor_reported_failure": True,
        "attempt_count": 1,
        "latest_attempt_outcome": "failed",
    }
    return payload


def _intent_consumer_events(intent_entry: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    intent = intent_entry["intent"]
    task_id = str(intent["task_id"])
    attempt_id = f"attempt-{intent['intent_type']}-dryrun-1"
    return (
        _runner_event_payload(
            task_id=task_id,
            event_id="intent-consumer-event-1",
            attempt_id=attempt_id,
            event_type="dispatch_requested",
            occurred_at="2026-04-29T14:00:00Z",
            payload={
                "intent_type": intent["intent_type"],
                "source": intent["source"],
                "advisory_only": True,
            },
        ),
        _runner_event_payload(
            task_id=task_id,
            event_id="intent-consumer-event-2",
            attempt_id=attempt_id,
            event_type="runner_session_started",
            occurred_at="2026-04-29T14:01:00Z",
            payload={
                "substrate_kind": intent["substrate_kind"],
                "completion_authority": intent["completion_authority"],
            },
        ),
    )


def _with_env_var(name: str, value: str):
    class _EnvGuard:
        def __enter__(self) -> None:
            self._previous = os.environ.get(name)
            os.environ[name] = value

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            if self._previous is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = self._previous

    return _EnvGuard()


def _intent_from_payload(intent_payload: dict[str, Any]) -> ExecutionSubstrateIntent:
    return ExecutionSubstrateIntent(
        intent_type=ExecutionSubstrateIntentType(str(intent_payload["intent_type"])),
        substrate_kind=str(intent_payload["substrate_kind"]),
        task_id=str(intent_payload["task_id"]),
        source=str(intent_payload["source"]),
        reason=str(intent_payload["reason"]),
        suggested_action=str(intent_payload["suggested_action"]),
        events_endpoint=str(intent_payload["events_endpoint"]),
        advisory_only=bool(intent_payload["advisory_only"]),
        completion_authority=str(intent_payload["completion_authority"]),
        prohibited_actions=tuple(str(action) for action in intent_payload["prohibited_actions"]),
        metadata=(
            dict(intent_payload["metadata"])
            if isinstance(intent_payload.get("metadata"), dict)
            else {}
        ),
    )


def _create_retryable_task_and_poll_intent(
    *,
    service: HarnessApiService,
    task_id: str,
) -> tuple[dict[str, Any], int, dict[str, Any]]:
    with _with_env_var("HARNESS_CLASSIFIED_RETRY_BUDGET", "2"):
        create_status, create_payload = service.evaluate(_intent_creation_payload(task_id))
    if create_status != 200:
        raise RuntimeError(f"intent dry run create failed with HTTP {create_status}")

    intent_status, intent_payload = service.get_execution_substrate_intents()
    if intent_status != 200:
        raise RuntimeError(f"intent dry run poll failed with HTTP {intent_status}")
    intents = intent_payload.get("intents") if isinstance(intent_payload.get("intents"), list) else []
    if not intents:
        raise RuntimeError("intent dry run did not produce an execution-substrate intent")
    return create_payload, int(intent_status), intent_payload


def run_symphony_substrate_dry_run(
    *,
    task_id: str = "symphony-substrate-dryrun-1",
) -> ExecutionSubstrateDryRunResult:
    """Run a local deterministic Symphony-style event stream through Harness."""

    with tempfile.TemporaryDirectory() as temp_dir:
        store = FileBackedHarnessStore(temp_dir)
        service = HarnessApiService(store=store)
        store.create_task(_disposable_task(task_id))

        event_statuses = tuple(
            service.submit_execution_substrate_event(task_id, event_payload)[0]
            for event_payload in _event_sequence(task_id)
        )
        read_model_status, read_model = service.get_task_read_model(task_id)
        timeline_status, timeline = service.get_task_timeline(task_id)
        if read_model_status != 200:
            raise RuntimeError(f"read-model dry run failed with HTTP {read_model_status}")
        if timeline_status != 200:
            raise RuntimeError(f"timeline dry run failed with HTTP {timeline_status}")

        task = read_model["task"]
        execution_summary = task["execution_summary"]
        latest_event = execution_summary["latest_substrate_event"] or {}
        timeline_events = [
            event
            for event in timeline["timeline"]
            if event["event_type"] == "execution_substrate_event_recorded"
        ]
        return ExecutionSubstrateDryRunResult(
            task_id=task_id,
            event_statuses=event_statuses,
            final_task_status=task["current_status"],
            accepted_completion=task["current_status"] == "completed",
            substrate_event_count=execution_summary["substrate_event_count"],
            latest_event_type=latest_event.get("event_type"),
            latest_runner_session_id=execution_summary["latest_runner_session_id"],
            latest_workspace_id=execution_summary["latest_workspace_id"],
            timeline_event_count=len(timeline_events),
        )


def run_symphony_intent_consumer_dry_run(
    *,
    task_id: str = "symphony-intent-consumer-dryrun-1",
) -> ExecutionSubstrateIntentDryRunResult:
    """Poll Harness substrate intents and consume one through advisory events."""

    with tempfile.TemporaryDirectory() as temp_dir:
        store = FileBackedHarnessStore(temp_dir)
        service = HarnessApiService(store=store)
        create_payload, intent_status, intent_payload = _create_retryable_task_and_poll_intent(
            service=service,
            task_id=task_id,
        )

        intent_entry = intent_payload["intents"][0]
        event_statuses = tuple(
            service.submit_execution_substrate_event(task_id, event_payload)[0]
            for event_payload in _intent_consumer_events(intent_entry)
        )
        read_model_status, read_model = service.get_task_read_model(task_id)
        if read_model_status != 200:
            raise RuntimeError(f"intent dry run read-model failed with HTTP {read_model_status}")

        task = read_model["task"]
        execution_summary = task["execution_summary"]
        latest_event = execution_summary["latest_substrate_event"] or {}
        return ExecutionSubstrateIntentDryRunResult(
            task_id=task_id,
            initial_task_status=(
                str((create_payload.get("task_envelope") or {}).get("status"))
                if isinstance(create_payload.get("task_envelope"), dict)
                else None
            ),
            intent_status=intent_status,
            intent_count=int(intent_payload["intent_count"]),
            consumed_intent_type=str(intent_entry["intent"]["intent_type"]),
            event_statuses=event_statuses,
            final_task_status=task["current_status"],
            accepted_completion=task["current_status"] == "completed",
            substrate_event_count=execution_summary["substrate_event_count"],
            latest_event_type=latest_event.get("event_type"),
        )


def run_symphony_handoff_dry_run(
    *,
    task_id: str = "symphony-handoff-dryrun-1",
    harness_base_url: str = "http://127.0.0.1:8765",
) -> ExecutionSubstrateHandoffDryRunResult:
    """Render a Symphony-compatible handoff payload from a local Harness intent."""

    with tempfile.TemporaryDirectory() as temp_dir:
        store = FileBackedHarnessStore(temp_dir)
        service = HarnessApiService(store=store)
        create_payload, intent_status, intent_payload = _create_retryable_task_and_poll_intent(
            service=service,
            task_id=task_id,
        )

        intent_entry = intent_payload["intents"][0]
        handoff = SymphonyExecutionSubstrateAdapter(
            harness_base_url=harness_base_url,
        ).render_handoff(_intent_from_payload(intent_entry["intent"]))
        handoff_payload = handoff.to_dict()
        return ExecutionSubstrateHandoffDryRunResult(
            task_id=task_id,
            initial_task_status=(
                str((create_payload.get("task_envelope") or {}).get("status"))
                if isinstance(create_payload.get("task_envelope"), dict)
                else None
            ),
            intent_status=intent_status,
            intent_count=int(intent_payload["intent_count"]),
            rendered_intent_type=handoff_payload["intent"].get("intent_type"),
            handoff_mode=str(handoff_payload["mode"]),
            events_url=str(handoff_payload["callback"]["events_url"]),
            completion_authority=str(handoff_payload["harness_boundary"]["completion_authority"]),
            runner_completion_is_truth=bool(
                handoff_payload["harness_boundary"]["runner_completion_is_truth"]
            ),
            safe_to_execute_live=bool(handoff_payload["metadata"]["safe_to_execute_live"]),
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run deterministic local Symphony execution-substrate dry runs.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    event_stream = subparsers.add_parser(
        "event-stream",
        help="Record a local Symphony-style runner event stream against a disposable task.",
    )
    event_stream.add_argument(
        "--task-id",
        default="symphony-substrate-dryrun-1",
        help="Disposable Harness task id to use for the dry run.",
    )

    intent_consumer = subparsers.add_parser(
        "intent-consumer",
        help="Poll local execution-substrate intents and record advisory runner events.",
    )
    intent_consumer.add_argument(
        "--task-id",
        default="symphony-intent-consumer-dryrun-1",
        help="Disposable Harness task id to use for the dry run.",
    )

    handoff = subparsers.add_parser(
        "handoff",
        help="Render a local Symphony-compatible handoff payload without starting Symphony.",
    )
    handoff.add_argument(
        "--task-id",
        default="symphony-handoff-dryrun-1",
        help="Disposable Harness task id to use for the dry run.",
    )
    handoff.add_argument(
        "--harness-base-url",
        default="http://127.0.0.1:8765",
        help="Base Harness URL to use when rendering callback URLs.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "event-stream":
        result = run_symphony_substrate_dry_run(task_id=args.task_id)
    elif args.command == "intent-consumer":
        result = run_symphony_intent_consumer_dry_run(task_id=args.task_id)
    elif args.command == "handoff":
        result = run_symphony_handoff_dry_run(
            task_id=args.task_id,
            harness_base_url=args.harness_base_url,
        )
    else:  # pragma: no cover - argparse prevents this branch.
        parser.error(f"unsupported command: {args.command}")

    print(json.dumps(asdict(result), indent=2, sort_keys=True))
    return 0


__all__ = [
    "ExecutionSubstrateDryRunResult",
    "ExecutionSubstrateHandoffDryRunResult",
    "ExecutionSubstrateIntentDryRunResult",
    "build_parser",
    "main",
    "run_symphony_handoff_dry_run",
    "run_symphony_intent_consumer_dry_run",
    "run_symphony_substrate_dry_run",
]


if __name__ == "__main__":
    raise SystemExit(main())
