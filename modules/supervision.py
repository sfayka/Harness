"""Canonical supervision queue for autonomous OpenClaw-style polling."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from modules.read_model import HarnessReadModelService
from modules.store import HarnessStore, build_harness_store


def _parse_iso_timestamp(value: str | None) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


@dataclass(frozen=True)
class SupervisionQueueEntry:
    task_id: str
    title: str
    current_status: str
    attention_type: str
    suggested_action: str
    reason: str
    last_activity_at: str | None
    stale: bool
    review_status: str
    clarification_status: str
    failure_state: str
    retry_eligible: bool


class HarnessSupervisionService:
    """Project canonical task truth into an attention queue for autonomous supervisors."""

    def __init__(
        self,
        *,
        store: HarnessStore | None = None,
        now_provider: Callable[[], str] | None = None,
        stale_after_seconds_by_status: dict[str, int] | None = None,
    ) -> None:
        resolved_store = store or build_harness_store()
        self.read_model_service = HarnessReadModelService(store=resolved_store)
        self._now_provider = now_provider or self._iso_now
        self._stale_after_seconds_by_status = stale_after_seconds_by_status or {
            "planned": 24 * 60 * 60,
            "dispatch_ready": 2 * 60 * 60,
            "assigned": 2 * 60 * 60,
            "blocked": 8 * 60 * 60,
        }

    @staticmethod
    def _iso_now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def _last_activity_at(self, task: dict[str, Any]) -> str | None:
        timeline = task.get("timeline")
        events = [event for event in timeline if isinstance(event, dict)] if isinstance(timeline, list) else []
        if events:
            latest_event = max(
                events,
                key=lambda event: (
                    _parse_iso_timestamp(str(event.get("occurred_at") or "")),
                    str(event.get("event_id") or ""),
                ),
            )
            occurred_at = latest_event.get("occurred_at")
            if occurred_at is not None:
                return str(occurred_at)

        timestamps = task.get("timestamps") if isinstance(task.get("timestamps"), dict) else {}
        updated_at = timestamps.get("updated_at")
        if updated_at is not None:
            return str(updated_at)
        created_at = timestamps.get("created_at")
        return str(created_at) if created_at is not None else None

    def _is_stale(self, task: dict[str, Any], *, last_activity_at: str | None) -> bool:
        current_status = str(task.get("current_status") or "")
        threshold_seconds = self._stale_after_seconds_by_status.get(current_status)
        if threshold_seconds is None:
            return False
        if not last_activity_at:
            return False
        return (_parse_iso_timestamp(self._now_provider()) - _parse_iso_timestamp(last_activity_at)).total_seconds() >= threshold_seconds

    def _classify_attention(
        self,
        task: dict[str, Any],
        *,
        last_activity_at: str | None,
    ) -> tuple[str, str, str, bool] | None:
        current_status = str(task.get("current_status") or "")
        review_summary = task.get("review_summary") if isinstance(task.get("review_summary"), dict) else {}
        clarification_summary = (
            task.get("clarification_summary") if isinstance(task.get("clarification_summary"), dict) else {}
        )
        failure_summary = task.get("failure_summary") if isinstance(task.get("failure_summary"), dict) else {}
        execution_summary = task.get("execution_summary") if isinstance(task.get("execution_summary"), dict) else {}
        latest_attempt_validation = (
            execution_summary.get("latest_attempt_validation")
            if isinstance(execution_summary.get("latest_attempt_validation"), dict)
            else {}
        )

        if current_status == "in_review" or str(review_summary.get("status") or "none") == "requested":
            return (
                "review_required",
                "resolve_review_gate",
                "Task has an active manual review gate that blocks autonomous completion.",
                False,
            )
        if str(clarification_summary.get("status") or "none") == "required":
            return (
                "clarification_required",
                "collect_clarification",
                "Task is blocked on explicit clarification and cannot proceed safely.",
                False,
            )
        if str(latest_attempt_validation.get("status") or "") == "invalid":
            return (
                "invalid_execution_attempt",
                "request_fresh_proof_or_rework",
                "Latest execution attempt failed the current-run proof contract.",
                False,
            )
        if bool(execution_summary.get("retry_eligible")) or str(failure_summary.get("state") or "") == "retryable":
            return (
                "retryable_failure",
                "retry_or_redispatch",
                "Task is in a retryable failure state and remains eligible for governed recovery.",
                False,
            )

        stale = self._is_stale(task, last_activity_at=last_activity_at)
        if stale:
            return (
                "stale_active_task",
                "investigate_staleness",
                "Task is active but has not produced recent canonical activity.",
                True,
            )
        return None

    def list_attention_queue(self) -> list[dict[str, Any]]:
        priority = {
            "review_required": 0,
            "clarification_required": 1,
            "invalid_execution_attempt": 2,
            "retryable_failure": 3,
            "stale_active_task": 4,
        }
        queue: list[dict[str, Any]] = []
        for read_model in self.read_model_service.list_task_read_models():
            task = asdict(read_model)
            last_activity_at = self._last_activity_at(task)
            attention = self._classify_attention(task, last_activity_at=last_activity_at)
            if attention is None:
                continue
            attention_type, suggested_action, reason, stale = attention
            queue.append(
                asdict(
                    SupervisionQueueEntry(
                        task_id=str(task["task_id"]),
                        title=str(task["title"]),
                        current_status=str(task["current_status"]),
                        attention_type=attention_type,
                        suggested_action=suggested_action,
                        reason=reason,
                        last_activity_at=last_activity_at,
                        stale=stale,
                        review_status=str(((task.get("review_summary") or {}).get("status")) or "none"),
                        clarification_status=str(((task.get("clarification_summary") or {}).get("status")) or "none"),
                        failure_state=str(((task.get("failure_summary") or {}).get("state")) or "clear"),
                        retry_eligible=bool(((task.get("execution_summary") or {}).get("retry_eligible"))),
                    )
                )
            )

        return sorted(
            queue,
            key=lambda item: (
                priority.get(str(item.get("attention_type")), 99),
                _parse_iso_timestamp(str(item.get("last_activity_at") or "")),
                str(item.get("task_id") or ""),
            ),
        )


__all__ = [
    "HarnessSupervisionService",
    "SupervisionQueueEntry",
]
