"""Deterministic local dry run for Symphony-like execution-substrate events."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from typing import Any

from modules.api import HarnessApiService
from modules.intake.task_envelope import create_task_envelope
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


__all__ = [
    "ExecutionSubstrateDryRunResult",
    "run_symphony_substrate_dry_run",
]
