"""Dashboard-friendly task read model and timeline builders."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from modules.store import EvaluationRecord, FileBackedHarnessStore, TaskEnvelopeNotFoundError

TaskEnvelope = dict[str, Any]


def _parse_iso_timestamp(value: str | None) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _count_by(items: list[dict[str, Any]], field_name: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        key = str(item.get(field_name) or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return counts


def _latest_mapping(records: tuple[EvaluationRecord, ...], path: tuple[str, ...]) -> dict[str, Any] | None:
    for record in reversed(records):
        current: Any = record.result
        for key in path:
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(key)
        if isinstance(current, dict):
            return current
    return None


def _review_status(
    *,
    requests: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
) -> str:
    if not requests and not decisions:
        return "none"
    if not decisions:
        return "requested"
    latest_request_at = max((_parse_iso_timestamp(item.get("requested_at")) for item in requests), default=None)
    latest_decision_at = max((_parse_iso_timestamp(item.get("reviewed_at")) for item in decisions), default=None)
    if latest_request_at is not None and (latest_decision_at is None or latest_request_at > latest_decision_at):
        return "requested"
    return "resolved"


def _build_evidence_summary(task_envelope: TaskEnvelope) -> dict[str, Any]:
    artifacts = dict(task_envelope.get("artifacts") or {})
    items = list(artifacts.get("items") or [])
    completion_evidence = dict(artifacts.get("completion_evidence") or {})
    return {
        "artifact_count": len(items),
        "artifact_type_counts": _count_by(items, "type"),
        "verification_status_counts": _count_by(items, "verification_status"),
        "validated_artifact_count": len(tuple(completion_evidence.get("validated_artifact_ids") or ())),
        "completion_evidence": {
            "policy": completion_evidence.get("policy"),
            "status": completion_evidence.get("status"),
            "required_artifact_types": list(completion_evidence.get("required_artifact_types") or []),
            "validated_artifact_ids": list(completion_evidence.get("validated_artifact_ids") or []),
            "validation_method": completion_evidence.get("validation_method"),
            "validated_at": completion_evidence.get("validated_at"),
            "validator": completion_evidence.get("validator"),
        },
    }


def _build_review_summary(records: tuple[EvaluationRecord, ...]) -> dict[str, Any]:
    requests: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []

    for record in records:
        result_payload = record.result if isinstance(record.result, dict) else {}
        request_payload = record.request if isinstance(record.request, dict) else {}
        result_enforcement = dict(result_payload.get("enforcement_result") or {})

        review_request = result_enforcement.get("review_request") or request_payload.get("review_request")
        if isinstance(review_request, dict):
            requests.append(review_request)

        review_decision = result_enforcement.get("review_decision") or request_payload.get("review_decision")
        if isinstance(review_decision, dict):
            record_payload = review_decision.get("record")
            if isinstance(record_payload, dict):
                decisions.append(record_payload)

    return {
        "status": _review_status(requests=requests, decisions=decisions),
        "request_count": len(requests),
        "decision_count": len(decisions),
        "latest_request": requests[-1] if requests else None,
        "latest_decision": decisions[-1] if decisions else None,
        "requests": requests,
        "decisions": decisions,
    }


def _build_timeline(task_envelope: TaskEnvelope, records: tuple[EvaluationRecord, ...]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []

    timestamps = dict(task_envelope.get("timestamps") or {})
    created_at = timestamps.get("created_at")
    if created_at:
        events.append(
            {
                "event_id": f"{task_envelope['id']}:created",
                "event_type": "task_created",
                "occurred_at": created_at,
                "summary": "Task created",
                "source": str((task_envelope.get("origin") or {}).get("source_system") or "harness"),
                "details": {
                    "status": task_envelope.get("status"),
                    "title": task_envelope.get("title"),
                    "origin": task_envelope.get("origin"),
                },
            }
        )

    for index, entry in enumerate(task_envelope.get("status_history") or []):
        if not isinstance(entry, dict):
            continue
        events.append(
            {
                "event_id": f"{task_envelope['id']}:status:{index}",
                "event_type": "status_transition",
                "occurred_at": entry.get("changed_at") or timestamps.get("updated_at"),
                "summary": f"Status changed {entry.get('from_status')} -> {entry.get('to_status')}",
                "source": entry.get("changed_by") or "harness",
                "details": dict(entry),
            }
        )

    artifacts = list(((task_envelope.get("artifacts") or {}).get("items") or []))
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        events.append(
            {
                "event_id": f"{task_envelope['id']}:artifact:{artifact.get('id')}",
                "event_type": "artifact_captured",
                "occurred_at": artifact.get("captured_at") or timestamps.get("updated_at"),
                "summary": f"Artifact captured: {artifact.get('type')}",
                "source": str((artifact.get("provenance") or {}).get("source_system") or "unknown"),
                "details": {
                    "artifact_id": artifact.get("id"),
                    "type": artifact.get("type"),
                    "title": artifact.get("title"),
                    "verification_status": artifact.get("verification_status"),
                    "repository": artifact.get("repository"),
                    "branch": artifact.get("branch"),
                },
            }
        )

    for record in records:
        result_payload = record.result if isinstance(record.result, dict) else {}
        enforcement_result = dict(result_payload.get("enforcement_result") or {})
        verification_result = enforcement_result.get("verification_result")
        reconciliation_result = enforcement_result.get("reconciliation_result")

        events.append(
            {
                "event_id": f"{task_envelope['id']}:evaluation:{record.evaluation_id}",
                "event_type": "evaluation_recorded",
                "occurred_at": record.recorded_at,
                "summary": f"Evaluation recorded: {result_payload.get('action')}",
                "source": "harness",
                "details": {
                    "evaluation_id": record.evaluation_id,
                    "action": result_payload.get("action"),
                    "target_status": result_payload.get("target_status"),
                    "accepted_completion": result_payload.get("accepted_completion"),
                    "requires_review": result_payload.get("requires_review"),
                    "reasons": list(result_payload.get("reasons") or []),
                    "verification_result": verification_result,
                    "reconciliation_result": reconciliation_result,
                },
            }
        )

        review_request = enforcement_result.get("review_request") or (
            record.request.get("review_request") if isinstance(record.request, dict) else None
        )
        if isinstance(review_request, dict):
            events.append(
                {
                    "event_id": f"{task_envelope['id']}:review-request:{review_request.get('review_request_id')}",
                    "event_type": "review_requested",
                    "occurred_at": review_request.get("requested_at") or record.recorded_at,
                    "summary": "Manual review requested",
                    "source": review_request.get("requested_by") or "harness",
                    "details": review_request,
                }
            )

        review_decision = enforcement_result.get("review_decision") or (
            record.request.get("review_decision") if isinstance(record.request, dict) else None
        )
        if isinstance(review_decision, dict) and isinstance(review_decision.get("record"), dict):
            review_record = review_decision["record"]
            events.append(
                {
                    "event_id": f"{task_envelope['id']}:review-decision:{review_record.get('review_id')}",
                    "event_type": "review_decided",
                    "occurred_at": review_record.get("reviewed_at") or record.recorded_at,
                    "summary": f"Manual review decided: {review_record.get('outcome')}",
                    "source": str((review_record.get("reviewer") or {}).get("reviewer_name") or "operator"),
                    "details": review_record,
                }
            )

    order = {
        "task_created": 0,
        "artifact_captured": 1,
        "review_requested": 2,
        "review_decided": 3,
        "evaluation_recorded": 4,
        "status_transition": 5,
    }
    return sorted(
        events,
        key=lambda event: (
            _parse_iso_timestamp(event.get("occurred_at")),
            order.get(str(event.get("event_type")), 99),
            str(event.get("event_id")),
        ),
    )


@dataclass(frozen=True)
class TaskReadModel:
    """Presentation-friendly read model for task inspection surfaces."""

    task_id: str
    title: str
    description: str | None
    current_status: str
    objective_summary: str | None
    origin: dict[str, Any]
    relationships: dict[str, Any]
    assigned_executor: dict[str, Any] | None
    evidence_summary: dict[str, Any]
    verification_summary: dict[str, Any] | None
    reconciliation_summary: dict[str, Any] | None
    review_summary: dict[str, Any]
    evaluation_summary: dict[str, Any]
    lifecycle_history: list[dict[str, Any]]
    timestamps: dict[str, Any]
    extensions: dict[str, Any]
    timeline: list[dict[str, Any]]


class HarnessReadModelService:
    """Build dashboard-friendly task inspection surfaces from persisted records."""

    def __init__(self, *, store: FileBackedHarnessStore | None = None) -> None:
        self.store = store or FileBackedHarnessStore(".harness-store")

    def _load_task_and_records(self, task_id: str) -> tuple[TaskEnvelope, tuple[EvaluationRecord, ...]]:
        task = self.store.get_task(task_id)
        records = tuple(
            sorted(
                self.store.list_evaluation_records(task_id),
                key=lambda record: (_parse_iso_timestamp(record.recorded_at), record.evaluation_id),
            )
        )
        return task, records

    def build_task_read_model(self, task_id: str) -> TaskReadModel:
        task, records = self._load_task_and_records(task_id)
        verification_summary = _latest_mapping(records, ("enforcement_result", "verification_result"))
        reconciliation_summary = _latest_mapping(records, ("enforcement_result", "reconciliation_result"))
        review_summary = _build_review_summary(records)
        timeline = _build_timeline(task, records)

        return TaskReadModel(
            task_id=str(task["id"]),
            title=str(task.get("title") or ""),
            description=task.get("description"),
            current_status=str(task.get("status") or ""),
            objective_summary=str(((task.get("objective") or {}).get("summary"))) if (task.get("objective") or {}).get("summary") is not None else None,
            origin=dict(task.get("origin") or {}),
            relationships={
                "parent_task_id": task.get("parent_task_id"),
                "child_task_ids": list(task.get("child_task_ids") or []),
                "dependencies": list(task.get("dependencies") or []),
            },
            assigned_executor=dict(task.get("assigned_executor") or {}) if task.get("assigned_executor") is not None else None,
            evidence_summary=_build_evidence_summary(task),
            verification_summary=verification_summary,
            reconciliation_summary=reconciliation_summary,
            review_summary=review_summary,
            evaluation_summary={
                "count": len(records),
                "latest_recorded_at": records[-1].recorded_at if records else None,
                "latest_action": records[-1].result.get("action") if records and isinstance(records[-1].result, dict) else None,
                "latest_target_status": records[-1].result.get("target_status") if records and isinstance(records[-1].result, dict) else None,
                "history": [
                    {
                        "evaluation_id": record.evaluation_id,
                        "recorded_at": record.recorded_at,
                        "action": record.result.get("action") if isinstance(record.result, dict) else None,
                        "target_status": record.result.get("target_status") if isinstance(record.result, dict) else None,
                    }
                    for record in records
                ],
            },
            lifecycle_history=list(task.get("status_history") or []),
            timestamps=dict(task.get("timestamps") or {}),
            extensions=dict(task.get("extensions") or {}),
            timeline=timeline,
        )

    def build_task_timeline(self, task_id: str) -> dict[str, Any]:
        task, records = self._load_task_and_records(task_id)
        timeline = _build_timeline(task, records)
        return {
            "task_id": task_id,
            "current_status": task.get("status"),
            "event_count": len(timeline),
            "timeline": timeline,
        }


__all__ = [
    "HarnessReadModelService",
    "TaskReadModel",
]
