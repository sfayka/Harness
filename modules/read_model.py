"""Dashboard-friendly task read model and timeline builders."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from modules.store import EvaluationRecord, HarnessStore, TaskEnvelopeNotFoundError, build_harness_store

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


def _record_action(record: EvaluationRecord) -> str:
    result = record.result if isinstance(record.result, dict) else {}
    enforcement_result = result.get("enforcement_result") if isinstance(result.get("enforcement_result"), dict) else {}
    return str(enforcement_result.get("action") or result.get("action") or "")


def _latest_mapping(
    records: tuple[EvaluationRecord, ...],
    path: tuple[str, ...],
    *,
    include_transition_rejected: bool = True,
) -> dict[str, Any] | None:
    for record in reversed(records):
        if not include_transition_rejected and _record_action(record) == "transition_rejected":
            continue
        current: Any = record.result
        for key in path:
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(key)
        if isinstance(current, dict):
            return current
    return None


def _latest_verification_base(records: tuple[EvaluationRecord, ...]) -> dict[str, Any] | None:
    latest_verification = _latest_mapping(
        records,
        ("enforcement_result", "verification_result"),
        include_transition_rejected=False,
    )
    if isinstance(latest_verification, dict):
        outcome = latest_verification.get("outcome")
        if outcome not in (None, "verification_deferred") or latest_verification.get("claimed_completion"):
            return latest_verification
    for record in reversed(records):
        if _record_action(record) == "transition_rejected":
            continue
        result = record.result if isinstance(record.result, dict) else {}
        enforcement_result = result.get("enforcement_result") if isinstance(result.get("enforcement_result"), dict) else {}
        verification_result = enforcement_result.get("verification_result")
        if not isinstance(verification_result, dict):
            continue
        outcome = verification_result.get("outcome")
        if outcome not in (None, "verification_deferred") or verification_result.get("claimed_completion"):
            return verification_result
    return latest_verification


def _latest_failure_classification(
    records: tuple[EvaluationRecord, ...],
    *,
    include_transition_rejected: bool = False,
) -> dict[str, Any] | None:
    for record in reversed(records):
        if not include_transition_rejected and _record_action(record) == "transition_rejected":
            continue
        result = record.result if isinstance(record.result, dict) else {}
        failure = result.get("failure_classification")
        if isinstance(failure, dict):
            return failure
    return None


def _latest_verification_summary(
    records: tuple[EvaluationRecord, ...],
    *,
    task_envelope: TaskEnvelope,
    review_summary: dict[str, Any],
    reconciliation_summary: dict[str, Any] | None,
    current_status: str,
) -> dict[str, Any] | None:
    verification_summary = _latest_verification_base(records)
    latest_decision = (
        review_summary.get("latest_effective_decision") if isinstance(review_summary, dict) else None
    )
    if review_summary.get("status") == "resolved" and isinstance(latest_decision, dict):
        resolved_summary = dict(verification_summary or {})
        completion_evidence = dict(((task_envelope.get("artifacts") or {}).get("completion_evidence") or {}))
        acceptance_assessment = dict(resolved_summary.get("acceptance_criteria_assessment") or {})
        reasons = list(resolved_summary.get("reasons") or [])
        resolution_reason = str(latest_decision.get("reasoning") or "Manual review resolved the pending gate.")
        accepted_completion = bool(
            latest_decision.get("outcome") == "accept_completion" and current_status == "completed"
        )
        if resolution_reason not in reasons:
            reasons.append(resolution_reason)
        if not accepted_completion:
            acceptance_assessment["automatic_completion_safe"] = False
        latest_failure = dict(_latest_failure_classification(records) or {})
        is_manual_failure = bool(
            current_status == "failed"
            and latest_decision.get("outcome") == "mark_failed"
            and latest_decision.get("authorized_target_status") == "failed"
        )
        if latest_failure and (
            latest_failure.get("failure_type") not in (None, "none")
            or latest_failure.get("category") not in (None, "none")
        ):
            failure_classification = latest_failure
            is_terminal = bool(latest_failure.get("terminal"))
        else:
            failure_classification = {
                "category": "manual_review_failed" if is_manual_failure else "none",
                "failure_type": "manual_review_failed" if is_manual_failure else "none",
                "reason": resolution_reason,
                "recoverable": False,
                "retryable": False,
                "source": "manual_review" if is_manual_failure else "none",
                "terminal": is_manual_failure,
            }
            is_terminal = is_manual_failure
        resolved_summary.update(
            {
                "accepted_completion": accepted_completion,
                "acceptance_criteria_assessment": acceptance_assessment,
                "claimed_completion": accepted_completion,
                "evidence_is_sufficient": accepted_completion
                or str(completion_evidence.get("status") or "") == "satisfied",
                "failure_classification": failure_classification,
                "is_terminal": is_terminal,
                "outcome": "review_resolved",
                "reasons": reasons,
                "requires_review": False,
                "resolved_by": "manual_review",
                "target_status": current_status,
                "task_id": resolved_summary.get("task_id"),
                "verification_passed": False,
            }
        )
        if isinstance(reconciliation_summary, dict):
            resolved_summary["reconciliation_status"] = reconciliation_summary.get("status")
        return resolved_summary
    return verification_summary


def _latest_reconciliation_summary(
    records: tuple[EvaluationRecord, ...],
    *,
    review_summary: dict[str, Any],
) -> dict[str, Any] | None:
    reconciliation_summary = _latest_mapping(
        records,
        ("enforcement_result", "reconciliation_result"),
        include_transition_rejected=False,
    )
    if not isinstance(reconciliation_summary, dict):
        return None
    latest_request = review_summary.get("latest_request") if isinstance(review_summary, dict) else None
    if (
        reconciliation_summary.get("status") == "review_required"
        and review_summary.get("status") == "resolved"
        and isinstance(latest_request, dict)
        and latest_request.get("trigger") == "reconciliation"
    ):
        resolved_summary = dict(reconciliation_summary)
        resolved_summary["status"] = "resolved"
        resolved_summary["outcome"] = "review_resolved"
        resolved_summary["blocking"] = False
        resolved_summary["terminal"] = False
        resolved_summary["resolved_by"] = "manual_review"
        return resolved_summary
    return reconciliation_summary


def _failure_state(
    *,
    failure_type: str | None,
    terminal: bool,
    recoverable: bool,
) -> str:
    if failure_type in (None, "none"):
        return "clear"
    if failure_type == "review_required":
        return "review_required"
    if terminal:
        return "terminal"
    if recoverable:
        return "retryable"
    return "failed"


def _latest_failure_summary(
    records: tuple[EvaluationRecord, ...],
    *,
    review_summary: dict[str, Any] | None = None,
    current_status: str = "",
) -> dict[str, Any] | None:
    latest_decision = (
        review_summary.get("latest_effective_decision") if isinstance(review_summary, dict) else None
    )
    if (
        current_status == "failed"
        and isinstance(latest_decision, dict)
        and latest_decision.get("outcome") == "mark_failed"
        and latest_decision.get("authorized_target_status") == "failed"
    ):
        last_record = records[-1] if records else None
        failure_reason = str(
            latest_decision.get("reasoning")
            or "Manual review authorized the next control-plane action."
        )
        return {
            "state": "terminal",
            "failure_type": "manual_review_failed",
            "failure_source": "manual_review",
            "failure_reason": failure_reason,
            "terminal": True,
            "recoverable": False,
            "recorded_at": (
                last_record.recorded_at
                if isinstance(last_record, EvaluationRecord)
                else latest_decision.get("reviewed_at")
            ),
            "evaluation_id": (
                last_record.evaluation_id
                if isinstance(last_record, EvaluationRecord)
                else None
            ),
        }
    for record in reversed(records):
        if _record_action(record) == "transition_rejected":
            continue
        payload = record.result if isinstance(record.result, dict) else {}
        failure = payload.get("failure_classification")
        if not isinstance(failure, dict):
            continue
        failure_type = failure.get("failure_type") or failure.get("category")
        terminal = bool(failure.get("terminal"))
        recoverable = bool(failure.get("recoverable") or failure.get("retryable"))
        if failure_type in (None, "none"):
            return {
                "state": "clear",
                "failure_type": "none",
                "failure_source": failure.get("source") or "none",
                "failure_reason": failure.get("reason"),
                "terminal": False,
                "recoverable": False,
                "recorded_at": record.recorded_at,
                "evaluation_id": record.evaluation_id,
            }
        return {
            "state": _failure_state(
                failure_type=str(failure_type),
                terminal=terminal,
                recoverable=recoverable,
            ),
            "failure_type": failure_type,
            "failure_source": failure.get("source") or "evaluation",
            "failure_reason": failure.get("reason"),
            "terminal": terminal,
            "recoverable": recoverable,
            "recorded_at": record.recorded_at,
            "evaluation_id": record.evaluation_id,
        }
    return {"state": "clear", "failure_type": "none", "failure_source": "none", "terminal": False, "recoverable": False}


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


def _effective_review_decision_records(records: tuple[EvaluationRecord, ...]) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    for record in records:
        result_payload = record.result if isinstance(record.result, dict) else {}
        enforcement_result = dict(result_payload.get("enforcement_result") or {})
        action = str(enforcement_result.get("action") or result_payload.get("action") or "")
        if action not in {"transition_applied", "follow_up_authorized"}:
            continue
        review_decision = enforcement_result.get("review_decision")
        if isinstance(review_decision, dict) and isinstance(review_decision.get("record"), dict):
            decisions.append(review_decision["record"])
    return decisions


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


def _build_clarification_summary(task_envelope: TaskEnvelope) -> dict[str, Any] | None:
    clarification = task_envelope.get("clarification")
    if not isinstance(clarification, dict):
        return None

    required_inputs = [
        item
        for item in clarification.get("required_inputs") or []
        if isinstance(item, dict)
    ]
    questions = [item for item in clarification.get("questions") or [] if isinstance(item, dict)]
    responses = [item for item in clarification.get("responses") or [] if isinstance(item, dict)]
    open_required_inputs = [
        item for item in required_inputs if item.get("required") and item.get("status") == "open"
    ]
    open_questions = [item for item in questions if item.get("status") == "open"]

    return {
        "status": clarification.get("status"),
        "blocking_reason": clarification.get("blocking_reason"),
        "resume_target_status": clarification.get("resume_target_status"),
        "requested_at": clarification.get("requested_at"),
        "resolved_at": clarification.get("resolved_at"),
        "requested_by": clarification.get("requested_by"),
        "resolution_summary": clarification.get("resolution_summary"),
        "required_input_count": len(required_inputs),
        "open_required_input_count": len(open_required_inputs),
        "question_count": len(questions),
        "open_question_count": len(open_questions),
        "response_count": len(responses),
    }


def _build_review_summary(records: tuple[EvaluationRecord, ...]) -> dict[str, Any]:
    requests: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    effective_decisions = _effective_review_decision_records(records)

    for record in records:
        result_payload = record.result if isinstance(record.result, dict) else {}
        result_enforcement = dict(result_payload.get("enforcement_result") or {})

        review_request = result_enforcement.get("review_request")
        if isinstance(review_request, dict):
            requests.append(review_request)

        review_decision = result_enforcement.get("review_decision")
        if isinstance(review_decision, dict):
            record_payload = review_decision.get("record")
            if isinstance(record_payload, dict):
                decisions.append(record_payload)

    return {
        "status": _review_status(requests=requests, decisions=effective_decisions),
        "request_count": len(requests),
        "decision_count": len(decisions),
        "resolved_decision_count": len(effective_decisions),
        "latest_request": requests[-1] if requests else None,
        "latest_decision": decisions[-1] if decisions else None,
        "latest_effective_decision": effective_decisions[-1] if effective_decisions else None,
        "requests": requests,
        "decisions": decisions,
    }


def _build_execution_summary(task_envelope: TaskEnvelope, records: tuple[EvaluationRecord, ...]) -> dict[str, Any]:
    execution_attempts = ((task_envelope.get("observability") or {}).get("execution_metadata") or {}).get("execution_attempts") or []
    review_summary = _build_review_summary(records)
    latest_failure_summary = _latest_failure_summary(
        records,
        review_summary=review_summary,
        current_status=str(task_envelope.get("status") or ""),
    )
    retry_count = 0
    invalid_attempt_count = 0
    for record in records:
        if not isinstance(record.request, dict):
            continue
        if isinstance(record.request.get("retry_context"), dict):
            retry_count += 1
    if not isinstance(execution_attempts, list):
        failure_type = (latest_failure_summary or {}).get("failure_type")
        failure_state = _failure_state(
            failure_type=str(failure_type) if failure_type is not None else None,
            terminal=bool((latest_failure_summary or {}).get("terminal")),
            recoverable=bool((latest_failure_summary or {}).get("recoverable")),
        )
        return {
            "attempt_count": 0,
            "latest_attempt": None,
            "latest_artifact_references": [],
            "total_attempts": len(records),
            "retry_count": retry_count,
            "last_failure_type": failure_type,
            "retry_eligible": bool((latest_failure_summary or {}).get("recoverable")),
            "failure_state": failure_state,
        }
    latest_attempt = next(
        (attempt for attempt in reversed(execution_attempts) if isinstance(attempt, dict)),
        None,
    )
    attempt_count = len([attempt for attempt in execution_attempts if isinstance(attempt, dict)])
    for attempt in execution_attempts:
        if not isinstance(attempt, dict):
            continue
        metadata = attempt.get("metadata") if isinstance(attempt.get("metadata"), dict) else {}
        validation = metadata.get("attempt_validation") if isinstance(metadata.get("attempt_validation"), dict) else {}
        if validation.get("failure_type") == "invalid_execution_attempt":
            invalid_attempt_count += 1
    retry_eligible = bool((latest_failure_summary or {}).get("recoverable"))
    failure_state = _failure_state(
        failure_type=(
            str(latest_failure_summary.get("failure_type"))
            if latest_failure_summary and latest_failure_summary.get("failure_type") is not None
            else None
        ),
        terminal=bool((latest_failure_summary or {}).get("terminal")),
        recoverable=bool((latest_failure_summary or {}).get("recoverable")),
    )
    return {
        "attempt_count": attempt_count,
        "latest_attempt": dict(latest_attempt) if latest_attempt is not None else None,
        "latest_status": latest_attempt.get("status") if isinstance(latest_attempt, dict) else None,
        "latest_dispatch_origin": (
            ((latest_attempt.get("metadata") or {}).get("dispatch_mode"))
            if isinstance(latest_attempt, dict)
            else None
        ),
        "latest_attempt_validation": (
            dict((((latest_attempt.get("metadata") or {}).get("attempt_validation")) or {}))
            if isinstance(latest_attempt, dict)
            else None
        ),
        "latest_artifact_references": list((latest_attempt or {}).get("artifact_references") or []),
        "total_attempts": max(len(records), attempt_count),
        "retry_count": retry_count,
        "invalid_attempt_count": invalid_attempt_count,
        "last_failure_type": (latest_failure_summary or {}).get("failure_type"),
        "retry_eligible": retry_eligible,
        "failure_state": failure_state,
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
                    "pull_request_number": artifact.get("pull_request_number"),
                    "commit_sha": artifact.get("commit_sha"),
                    "repository": artifact.get("repository"),
                    "branch": artifact.get("branch"),
                },
            }
        )
    clarification = task_envelope.get("clarification")
    if isinstance(clarification, dict):
        events.append(
            {
                "event_id": f"{task_envelope['id']}:clarification",
                "event_type": "clarification_updated",
                "occurred_at": clarification.get("requested_at")
                or clarification.get("resolved_at")
                or timestamps.get("updated_at"),
                "summary": f"Clarification status: {clarification.get('status')}",
                "source": clarification.get("requested_by") or "harness",
                "details": {
                    "status": clarification.get("status"),
                    "blocking_reason": clarification.get("blocking_reason"),
                    "resume_target_status": clarification.get("resume_target_status"),
                    "required_inputs": list(clarification.get("required_inputs") or []),
                },
            }
        )

    clarification = task_envelope.get("clarification")
    if isinstance(clarification, dict):
        clarification_status = str(clarification.get("status") or "")
        clarification_event_type = "clarification_resolved" if clarification_status == "resolved" else "clarification_required"
        clarification_summary = "Clarification resolved" if clarification_status == "resolved" else "Clarification required"
        events.append(
            {
                "event_id": f"{task_envelope['id']}:clarification",
                "event_type": clarification_event_type,
                "occurred_at": clarification.get("resolved_at")
                or clarification.get("requested_at")
                or timestamps.get("updated_at"),
                "summary": clarification_summary,
                "source": clarification.get("requested_by") or "clarification",
                "details": {
                    "status": clarification.get("status"),
                    "blocking_reason": clarification.get("blocking_reason"),
                    "resume_target_status": clarification.get("resume_target_status"),
                    "required_inputs": list(clarification.get("required_inputs") or []),
                    "questions": list(clarification.get("questions") or []),
                    "responses": list(clarification.get("responses") or []),
                },
            }
        )

    execution_attempts = ((task_envelope.get("observability") or {}).get("execution_metadata") or {}).get("execution_attempts") or []
    for index, attempt in enumerate(execution_attempts):
        if not isinstance(attempt, dict):
            continue
        reevaluation = attempt.get("reevaluation") if isinstance(attempt.get("reevaluation"), dict) else {}
        metadata = attempt.get("metadata") if isinstance(attempt.get("metadata"), dict) else {}
        execution_events = metadata.get("execution_events") if isinstance(metadata.get("execution_events"), list) else []
        dispatch_id = metadata.get("dispatch_id")
        dispatch_at = metadata.get("dispatch_at")
        if dispatch_id:
            events.append(
                {
                    "event_id": f"{task_envelope['id']}:dispatch:{dispatch_id}",
                    "event_type": "task_dispatched",
                    "occurred_at": dispatch_at or attempt.get("recorded_at") or timestamps.get("updated_at"),
                    "summary": f"Task dispatched: {attempt.get('attempt_id')}",
                    "source": metadata.get("executor") or "dispatcher",
                    "details": {
                        "dispatch_id": dispatch_id,
                        "attempt_id": attempt.get("attempt_id"),
                        "executor": metadata.get("executor"),
                        "dispatch_trigger": metadata.get("dispatch_trigger"),
                        "dispatch_mode": metadata.get("dispatch_mode"),
                        "dispatch_reason": metadata.get("dispatch_reason"),
                        "execution_parameters": dict(metadata.get("execution_parameters") or {}),
                    },
                }
            )
        events.append(
            {
                "event_id": f"{task_envelope['id']}:execution_attempt:{attempt.get('attempt_id') or index}",
                "event_type": "execution_attempt_recorded",
                "occurred_at": attempt.get("recorded_at") or timestamps.get("updated_at"),
                "summary": f"Execution attempt recorded: {attempt.get('attempt_id')}",
                "source": attempt.get("reported_by") or "executor",
                "details": {
                    "attempt_id": attempt.get("attempt_id"),
                    "status": attempt.get("status"),
                    "completion_claim_id": attempt.get("completion_claim_id"),
                    "artifact_references": list(attempt.get("artifact_references") or []),
                    "attempt_validation": dict((metadata.get("attempt_validation") or {})),
                    "reevaluation": dict(reevaluation or {}),
                },
            }
        )
        for event_index, execution_event in enumerate(execution_events):
            if not isinstance(execution_event, dict):
                continue
            events.append(
                {
                    "event_id": f"{task_envelope['id']}:execution_event:{attempt.get('attempt_id') or index}:{event_index}",
                    "event_type": "execution_event_recorded",
                    "occurred_at": execution_event.get("occurred_at") or attempt.get("recorded_at") or timestamps.get("updated_at"),
                    "summary": f"Execution event: {execution_event.get('event_type')}",
                    "source": ((execution_event.get("provenance") or {}).get("source_system")) or attempt.get("reported_by") or "executor",
                    "details": dict(execution_event),
                }
            )
        for artifact_reference in attempt.get("artifact_references") or []:
            if not isinstance(artifact_reference, dict):
                continue
            events.append(
                {
                    "event_id": f"{task_envelope['id']}:execution_artifact:{attempt.get('attempt_id') or index}:{artifact_reference.get('reference_id')}",
                    "event_type": "execution_artifact_attached",
                    "occurred_at": attempt.get("recorded_at") or timestamps.get("updated_at"),
                    "summary": f"Execution artifact attached: {artifact_reference.get('artifact_type')}",
                    "source": ((artifact_reference.get("provenance") or {}).get("source_system")) or attempt.get("reported_by") or "executor",
                    "details": dict(artifact_reference),
                }
            )

    linear_coordination = ((task_envelope.get("coordination") or {}).get("linear")) or None
    if isinstance(linear_coordination, dict):
        provenance = linear_coordination.get("provenance") if isinstance(linear_coordination.get("provenance"), dict) else {}
        events.append(
            {
                "event_id": f"{task_envelope['id']}:linear_linkage",
                "event_type": "linear_linkage_recorded",
                "occurred_at": provenance.get("linked_at") or timestamps.get("updated_at"),
                "summary": "Linear linkage recorded",
                "source": provenance.get("linked_by") or "harness",
                "details": dict(linear_coordination),
            }
        )

    reconciliation = task_envelope.get("reconciliation")
    if isinstance(reconciliation, dict):
        attempts = reconciliation.get("attempts") if isinstance(reconciliation.get("attempts"), list) else []
        for attempt in attempts:
            if not isinstance(attempt, dict):
                continue
            events.append(
                {
                    "event_id": f"{task_envelope['id']}:reconciliation:{attempt.get('attempt_id')}",
                    "event_type": "reconciliation_attempt_recorded",
                    "occurred_at": attempt.get("completed_at") or attempt.get("started_at") or timestamps.get("updated_at"),
                    "summary": f"Reconciliation attempt: {attempt.get('failure_type')}",
                    "source": "reconciliation",
                    "details": dict(attempt),
                }
            )

    for record in records:
        result_payload = record.result if isinstance(record.result, dict) else {}
        request_payload = record.request if isinstance(record.request, dict) else {}
        enforcement_result = dict(result_payload.get("enforcement_result") or {})
        verification_result = enforcement_result.get("verification_result")
        reconciliation_result = enforcement_result.get("reconciliation_result")
        retry_context = request_payload.get("retry_context")
        if isinstance(retry_context, dict):
            retry_attempt_number = retry_context.get("attempt_number")
            retry_scheduled_at = retry_context.get("scheduled_at") or record.recorded_at
            events.append(
                {
                    "event_id": f"{task_envelope['id']}:retry-scheduled:{record.evaluation_id}",
                    "event_type": "retry_scheduled",
                    "occurred_at": retry_scheduled_at,
                    "summary": f"Retry scheduled: attempt {retry_attempt_number}",
                    "source": "harness",
                    "details": dict(retry_context),
                }
            )
            events.append(
                {
                    "event_id": f"{task_envelope['id']}:retry-started:{record.evaluation_id}",
                    "event_type": "retry_attempt_started",
                    "occurred_at": retry_scheduled_at,
                    "summary": f"Retry attempt started: attempt {retry_attempt_number}",
                    "source": "harness",
                    "details": dict(retry_context),
                }
            )

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
        if isinstance(retry_context, dict):
            retry_attempt_number = retry_context.get("attempt_number")
            events.append(
                {
                    "event_id": f"{task_envelope['id']}:retry-completed:{record.evaluation_id}",
                    "event_type": "retry_attempt_completed",
                    "occurred_at": record.recorded_at,
                    "summary": f"Retry attempt completed: attempt {retry_attempt_number}",
                    "source": "harness",
                    "details": {
                        **dict(retry_context),
                        "failure_classification": result_payload.get("failure_classification"),
                        "action": result_payload.get("action"),
                    },
                }
            )
        failure = result_payload.get("failure_classification")
        if isinstance(failure, dict):
            failure_type = failure.get("failure_type") or failure.get("category")
            if failure_type not in (None, "none"):
                events.append(
                    {
                        "event_id": f"{task_envelope['id']}:failure:{record.evaluation_id}",
                        "event_type": "failure_recorded",
                        "occurred_at": record.recorded_at,
                        "summary": f"Failure recorded: {failure_type}",
                        "source": failure.get("source") or "evaluation",
                        "details": {
                            "failure_recorded": True,
                            "failure_type": failure_type,
                            "failure_source": failure.get("source") or "evaluation",
                            "failure_reason": failure.get("reason"),
                            "terminal": bool(failure.get("terminal")),
                            "recoverable": bool(failure.get("recoverable") or failure.get("retryable")),
                        },
                    }
                )

        review_request = enforcement_result.get("review_request")
        if isinstance(review_request, dict):
            events.append(
                {
                    "event_id": f"{task_envelope['id']}:review-request:{review_request.get('review_request_id')}",
                    "event_type": "review_requested",
                    "occurred_at": review_request.get("requested_at") or record.recorded_at,
                    "summary": "Manual review requested",
                    "source": review_request.get("requested_by") or "harness",
                    "details": {
                        **review_request,
                        "reason": review_request.get("summary"),
                    },
                }
            )

        review_decision = enforcement_result.get("review_decision")
        if isinstance(review_decision, dict) and isinstance(review_decision.get("record"), dict):
            review_record = review_decision["record"]
            decision_rejected = str(enforcement_result.get("action") or "") == "transition_rejected"
            events.append(
                {
                    "event_id": f"{task_envelope['id']}:review-decision:{review_record.get('review_id')}",
                    "event_type": "review_decision_rejected" if decision_rejected else "review_decided",
                    "occurred_at": review_record.get("reviewed_at") or record.recorded_at,
                    "summary": (
                        f"Manual review decision rejected: {review_record.get('outcome')}"
                        if decision_rejected
                        else f"Manual review decided: {review_record.get('outcome')}"
                    ),
                    "source": str((review_record.get("reviewer") or {}).get("reviewer_name") or "operator"),
                    "details": {
                        **review_record,
                        "rejection_reason": enforcement_result.get("error") if decision_rejected else None,
                    },
                }
            )

    order = {
        "task_created": 0,
        "artifact_captured": 1,
        "clarification_updated": 2,
        "clarification_required": 3,
        "clarification_resolved": 3,
        "review_requested": 4,
        "review_decided": 5,
        "review_decision_rejected": 5,
        "task_dispatched": 6,
        "execution_event_recorded": 7,
        "execution_attempt_recorded": 8,
        "evaluation_recorded": 9,
        "failure_recorded": 10,
        "status_transition": 11,
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
    clarification_summary: dict[str, Any] | None
    evidence_summary: dict[str, Any]
    coordination_summary: dict[str, Any]
    verification_summary: dict[str, Any] | None
    reconciliation_summary: dict[str, Any] | None
    review_summary: dict[str, Any]
    execution_summary: dict[str, Any]
    failure_summary: dict[str, Any] | None
    evaluation_summary: dict[str, Any]
    lifecycle_history: list[dict[str, Any]]
    timestamps: dict[str, Any]
    extensions: dict[str, Any]
    timeline: list[dict[str, Any]]


class HarnessReadModelService:
    """Build dashboard-friendly task inspection surfaces from persisted records."""

    def __init__(self, *, store: HarnessStore | None = None) -> None:
        self.store = store or build_harness_store()

    def _load_task_and_records(self, task_id: str) -> tuple[TaskEnvelope, tuple[EvaluationRecord, ...]]:
        task = self.store.get_task(task_id)
        records = tuple(
            sorted(
                self.store.list_evaluation_records(task_id),
                key=lambda record: (_parse_iso_timestamp(record.recorded_at), record.evaluation_id),
            )
        )
        return task, records

    def _build_task_read_model_from_loaded(
        self,
        *,
        task: TaskEnvelope,
        records: tuple[EvaluationRecord, ...],
    ) -> TaskReadModel:
        records = tuple(
            sorted(
                records,
                key=lambda record: (_parse_iso_timestamp(record.recorded_at), record.evaluation_id),
            )
        )
        clarification_summary = _build_clarification_summary(task)
        review_summary = _build_review_summary(records)
        reconciliation_summary = _latest_reconciliation_summary(records, review_summary=review_summary)
        verification_summary = _latest_verification_summary(
            records,
            task_envelope=task,
            review_summary=review_summary,
            reconciliation_summary=reconciliation_summary,
            current_status=str(task.get("status") or ""),
        )
        execution_summary = _build_execution_summary(task, records)
        failure_summary = _latest_failure_summary(
            records,
            review_summary=review_summary,
            current_status=str(task.get("status") or ""),
        )
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
            clarification_summary=clarification_summary,
            evidence_summary=_build_evidence_summary(task),
            coordination_summary={
                "linear": dict(((task.get("coordination") or {}).get("linear") or {}))
                if ((task.get("coordination") or {}).get("linear")) is not None
                else None
            },
            verification_summary=verification_summary,
            reconciliation_summary=reconciliation_summary,
            review_summary=review_summary,
            execution_summary=execution_summary,
            failure_summary=failure_summary,
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

    def build_task_read_model(self, task_id: str) -> TaskReadModel:
        task, records = self._load_task_and_records(task_id)
        return self._build_task_read_model_from_loaded(task=task, records=records)

    def build_task_timeline(self, task_id: str) -> dict[str, Any]:
        task, records = self._load_task_and_records(task_id)
        timeline = _build_timeline(task, records)
        return {
            "task_id": task_id,
            "current_status": task.get("status"),
            "event_count": len(timeline),
            "timeline": timeline,
        }

    def list_task_read_models(self) -> tuple[TaskReadModel, ...]:
        tasks = self.store.list_tasks()
        task_ids = tuple(str(task["id"]) for task in tasks)
        records_by_task_id = self.store.list_evaluation_records_for_tasks(task_ids)
        return tuple(
            self._build_task_read_model_from_loaded(
                task=task,
                records=records_by_task_id.get(str(task["id"]), ()),
            )
            for task in tasks
        )


__all__ = [
    "HarnessReadModelService",
    "TaskReadModel",
]
