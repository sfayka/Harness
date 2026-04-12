"""Thin OpenClaw-side supervision loop over canonical Harness APIs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .openclaw_harness_spike import OpenClawHarnessSpikeClient


@dataclass(frozen=True)
class OpenClawSupervisionDecision:
    """One canonical attention item enriched with inspection context."""

    task_id: str
    title: str
    current_status: str
    attention_type: str
    suggested_action: str
    reason: str
    stale: bool
    last_activity_at: str | None
    read_model_status: int
    timeline_status: int
    evaluation_history_count: int
    timeline_event_count: int
    can_autonomously_dispatch: bool
    proposed_dispatch_payload: dict[str, Any] | None
    read_model: dict[str, Any]
    timeline: dict[str, Any]
    evaluations: dict[str, Any]


@dataclass(frozen=True)
class OpenClawSupervisionActionResult:
    """Outcome of one supervisor decision during a cycle."""

    task_id: str
    attention_type: str
    action_status: str
    http_status: int | None
    action: str | None
    resulting_task_status: str | None


@dataclass(frozen=True)
class OpenClawSupervisionCycleResult:
    """Structured result of one supervision polling cycle."""

    queue_status: int
    generated_at: str | None
    decision_count: int
    decisions: tuple[OpenClawSupervisionDecision, ...]
    action_results: tuple[OpenClawSupervisionActionResult, ...]


class OpenClawHarnessSupervisor:
    """OpenClaw-side supervisor that polls canonical Harness attention state."""

    def __init__(self, base_url: str) -> None:
        self.client = OpenClawHarnessSpikeClient(base_url)

    def _can_autonomously_dispatch(self, entry: dict[str, Any]) -> bool:
        return (
            str(entry.get("attention_type") or "") == "retryable_failure"
            and str(entry.get("suggested_action") or "") == "retry_or_redispatch"
            and str(entry.get("current_status") or "") in {"dispatch_ready", "assigned", "blocked"}
            and str(entry.get("clarification_status") or "") != "required"
            and str(entry.get("review_status") or "") != "requested"
        )

    @staticmethod
    def _dispatch_payload(*, attention_type: str, executor: str) -> dict[str, Any]:
        return {
            "request": {
                "executor": executor,
                "dispatch_mode": "manual",
                "dispatch_trigger": "openclaw_supervision_loop",
                "dispatch_reason": f"OpenClaw supervision loop redispatch for {attention_type}.",
                "execution_parameters": {
                    "initiator": "openclaw_supervision_loop",
                    "attention_type": attention_type,
                },
            }
        }

    def _build_decision(self, entry: dict[str, Any], *, executor: str) -> OpenClawSupervisionDecision:
        task_id = str(entry.get("task_id") or "")
        read_model_status, read_model_payload = self.client.get_task_read_model(task_id)
        timeline_status, timeline_payload = self.client.get_task_timeline(task_id)
        evaluations_status, evaluations_payload = self.client.get_evaluation_history(task_id)
        if read_model_status >= 400 or timeline_status >= 400 or evaluations_status >= 400:
            raise RuntimeError(f"OpenClaw supervision inspection failed for {task_id}")

        can_dispatch = self._can_autonomously_dispatch(entry)
        return OpenClawSupervisionDecision(
            task_id=task_id,
            title=str(entry.get("title") or ""),
            current_status=str(entry.get("current_status") or ""),
            attention_type=str(entry.get("attention_type") or ""),
            suggested_action=str(entry.get("suggested_action") or ""),
            reason=str(entry.get("reason") or ""),
            stale=bool(entry.get("stale")),
            last_activity_at=str(entry.get("last_activity_at")) if entry.get("last_activity_at") is not None else None,
            read_model_status=read_model_status,
            timeline_status=timeline_status,
            evaluation_history_count=len(evaluations_payload.get("evaluations", ())),
            timeline_event_count=int(timeline_payload.get("event_count") or 0),
            can_autonomously_dispatch=can_dispatch,
            proposed_dispatch_payload=(
                self._dispatch_payload(attention_type=str(entry.get("attention_type") or ""), executor=executor)
                if can_dispatch
                else None
            ),
            read_model=read_model_payload,
            timeline=timeline_payload,
            evaluations=evaluations_payload,
        )

    @staticmethod
    def _non_dispatch_action_status(attention_type: str) -> str:
        return {
            "review_required": "manual_review_required",
            "clarification_required": "clarification_required",
            "invalid_execution_attempt": "fresh_proof_or_rework_required",
            "retryable_failure": "retryable_failure_observed",
            "stale_active_task": "staleness_investigation_required",
        }.get(attention_type, "attention_observed")

    def run_cycle(
        self,
        *,
        allow_redispatch: bool = False,
        executor: str = "codex",
    ) -> OpenClawSupervisionCycleResult:
        queue_status, queue_payload = self.client.get_supervision_queue()
        if queue_status >= 400:
            raise RuntimeError(f"OpenClaw supervision queue fetch failed: {queue_payload}")
        queue = queue_payload.get("queue")
        if not isinstance(queue, list):
            raise RuntimeError("OpenClaw supervision queue payload is malformed")

        decisions = tuple(self._build_decision(entry, executor=executor) for entry in queue if isinstance(entry, dict))
        action_results: list[OpenClawSupervisionActionResult] = []
        for decision in decisions:
            if allow_redispatch and decision.can_autonomously_dispatch and decision.proposed_dispatch_payload is not None:
                dispatch_status, dispatch_payload = self.client.dispatch_task(
                    decision.task_id,
                    payload=decision.proposed_dispatch_payload,
                )
                action_results.append(
                    OpenClawSupervisionActionResult(
                        task_id=decision.task_id,
                        attention_type=decision.attention_type,
                        action_status="redispatch_triggered" if dispatch_status < 400 else "redispatch_failed",
                        http_status=dispatch_status,
                        action=(
                            str(dispatch_payload.get("action"))
                            if isinstance(dispatch_payload, dict) and dispatch_payload.get("action") is not None
                            else None
                        ),
                        resulting_task_status=(
                            str((dispatch_payload.get("task_envelope") or {}).get("status"))
                            if isinstance(dispatch_payload, dict)
                            and isinstance(dispatch_payload.get("task_envelope"), dict)
                            and (dispatch_payload.get("task_envelope") or {}).get("status") is not None
                            else None
                        ),
                    )
                )
                continue

            action_results.append(
                OpenClawSupervisionActionResult(
                    task_id=decision.task_id,
                    attention_type=decision.attention_type,
                    action_status=self._non_dispatch_action_status(decision.attention_type),
                    http_status=None,
                    action=None,
                    resulting_task_status=decision.current_status,
                )
            )

        return OpenClawSupervisionCycleResult(
            queue_status=queue_status,
            generated_at=(
                str(queue_payload.get("generated_at"))
                if queue_payload.get("generated_at") is not None
                else None
            ),
            decision_count=len(decisions),
            decisions=decisions,
            action_results=tuple(action_results),
        )


__all__ = [
    "OpenClawHarnessSupervisor",
    "OpenClawSupervisionActionResult",
    "OpenClawSupervisionCycleResult",
    "OpenClawSupervisionDecision",
]
