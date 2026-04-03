"""Minimal HTTP API wrapper around the Harness evaluation entry point."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from dataclasses import asdict, is_dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import unquote, urlparse

from modules.adapters.executor_adapter import (
    ExecutorAdapterInputError,
    ExecutorDispatchInput,
    StubExecutorAdapter,
)
from modules.connectors import (
    GitHubConnectorInputError,
    LinearConnectorInputError,
    LinearIngressInputError,
    ManualIngressInputError,
    OpenClawIngressInputError,
    translate_openclaw_submission_payload,
    translate_github_artifact_facts,
    translate_linear_facts,
    translate_linear_submission_payload,
    translate_manual_submission_payload,
)
from modules.contracts.failure_classification import FailureType
from modules.contracts.task_envelope_end_to_end import CanonicalExternalFactBundle
from modules.contracts.task_envelope_external_facts import ExternalFactValidationError, GitHubArtifactFacts, LinearFacts
from modules.contracts.task_envelope_reconciliation import ExpectedCodeContext
from modules.contracts.task_envelope_review import (
    ReviewDecisionResult,
    ReviewFollowUpAction,
    ReviewOutcome,
    ReviewRecord,
    ReviewRequest,
    ReviewTrigger,
    ReviewerIdentity,
)
from modules.contracts.task_envelope_verification import RuntimeVerificationFacts
from modules.evaluation import HarnessEvaluationRequest, evaluate_task_case
from modules.read_model import HarnessReadModelService
from modules.store import (
    EvaluationRecord,
    HarnessStore,
    PostgresHarnessStore,
    TaskEnvelopeAlreadyExistsError,
    TaskEnvelopeNotFoundError,
    build_harness_store,
)


class ApiRequestError(ValueError):
    """Raised when the HTTP API receives malformed request payloads."""


LINEAR_WORKFLOW_CONTRACT_ERROR = (
    "Invalid external_facts.linear_facts.workflow: must be null/omitted when record_found=false, "
    "or an object with workflow_id and workflow_name when record_found=true"
)
_DEFAULT_CLASSIFIED_RETRY_BUDGET = 2
_CLASSIFIED_RETRY_BUDGET_ENV = "HARNESS_CLASSIFIED_RETRY_BUDGET"
_RETRYABLE_FAILURE_CATEGORIES = frozenset(
    {
        FailureType.BOOTSTRAP_FAILURE,
        FailureType.DISPATCH_FAILURE,
        FailureType.EXECUTOR_FAILURE,
        FailureType.EVIDENCE_INSUFFICIENT,
    }
)
_TERMINAL_TASK_STATUSES = frozenset({"completed", "failed", "canceled"})
_DISPATCH_BLOCKED_STATUSES = frozenset({"in_review"})
_AUTO_DISPATCHABLE_STATUSES = frozenset({"planned", "dispatch_ready", "assigned"})


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso_timestamp(value: str | None) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _classified_retry_budget() -> int:
    raw_budget = os.getenv(_CLASSIFIED_RETRY_BUDGET_ENV)
    if raw_budget is None:
        return _DEFAULT_CLASSIFIED_RETRY_BUDGET
    try:
        parsed_budget = int(raw_budget)
    except ValueError:
        return _DEFAULT_CLASSIFIED_RETRY_BUDGET
    return max(parsed_budget, 0)


def _require_mapping(value: Any, *, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ApiRequestError(f"{field_name} must be an object")
    return value


def _optional_mapping(value: Any, *, field_name: str) -> dict[str, Any] | None:
    if value is None:
        return None
    return _require_mapping(value, field_name=field_name)


def _optional_non_empty_string(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_non_empty_string(value, field_name=field_name)


def _optional_string_tuple(value: Any, *, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ApiRequestError(f"{field_name} must be an array of strings")
    return tuple(value)


def _optional_object_list(value: Any, *, field_name: str) -> tuple[dict[str, Any], ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ApiRequestError(f"{field_name} must be an array of objects")
    result = []
    for index, item in enumerate(value):
        result.append(_require_mapping(item, field_name=f"{field_name}[{index}]"))
    return tuple(result)


def _require_non_empty_string(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ApiRequestError(f"{field_name} is required")
    return value.strip()


def _parse_github_facts(payload: dict[str, Any] | None) -> GitHubArtifactFacts | None:
    if payload is None:
        return None
    github_payload = _require_mapping(payload, field_name="external_facts.github_facts")
    try:
        return translate_github_artifact_facts(github_payload)
    except (GitHubConnectorInputError, ExternalFactValidationError) as error:
        raise ApiRequestError(str(error)) from error


def _parse_linear_facts(payload: dict[str, Any] | None) -> LinearFacts | None:
    if payload is None:
        return None
    linear_payload = _require_mapping(payload, field_name="external_facts.linear_facts")
    try:
        return translate_linear_facts(linear_payload)
    except (LinearConnectorInputError, ExternalFactValidationError) as error:
        if "workflow" in str(error):
            raise ApiRequestError(LINEAR_WORKFLOW_CONTRACT_ERROR) from error
        raise ApiRequestError(str(error)) from error


def _parse_external_facts(payload: dict[str, Any] | None) -> CanonicalExternalFactBundle | None:
    if payload is None:
        return None
    external_payload = _require_mapping(payload, field_name="external_facts")
    expected_code_context_payload = _optional_mapping(
        external_payload.get("expected_code_context"),
        field_name="expected_code_context",
    )
    return CanonicalExternalFactBundle(
        expected_code_context=ExpectedCodeContext(**expected_code_context_payload)
        if expected_code_context_payload is not None
        else None,
        github_facts=_parse_github_facts(_optional_mapping(external_payload.get("github_facts"), field_name="github_facts")),
        linear_facts=_parse_linear_facts(_optional_mapping(external_payload.get("linear_facts"), field_name="linear_facts")),
    )


def _parse_runtime_facts(payload: dict[str, Any] | None) -> RuntimeVerificationFacts:
    if payload is None:
        return RuntimeVerificationFacts()
    return RuntimeVerificationFacts(**_require_mapping(payload, field_name="runtime_facts"))


def _parse_review_request(payload: dict[str, Any] | None) -> ReviewRequest | None:
    if payload is None:
        return None
    request_payload = _require_mapping(payload, field_name="review_request")
    return ReviewRequest(
        review_request_id=request_payload["review_request_id"],
        task_id=request_payload["task_id"],
        requested_at=request_payload["requested_at"],
        requested_by=request_payload["requested_by"],
        trigger=ReviewTrigger(request_payload["trigger"]),
        summary=request_payload["summary"],
        presented_sections=tuple(request_payload.get("presented_sections", [])),
        allowed_outcomes=tuple(ReviewOutcome(item) for item in request_payload.get("allowed_outcomes", [])),
        prior_review_ids=tuple(request_payload.get("prior_review_ids", [])),
        metadata=dict(request_payload.get("metadata", {})),
    )


def _parse_review_decision(payload: dict[str, Any] | None) -> ReviewDecisionResult | None:
    if payload is None:
        return None
    decision_payload = _require_mapping(payload, field_name="review_decision")
    request = _parse_review_request(_optional_mapping(decision_payload.get("request"), field_name="review_decision.request"))
    if request is None:
        raise ApiRequestError("review_decision.request is required")
    record_payload = _require_mapping(decision_payload.get("record"), field_name="review_decision.record")
    reviewer_payload = _require_mapping(record_payload.get("reviewer"), field_name="review_decision.record.reviewer")
    record = ReviewRecord(
        review_id=record_payload["review_id"],
        review_request_id=record_payload["review_request_id"],
        task_id=record_payload["task_id"],
        reviewer=ReviewerIdentity(**reviewer_payload),
        reviewed_at=record_payload["reviewed_at"],
        outcome=ReviewOutcome(record_payload["outcome"]),
        reasoning=record_payload["reasoning"],
        authorized_target_status=record_payload["authorized_target_status"],
        follow_up_action=ReviewFollowUpAction(record_payload.get("follow_up_action", "none")),
        supersedes_review_id=record_payload.get("supersedes_review_id"),
        basis_refs=tuple(record_payload.get("basis_refs", [])),
        preserves_history=record_payload.get("preserves_history", True),
        metadata=dict(record_payload.get("metadata", {})),
    )
    return ReviewDecisionResult(
        request=request,
        record=record,
        recommended_target_status=decision_payload["recommended_target_status"],
        follow_up_action=ReviewFollowUpAction(decision_payload.get("follow_up_action", "none")),
    )


def _apply_submission_task_overlays(
    task_envelope: dict[str, Any],
    *,
    request_payload: dict[str, Any],
) -> dict[str, Any]:
    merged_task = deepcopy(task_envelope)

    task_status = _optional_non_empty_string(request_payload.get("task_status"), field_name="task_status")
    if task_status is not None:
        merged_task["status"] = task_status
        merged_task["timestamps"]["completed_at"] = (
            merged_task["timestamps"]["updated_at"] if task_status == "completed" else None
        )

    assigned_executor = _optional_mapping(request_payload.get("assigned_executor"), field_name="assigned_executor")
    if assigned_executor is not None:
        merged_task["assigned_executor"] = dict(assigned_executor)

    linked_artifacts_payload = request_payload.get("linked_artifacts")
    if linked_artifacts_payload is not None:
        linked_artifacts = _optional_object_list(linked_artifacts_payload, field_name="linked_artifacts")
        merged_task["artifacts"]["items"] = [deepcopy(artifact) for artifact in linked_artifacts]

    completion_evidence_update = _optional_mapping(
        request_payload.get("completion_evidence"),
        field_name="completion_evidence",
    )
    if completion_evidence_update is not None:
        merged_task["artifacts"]["completion_evidence"].update(dict(completion_evidence_update))

    return merged_task


def _with_linear_coordination(
    task_envelope: dict[str, Any],
    *,
    linear_facts: LinearFacts | None,
    linked_by: str,
    source: str,
) -> dict[str, Any]:
    if linear_facts is None:
        return task_envelope

    merged_task = deepcopy(task_envelope)
    coordination = _optional_mapping(merged_task.get("coordination"), field_name="task_envelope.coordination") or {}
    coordination["linear"] = {
        "record_found": linear_facts.record_found,
        "issue_id": linear_facts.issue_id,
        "issue_key": linear_facts.issue_key,
        "state": linear_facts.state,
        "workflow": _to_jsonable(linear_facts.workflow),
        "project": _to_jsonable(linear_facts.project),
        "task_reference": _to_jsonable(linear_facts.task_reference),
        "reasons": list(linear_facts.reasons),
        "provenance": {
            "linked_at": _iso_now(),
            "linked_by": linked_by,
            "source": source,
        },
    }
    merged_task["coordination"] = coordination
    return merged_task


def parse_evaluation_request(payload: dict[str, Any]) -> HarnessEvaluationRequest:
    """Parse a canonical HTTP evaluation request into the public evaluator input."""

    request_payload = _require_mapping(payload.get("request"), field_name="request")
    task_envelope = _require_mapping(request_payload.get("task_envelope"), field_name="task_envelope")
    _require_non_empty_string(task_envelope.get("id"), field_name="task_envelope.id")
    task_envelope = _apply_submission_task_overlays(task_envelope, request_payload=request_payload)

    external_facts = _parse_external_facts(
        _optional_mapping(request_payload.get("external_facts"), field_name="external_facts")
    )
    task_envelope = _with_linear_coordination(
        task_envelope,
        linear_facts=external_facts.linear_facts if external_facts is not None else None,
        linked_by=(task_envelope.get("origin") or {}).get("source_system") or "harness",
        source="evaluation_request.external_facts",
    )

    return HarnessEvaluationRequest(
        task_envelope=task_envelope,
        external_facts=external_facts,
        claimed_completion=bool(request_payload.get("claimed_completion", False)),
        acceptance_criteria_satisfied=bool(request_payload.get("acceptance_criteria_satisfied", False)),
        runtime_facts=_parse_runtime_facts(_optional_mapping(request_payload.get("runtime_facts"), field_name="runtime_facts")),
        unresolved_conditions=_optional_string_tuple(
            request_payload.get("unresolved_conditions"),
            field_name="unresolved_conditions",
        ),
        review_reasons=_optional_string_tuple(request_payload.get("review_reasons"), field_name="review_reasons"),
        review_request=_parse_review_request(_optional_mapping(request_payload.get("review_request"), field_name="review_request")),
        review_decision=_parse_review_decision(_optional_mapping(request_payload.get("review_decision"), field_name="review_decision")),
    )


def _merge_artifacts(existing_task: dict[str, Any], *, new_artifacts: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    merged_task = deepcopy(existing_task)
    artifact_items = list(merged_task["artifacts"]["items"])
    existing_ids = {str(item.get("id")) for item in artifact_items if item.get("id") is not None}

    for artifact in new_artifacts:
        artifact_id = artifact.get("id")
        if artifact_id is not None and str(artifact_id) in existing_ids:
            raise ApiRequestError(f"new_artifacts contains duplicate artifact id {artifact_id!r}")
        artifact_items.append(deepcopy(artifact))
        if artifact_id is not None:
            existing_ids.add(str(artifact_id))

    merged_task["artifacts"]["items"] = artifact_items
    return merged_task


def _merge_completion_evidence(
    existing_task: dict[str, Any],
    *,
    completion_evidence_update: dict[str, Any] | None,
) -> dict[str, Any]:
    if completion_evidence_update is None:
        return existing_task

    merged_task = deepcopy(existing_task)
    merged_task["artifacts"]["completion_evidence"].update(dict(completion_evidence_update))
    return merged_task


def _parse_completion_claim(payload: dict[str, Any]) -> dict[str, Any]:
    claim_payload = _require_mapping(payload.get("completion_claim"), field_name="completion_claim")
    claim_id = _require_non_empty_string(claim_payload.get("claim_id"), field_name="completion_claim.claim_id")
    reported_at = _require_non_empty_string(claim_payload.get("reported_at"), field_name="completion_claim.reported_at")
    reported_by = _optional_non_empty_string(claim_payload.get("reported_by"), field_name="completion_claim.reported_by")
    reason = _optional_non_empty_string(claim_payload.get("reason"), field_name="completion_claim.reason")
    metadata = _optional_mapping(claim_payload.get("metadata"), field_name="completion_claim.metadata") or {}

    return {
        "claim_id": claim_id,
        "reported_at": reported_at,
        "reported_by": reported_by,
        "reason": reason,
        "metadata": dict(metadata),
    }


def _parse_execution_attempt(payload: dict[str, Any], *, completion_claim: dict[str, Any]) -> dict[str, Any] | None:
    attempt_payload = _optional_mapping(payload.get("execution_attempt"), field_name="execution_attempt")
    if attempt_payload is None:
        return None

    attempt_id = _require_non_empty_string(attempt_payload.get("attempt_id"), field_name="execution_attempt.attempt_id")
    recorded_at = _optional_non_empty_string(attempt_payload.get("recorded_at"), field_name="execution_attempt.recorded_at")
    status = _optional_non_empty_string(attempt_payload.get("status"), field_name="execution_attempt.status") or "reported"
    reported_by = _optional_non_empty_string(attempt_payload.get("reported_by"), field_name="execution_attempt.reported_by")
    artifact_references = _optional_object_list(
        attempt_payload.get("artifact_references"),
        field_name="execution_attempt.artifact_references",
    )
    metadata = _optional_mapping(attempt_payload.get("metadata"), field_name="execution_attempt.metadata") or {}

    return {
        "attempt_id": attempt_id,
        "recorded_at": recorded_at or completion_claim["reported_at"],
        "status": status,
        "reported_by": reported_by or completion_claim.get("reported_by"),
        "completion_claim_id": completion_claim["claim_id"],
        "artifact_references": [deepcopy(artifact) for artifact in artifact_references],
        "metadata": dict(metadata),
        "reevaluation": {},
    }


def _with_advisory_completion_claim(task_envelope: dict[str, Any], *, claim: dict[str, Any]) -> dict[str, Any]:
    merged_task = deepcopy(task_envelope)
    execution_metadata = dict(merged_task["observability"]["execution_metadata"] or {})
    existing_claims = execution_metadata.get("advisory_completion_claims")
    if existing_claims is None:
        advisory_claims: list[dict[str, Any]] = []
    elif isinstance(existing_claims, list):
        advisory_claims = [deepcopy(item) for item in existing_claims]
    else:
        raise ApiRequestError("observability.execution_metadata.advisory_completion_claims must be an array")

    advisory_claims.append(deepcopy(claim))
    execution_metadata["advisory_completion_claims"] = advisory_claims
    merged_task["observability"]["execution_metadata"] = execution_metadata
    merged_task["timestamps"]["updated_at"] = _iso_now()
    return merged_task


def _with_execution_attempt_record(task_envelope: dict[str, Any], *, attempt: dict[str, Any]) -> dict[str, Any]:
    merged_task = deepcopy(task_envelope)
    execution_metadata = dict(merged_task["observability"]["execution_metadata"] or {})
    existing_attempts = execution_metadata.get("execution_attempts")
    if existing_attempts is None:
        execution_attempts: list[dict[str, Any]] = []
    elif isinstance(existing_attempts, list):
        execution_attempts = [deepcopy(item) for item in existing_attempts]
    else:
        raise ApiRequestError("observability.execution_metadata.execution_attempts must be an array")

    execution_attempts.append(deepcopy(attempt))
    execution_metadata["execution_attempts"] = execution_attempts
    merged_task["observability"]["execution_metadata"] = execution_metadata
    merged_task["timestamps"]["updated_at"] = _iso_now()
    return merged_task


def _with_reevaluation_linked_execution_attempt(
    task_envelope: dict[str, Any],
    *,
    completion_claim_id: str,
    evaluation_record: EvaluationRecord | None,
) -> dict[str, Any]:
    if evaluation_record is None:
        return task_envelope

    merged_task = deepcopy(task_envelope)
    execution_metadata = dict(merged_task["observability"]["execution_metadata"] or {})
    existing_attempts = execution_metadata.get("execution_attempts")
    if existing_attempts is None:
        return merged_task
    if not isinstance(existing_attempts, list):
        raise ApiRequestError("observability.execution_metadata.execution_attempts must be an array")

    updated_attempts: list[Any] = [deepcopy(item) for item in existing_attempts]
    for attempt in reversed(updated_attempts):
        if not isinstance(attempt, dict):
            continue
        if attempt.get("completion_claim_id") != completion_claim_id:
            continue
        reevaluation = dict(attempt.get("reevaluation") or {})
        reevaluation["evaluation_id"] = evaluation_record.evaluation_id
        reevaluation["linked_at"] = evaluation_record.recorded_at
        reevaluation["action"] = (evaluation_record.result if isinstance(evaluation_record.result, dict) else {}).get("action")
        attempt["reevaluation"] = reevaluation
        break
    else:
        return merged_task

    execution_metadata["execution_attempts"] = updated_attempts
    merged_task["observability"]["execution_metadata"] = execution_metadata
    merged_task["timestamps"]["updated_at"] = _iso_now()
    return merged_task


def parse_completion_claim_request(task_envelope: dict[str, Any], payload: dict[str, Any]) -> HarnessEvaluationRequest:
    """Parse an executor completion claim into canonical reevaluation input."""

    request_payload = _require_mapping(payload.get("request"), field_name="request")
    completion_claim = _parse_completion_claim(request_payload)
    merged_task = _with_advisory_completion_claim(task_envelope, claim=completion_claim)
    execution_attempt = _parse_execution_attempt(request_payload, completion_claim=completion_claim)
    if execution_attempt is not None:
        merged_task = _with_execution_attempt_record(merged_task, attempt=execution_attempt)

    new_artifacts = _optional_object_list(request_payload.get("new_artifacts"), field_name="new_artifacts")
    if new_artifacts:
        merged_task = _merge_artifacts(merged_task, new_artifacts=new_artifacts)

    completion_evidence_update = _optional_mapping(
        request_payload.get("completion_evidence"),
        field_name="completion_evidence",
    )
    if completion_evidence_update is not None:
        merged_task = _merge_completion_evidence(
            merged_task,
            completion_evidence_update=completion_evidence_update,
        )

    review_request = _parse_review_request(_optional_mapping(request_payload.get("review_request"), field_name="review_request"))
    review_decision = _parse_review_decision(
        _optional_mapping(request_payload.get("review_decision"), field_name="review_decision")
    )

    if review_request is not None and review_request.task_id != merged_task["id"]:
        raise ApiRequestError("review_request.task_id must match the stored task id")
    if review_decision is not None and review_decision.record.task_id != merged_task["id"]:
        raise ApiRequestError("review_decision.record.task_id must match the stored task id")

    external_facts = _parse_external_facts(
        _optional_mapping(request_payload.get("external_facts"), field_name="external_facts")
    )
    merged_task = _with_linear_coordination(
        merged_task,
        linear_facts=external_facts.linear_facts if external_facts is not None else None,
        linked_by="reevaluation",
        source="completion_claim.external_facts",
    )

    return HarnessEvaluationRequest(
        task_envelope=merged_task,
        external_facts=external_facts,
        claimed_completion=True,
        acceptance_criteria_satisfied=bool(request_payload.get("acceptance_criteria_satisfied", False)),
        runtime_facts=_parse_runtime_facts(_optional_mapping(request_payload.get("runtime_facts"), field_name="runtime_facts")),
        unresolved_conditions=_optional_string_tuple(
            request_payload.get("unresolved_conditions"),
            field_name="unresolved_conditions",
        ),
        review_reasons=_optional_string_tuple(request_payload.get("review_reasons"), field_name="review_reasons"),
        review_request=review_request,
        review_decision=review_decision,
    )


def parse_reevaluation_request(task_envelope: dict[str, Any], payload: dict[str, Any]) -> HarnessEvaluationRequest:
    """Parse a reevaluation payload against an existing stored TaskEnvelope."""

    request_payload = _require_mapping(payload.get("request"), field_name="request")
    merged_task = deepcopy(task_envelope)

    new_artifacts = _optional_object_list(request_payload.get("new_artifacts"), field_name="new_artifacts")
    if new_artifacts:
        merged_task = _merge_artifacts(merged_task, new_artifacts=new_artifacts)

    completion_evidence_update = _optional_mapping(
        request_payload.get("completion_evidence"),
        field_name="completion_evidence",
    )
    if completion_evidence_update is not None:
        merged_task = _merge_completion_evidence(
            merged_task,
            completion_evidence_update=completion_evidence_update,
        )

    merged_task["timestamps"]["updated_at"] = _iso_now()

    review_request = _parse_review_request(_optional_mapping(request_payload.get("review_request"), field_name="review_request"))
    review_decision = _parse_review_decision(
        _optional_mapping(request_payload.get("review_decision"), field_name="review_decision")
    )

    if review_request is not None and review_request.task_id != merged_task["id"]:
        raise ApiRequestError("review_request.task_id must match the stored task id")
    if review_decision is not None and review_decision.record.task_id != merged_task["id"]:
        raise ApiRequestError("review_decision.record.task_id must match the stored task id")

    external_facts = _parse_external_facts(
        _optional_mapping(request_payload.get("external_facts"), field_name="external_facts")
    )
    merged_task = _with_linear_coordination(
        merged_task,
        linear_facts=external_facts.linear_facts if external_facts is not None else None,
        linked_by="reevaluation",
        source="reevaluation_request.external_facts",
    )

    return HarnessEvaluationRequest(
        task_envelope=merged_task,
        external_facts=external_facts,
        claimed_completion=bool(request_payload.get("claimed_completion", False)),
        acceptance_criteria_satisfied=bool(request_payload.get("acceptance_criteria_satisfied", False)),
        runtime_facts=_parse_runtime_facts(_optional_mapping(request_payload.get("runtime_facts"), field_name="runtime_facts")),
        unresolved_conditions=_optional_string_tuple(
            request_payload.get("unresolved_conditions"),
            field_name="unresolved_conditions",
        ),
        review_reasons=_optional_string_tuple(request_payload.get("review_reasons"), field_name="review_reasons"),
        review_request=review_request,
        review_decision=review_decision,
    )


def _dispatch_attempt_number(task_envelope: dict[str, Any]) -> int:
    attempts = ((task_envelope.get("observability") or {}).get("execution_metadata") or {}).get("execution_attempts") or []
    if not isinstance(attempts, list):
        raise ApiRequestError("observability.execution_metadata.execution_attempts must be an array")
    return len(attempts) + 1


def _dispatch_attempt_status(execution_events: tuple[dict[str, Any], ...]) -> str:
    event_types = {str(event.get("event_type")) for event in execution_events}
    if "execution_failed" in event_types:
        return "failed"
    if "execution_succeeded" in event_types:
        return "completed"
    if "execution_stalled" in event_types or "execution_timed_out" in event_types:
        return "blocked"
    if "progress_reported" in event_types:
        return "in_progress"
    return "started"


def _dispatch_policy_decision(task_envelope: dict[str, Any]) -> tuple[bool, str]:
    task_status = str(task_envelope.get("status") or "")
    if task_status not in _AUTO_DISPATCHABLE_STATUSES:
        return False, f"status={task_status} is not auto-dispatch eligible"
    if task_status in _TERMINAL_TASK_STATUSES:
        return False, f"status={task_status} is terminal"
    if task_status in _DISPATCH_BLOCKED_STATUSES or task_status == "blocked":
        return False, f"status={task_status} is blocked for dispatch"

    execution_attempts = ((task_envelope.get("observability") or {}).get("execution_metadata") or {}).get("execution_attempts") or []
    if isinstance(execution_attempts, list) and any(isinstance(attempt, dict) for attempt in execution_attempts):
        return False, "execution attempt already recorded for current task state"

    return True, "eligible: non_terminal_non_blocked_no_existing_attempt"


def _executor_hint_from_task(task_envelope: dict[str, Any]) -> str | None:
    assigned_executor = task_envelope.get("assigned_executor")
    if not isinstance(assigned_executor, dict):
        return None
    executor_type = assigned_executor.get("executor_type")
    if not isinstance(executor_type, str):
        return None
    normalized_executor = executor_type.strip().lower()
    if not normalized_executor:
        return None
    return normalized_executor


def _executor_hint(hint: str | None) -> str:
    if hint is None:
        return "codex"
    normalized = hint.strip().lower()
    if not normalized:
        return "codex"
    if normalized in {"codex", "openclaw", "stub-executor", "stub"}:
        return normalized
    raise ApiRequestError("request.executor must be one of: codex, openclaw, stub-executor")


def _collect_review_activity(records: tuple[EvaluationRecord, ...]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    requests: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []

    for record in records:
        result_payload = record.result if isinstance(record.result, dict) else {}
        request_payload = record.request if isinstance(record.request, dict) else {}
        enforcement_result = dict(result_payload.get("enforcement_result") or {})

        review_request = enforcement_result.get("review_request") or request_payload.get("review_request")
        if isinstance(review_request, dict):
            requests.append(review_request)

        review_decision = enforcement_result.get("review_decision") or request_payload.get("review_decision")
        if isinstance(review_decision, dict):
            review_record = review_decision.get("record")
            if isinstance(review_record, dict):
                decisions.append(review_record)

    return requests, decisions


def _review_status_from_activity(
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


def _review_gate_is_active(task_envelope: dict[str, Any], records: tuple[EvaluationRecord, ...]) -> bool:
    if task_envelope.get("status") == "in_review":
        return True
    requests, decisions = _collect_review_activity(records)
    return _review_status_from_activity(requests=requests, decisions=decisions) == "requested"


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


def evaluate_http_payload(payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Evaluate one HTTP request payload and return an HTTP status code plus JSON body."""

    try:
        request = parse_evaluation_request(payload)
    except Exception as error:
        return HTTPStatus.BAD_REQUEST, {
            "error": str(error),
            "invalid_input": True,
        }

    status, response_payload, _ = _evaluate_request(request)
    return status, response_payload


def _task_path_components(path: str) -> tuple[str, ...]:
    parsed_path = urlparse(path).path.strip("/")
    if not parsed_path:
        return ()
    return tuple(unquote(component) for component in parsed_path.split("/"))


def _serialize_evaluation_record(record: EvaluationRecord) -> dict[str, Any]:
    return _to_jsonable(record)


def _parse_database_host(database_url: str) -> str | None:
    parsed = urlparse(database_url)
    return parsed.hostname


def _evaluate_request(request: HarnessEvaluationRequest) -> tuple[int, dict[str, Any], HarnessEvaluationResult | None]:
    try:
        result = evaluate_task_case(request)
    except (ApiRequestError, ValueError) as error:
        return HTTPStatus.BAD_REQUEST, {
            "error": str(error),
            "invalid_input": True,
        }, None

    status = HTTPStatus.BAD_REQUEST if result.invalid_input else HTTPStatus.OK
    return status, _to_jsonable(result), result


class HarnessApiService:
    """Stateful HTTP-facing service that reuses the canonical evaluator and store."""

    def __init__(self, *, store: HarnessStore | None = None) -> None:
        self.store = store or build_harness_store()
        self.read_model_service = HarnessReadModelService(store=self.store)

    def _build_postgres_health_payload(self, store: PostgresHarnessStore) -> dict[str, Any]:
        expected_tables = ("tasks", "evaluation_records")
        schema_ready = False
        status = "degraded"

        try:
            with store._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT EXISTS (
                            SELECT 1
                            FROM information_schema.tables
                            WHERE table_schema = 'public' AND table_name = %s
                        )
                        """,
                        (expected_tables[0],),
                    )
                    tasks_exists_row = cursor.fetchone()
                    cursor.execute(
                        """
                        SELECT EXISTS (
                            SELECT 1
                            FROM information_schema.tables
                            WHERE table_schema = 'public' AND table_name = %s
                        )
                        """,
                        (expected_tables[1],),
                    )
                    evaluation_records_exists_row = cursor.fetchone()
        except Exception:
            schema_ready = False
        else:
            tasks_exists = bool(tasks_exists_row and tasks_exists_row[0])
            evaluation_records_exists = bool(
                evaluation_records_exists_row and evaluation_records_exists_row[0]
            )
            schema_ready = tasks_exists and evaluation_records_exists
            status = "ok" if schema_ready else "degraded"

        return {
            "status": status,
            "store_backend": "postgres",
            "database_configured": True,
            "database_host": _parse_database_host(store.database_url),
            "database_schema_ready": schema_ready,
        }

    def health(self) -> tuple[int, dict[str, Any]]:
        if isinstance(self.store, PostgresHarnessStore):
            return HTTPStatus.OK, self._build_postgres_health_payload(self.store)
        return HTTPStatus.OK, {
            "status": "ok",
            "store_backend": "file",
            "database_configured": False,
            "database_host": None,
            "database_schema_ready": None,
        }

    def _upsert_task(self, task_envelope: dict[str, Any]) -> dict[str, Any]:
        task_id = str(task_envelope["id"])
        try:
            self.store.get_task(task_id)
        except TaskEnvelopeNotFoundError:
            return self.store.put_task(task_envelope)
        return self.store.update_task(task_envelope)

    def _with_retry_provenance(
        self,
        request: HarnessEvaluationRequest,
        *,
        attempt_number: int,
        max_retries: int,
        retry_reason: str,
        category: FailureType,
    ) -> HarnessEvaluationRequest:
        runtime_facts = request.runtime_facts
        next_attempt_count = max(runtime_facts.attempt_count, 1) + 1
        return replace(
            request,
            runtime_facts=replace(
                runtime_facts,
                attempt_count=next_attempt_count,
                latest_attempt_outcome="retry_scheduled",
            ),
            retry_context={
                "attempt_number": attempt_number,
                "max_retries": max_retries,
                "triggered_by_category": category.value,
                "triggered_by_reason": retry_reason,
                "is_final_attempt": attempt_number >= max_retries,
                "scheduled_at": _iso_now(),
            },
        )

    def _evaluate_with_classified_retries(
        self,
        request: HarnessEvaluationRequest,
    ) -> tuple[int, dict[str, Any], HarnessEvaluationResult | None, tuple[tuple[HarnessEvaluationRequest, HarnessEvaluationResult], ...]]:
        attempts: list[tuple[HarnessEvaluationRequest, HarnessEvaluationResult]] = []
        max_retries = _classified_retry_budget()
        active_request = request

        for retry_index in range(max_retries + 1):
            status, response_payload, result = _evaluate_request(active_request)
            if result is None:
                return status, response_payload, None, tuple(attempts)
            attempts.append((active_request, result))

            category = result.failure_classification.category
            should_retry = (
                status == HTTPStatus.OK
                and not result.invalid_input
                and result.failure_classification.retryable
                and category in _RETRYABLE_FAILURE_CATEGORIES
                and retry_index < max_retries
            )
            if not should_retry:
                return status, response_payload, result, tuple(attempts)

            active_request = self._with_retry_provenance(
                request=active_request,
                attempt_number=retry_index + 1,
                max_retries=max_retries,
                retry_reason=result.failure_classification.reason,
                category=category,
            )

        status, response_payload, result = _evaluate_request(active_request)
        if result is None:
            return status, response_payload, None, tuple(attempts)
        attempts.append((active_request, result))
        return status, response_payload, result, tuple(attempts)

    def submit(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        try:
            request = parse_evaluation_request(payload)
        except Exception as error:
            return HTTPStatus.BAD_REQUEST, {
                "error": str(error),
                "invalid_input": True,
            }

        task_id = str(request.task_envelope["id"])
        try:
            self.store.get_task(task_id)
            return HTTPStatus.CONFLICT, {
                "error": f"Task {task_id!r} already exists; use reevaluate for existing tasks",
                "duplicate_task_id": True,
            }
        except TaskEnvelopeNotFoundError:
            pass

        status, response_payload, result, attempts = self._evaluate_with_classified_retries(request)
        if result is None:
            return status, response_payload

        if result.invalid_input:
            return status, response_payload

        try:
            stored_task = self.store.create_task(result.task_envelope)
        except TaskEnvelopeAlreadyExistsError as error:
            return HTTPStatus.CONFLICT, {
                "error": str(error),
                "duplicate_task_id": True,
            }

        record = None
        for attempt_request, attempt_result in attempts:
            record = self.store.put_evaluation_record(request=attempt_request, result=attempt_result)
        response_payload["task_envelope"] = _to_jsonable(stored_task)
        if record is not None:
            response_payload["evaluation_record"] = _serialize_evaluation_record(record)

        should_dispatch, reason = _dispatch_policy_decision(stored_task)
        if should_dispatch:
            dispatch_status, dispatch_payload = self.dispatch_task(
                task_id,
                {
                    "request": {
                        "executor": _executor_hint_from_task(stored_task),
                        "execution_parameters": {
                            "dispatch_policy_reason": reason,
                            "dispatch_policy_stage": "post_ingestion",
                        },
                        "dispatch_mode": "automatic",
                        "dispatch_trigger": "automatic_policy_post_ingestion",
                        "dispatch_reason": reason,
                    }
                },
            )
            response_payload["automatic_dispatch"] = {
                "attempted": True,
                "dispatchable": True,
                "reason": reason,
                "status": int(dispatch_status),
            }
            if dispatch_status == HTTPStatus.OK:
                if isinstance(dispatch_payload.get("dispatch"), dict):
                    response_payload["automatic_dispatch"]["dispatch"] = deepcopy(dispatch_payload["dispatch"])
                if isinstance(dispatch_payload.get("task_envelope"), dict):
                    stored_task = dispatch_payload["task_envelope"]
                    response_payload["task_envelope"] = _to_jsonable(stored_task)
                if isinstance(dispatch_payload.get("evaluation_record"), dict):
                    response_payload["evaluation_record"] = deepcopy(dispatch_payload["evaluation_record"])
            else:
                response_payload["automatic_dispatch"]["error"] = dispatch_payload.get("error")
        else:
            response_payload["automatic_dispatch"] = {
                "attempted": False,
                "dispatchable": False,
                "reason": reason,
            }
        return status, response_payload

    def submit_linear_ingress(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        try:
            canonical_payload = translate_linear_submission_payload(payload)
        except (LinearIngressInputError, LinearConnectorInputError, ValueError) as error:
            return HTTPStatus.BAD_REQUEST, {
                "error": str(error),
                "invalid_input": True,
            }

        return self.submit(canonical_payload)


    def submit_manual_ingress(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        try:
            canonical_payload = translate_manual_submission_payload(payload)
        except (ManualIngressInputError, ValueError) as error:
            return HTTPStatus.BAD_REQUEST, {
                "error": str(error),
                "invalid_input": True,
            }

        return self.submit(canonical_payload)

    def submit_openclaw_ingress(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        try:
            canonical_payload = translate_openclaw_submission_payload(payload)
        except (OpenClawIngressInputError, ValueError) as error:
            return HTTPStatus.BAD_REQUEST, {
                "error": str(error),
                "invalid_input": True,
            }

        return self.submit(canonical_payload)

    def evaluate(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        try:
            request = parse_evaluation_request(payload)
        except Exception as error:
            return HTTPStatus.BAD_REQUEST, {
                "error": str(error),
                "invalid_input": True,
            }

        task_id = str(request.task_envelope["id"])
        try:
            stored_task = self.store.get_task(task_id)
        except TaskEnvelopeNotFoundError:
            pass
        else:
            existing_records = self.store.list_evaluation_records(task_id)
            request_payload = _require_mapping(payload.get("request"), field_name="request")
            request = replace(
                request,
                task_envelope=_apply_submission_task_overlays(stored_task, request_payload=request_payload),
                review_is_active=_review_gate_is_active(stored_task, existing_records),
            )

        status, response_payload, result, attempts = self._evaluate_with_classified_retries(request)
        if result is None:
            return status, response_payload

        if result.invalid_input:
            return status, response_payload

        stored_task = self._upsert_task(result.task_envelope)
        record = None
        for attempt_request, attempt_result in attempts:
            record = self.store.put_evaluation_record(request=attempt_request, result=attempt_result)
        response_payload["task_envelope"] = _to_jsonable(stored_task)
        if record is not None:
            response_payload["evaluation_record"] = _serialize_evaluation_record(record)
        return status, response_payload

    def reevaluate(self, task_id: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        try:
            stored_task = self.store.get_task(task_id)
        except TaskEnvelopeNotFoundError:
            return HTTPStatus.NOT_FOUND, {"error": f"Task {task_id!r} was not found"}

        try:
            request = parse_reevaluation_request(stored_task, payload)
        except Exception as error:
            return HTTPStatus.BAD_REQUEST, {
                "error": str(error),
                "invalid_input": True,
            }

        request = replace(
            request,
            review_is_active=_review_gate_is_active(
                stored_task,
                self.store.list_evaluation_records(task_id),
            ),
        )

        status, response_payload, result, attempts = self._evaluate_with_classified_retries(request)
        if result is None:
            return status, response_payload

        if result.invalid_input:
            return status, response_payload

        stored_task = self.store.update_task(result.task_envelope)
        record = None
        for attempt_request, attempt_result in attempts:
            record = self.store.put_evaluation_record(request=attempt_request, result=attempt_result)
        response_payload["task_envelope"] = _to_jsonable(stored_task)
        if record is not None:
            response_payload["evaluation_record"] = _serialize_evaluation_record(record)
        return status, response_payload

    def submit_completion_claim(self, task_id: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        try:
            stored_task = self.store.get_task(task_id)
        except TaskEnvelopeNotFoundError:
            return HTTPStatus.NOT_FOUND, {"error": f"Task {task_id!r} was not found"}

        try:
            request = parse_completion_claim_request(stored_task, payload)
        except Exception as error:
            return HTTPStatus.BAD_REQUEST, {
                "error": str(error),
                "invalid_input": True,
            }

        request = replace(
            request,
            review_is_active=_review_gate_is_active(
                stored_task,
                self.store.list_evaluation_records(task_id),
            ),
        )

        status, response_payload, result, attempts = self._evaluate_with_classified_retries(request)
        if result is None:
            return status, response_payload
        if result.invalid_input:
            return status, response_payload

        stored_task = self.store.update_task(result.task_envelope)
        record = None
        for attempt_request, attempt_result in attempts:
            record = self.store.put_evaluation_record(request=attempt_request, result=attempt_result)
        latest_claim_id = (
            request.task_envelope.get("observability", {})
            .get("execution_metadata", {})
            .get("advisory_completion_claims", [{}])[-1]
            .get("claim_id")
        )
        if isinstance(latest_claim_id, str) and latest_claim_id:
            stored_task = self.store.update_task(
                _with_reevaluation_linked_execution_attempt(
                    stored_task,
                    completion_claim_id=latest_claim_id,
                    evaluation_record=record,
                )
            )
        response_payload["task_envelope"] = _to_jsonable(stored_task)
        if record is not None:
            response_payload["evaluation_record"] = _serialize_evaluation_record(record)
        return status, response_payload

    def dispatch_task(self, task_id: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        try:
            stored_task = self.store.get_task(task_id)
        except TaskEnvelopeNotFoundError:
            return HTTPStatus.NOT_FOUND, {"error": f"Task {task_id!r} was not found"}

        task_status = str(stored_task.get("status") or "")
        if task_status in _TERMINAL_TASK_STATUSES:
            return HTTPStatus.CONFLICT, {"error": f"Task {task_id!r} is terminal and cannot be dispatched"}
        if task_status in _DISPATCH_BLOCKED_STATUSES:
            return HTTPStatus.CONFLICT, {"error": f"Task {task_id!r} is currently blocked for dispatch"}

        request_payload = _optional_mapping(payload.get("request"), field_name="request") or {}
        executor = _executor_hint(_optional_non_empty_string(request_payload.get("executor"), field_name="request.executor"))
        dispatch_mode = _optional_non_empty_string(request_payload.get("dispatch_mode"), field_name="request.dispatch_mode") or "manual"
        dispatch_trigger = (
            _optional_non_empty_string(request_payload.get("dispatch_trigger"), field_name="request.dispatch_trigger")
            or "manual_api"
        )
        dispatch_reason = _optional_non_empty_string(request_payload.get("dispatch_reason"), field_name="request.dispatch_reason")
        execution_parameters = _optional_mapping(
            request_payload.get("execution_parameters"),
            field_name="request.execution_parameters",
        ) or {}
        extra_artifact_refs = _optional_object_list(
            request_payload.get("artifact_references"),
            field_name="request.artifact_references",
        )

        try:
            attempt_number = _dispatch_attempt_number(stored_task)
            attempt_id = f"attempt-{attempt_number}"
            dispatch_input = ExecutorDispatchInput.from_task_envelope(
                stored_task,
                attempt_id=attempt_id,
                assigned_executor=executor,
            )
            adapter_output = StubExecutorAdapter().dispatch(dispatch_input)
        except (ApiRequestError, ExecutorAdapterInputError, ValueError) as error:
            return HTTPStatus.BAD_REQUEST, {"error": str(error), "invalid_input": True}

        event_payloads = tuple(
            {
                "event_id": str(event.event_id),
                "event_type": str(event.event_type.value),
                "occurred_at": str(event.occurred_at),
                "source_system": str(event.provenance.source_system),
                "metadata": dict(event.metadata),
            }
            for event in adapter_output.events
        )
        artifact_references = [
            {
                "reference_id": str(item.reference_id),
                "artifact_type": str(item.artifact_type),
                "location": item.location,
                "external_id": item.external_id,
                "commit_sha": item.commit_sha,
                "metadata": dict(item.metadata),
            }
            for item in adapter_output.artifact_references
        ]
        artifact_references.extend(deepcopy(item) for item in extra_artifact_refs)
        attempt_status = _dispatch_attempt_status(event_payloads)
        claim_event = next(
            (
                event
                for event in reversed(adapter_output.events)
                if event.advisory_completion is not None
            ),
            None,
        )
        completion_claim_payload = claim_event.advisory_completion if claim_event is not None else None
        completion_claim = {
            "claim_id": (
                completion_claim_payload.claim_id
                if completion_claim_payload is not None
                else f"{attempt_id}:claim"
            ),
            "reported_at": _iso_now(),
            "reported_by": executor,
            "reason": dispatch_reason or f"{dispatch_mode} dispatch execution attempt recorded",
            "metadata": {
                "attempt_id": attempt_id,
                "dispatch_mode": dispatch_mode,
                "execution_parameters": dict(execution_parameters),
                "advisory_only": True,
            },
        }
        execution_attempt = {
            "attempt_id": attempt_id,
            "recorded_at": _iso_now(),
            "status": attempt_status,
            "reported_by": executor,
            "completion_claim_id": completion_claim["claim_id"],
            "artifact_references": artifact_references,
            "metadata": {
                "dispatch_id": f"dispatch:{task_id}:{attempt_number}",
                "dispatch_trigger": dispatch_trigger,
                "dispatch_mode": dispatch_mode,
                "dispatch_reason": dispatch_reason,
                "executor": executor,
                "execution_parameters": dict(execution_parameters),
                "dispatch_at": _iso_now(),
                "execution_events": list(event_payloads),
            },
            "reevaluation": {},
        }

        dispatch_response_payload = {
            "request": {
                "completion_claim": completion_claim,
                "execution_attempt": execution_attempt,
                "acceptance_criteria_satisfied": bool(request_payload.get("acceptance_criteria_satisfied", False)),
                "runtime_facts": {
                    "executor_reported_success": attempt_status == "completed",
                    "attempt_count": attempt_number,
                    "latest_attempt_outcome": attempt_status,
                },
            }
        }
        external_facts_payload = _optional_mapping(request_payload.get("external_facts"), field_name="request.external_facts")
        if external_facts_payload is not None:
            dispatch_response_payload["request"]["external_facts"] = deepcopy(external_facts_payload)

        status, response_payload = self.submit_completion_claim(task_id, dispatch_response_payload)
        if status == HTTPStatus.OK:
            response_payload["dispatch"] = {
                "dispatch_id": execution_attempt["metadata"]["dispatch_id"],
                "task_id": task_id,
                "attempt_id": attempt_id,
                "executor": executor,
                "attempt_status": attempt_status,
            }
        return status, response_payload

    def get_task(self, task_id: str) -> tuple[int, dict[str, Any]]:
        try:
            task = self.store.get_task(task_id)
        except TaskEnvelopeNotFoundError:
            return HTTPStatus.NOT_FOUND, {"error": f"Task {task_id!r} was not found"}
        return HTTPStatus.OK, {"task": task}

    def list_tasks(self) -> tuple[int, dict[str, Any]]:
        tasks = self.read_model_service.list_task_read_models()
        return HTTPStatus.OK, {"tasks": [_to_jsonable(task) for task in tasks]}

    def get_evaluation_history(self, task_id: str) -> tuple[int, dict[str, Any]]:
        try:
            self.store.get_task(task_id)
        except TaskEnvelopeNotFoundError:
            return HTTPStatus.NOT_FOUND, {"error": f"Task {task_id!r} was not found"}

        records = self.store.list_evaluation_records(task_id)
        return HTTPStatus.OK, {
            "task_id": task_id,
            "evaluations": [_serialize_evaluation_record(record) for record in records],
        }

    def get_task_read_model(self, task_id: str) -> tuple[int, dict[str, Any]]:
        try:
            read_model = self.read_model_service.build_task_read_model(task_id)
        except TaskEnvelopeNotFoundError:
            return HTTPStatus.NOT_FOUND, {"error": f"Task {task_id!r} was not found"}
        return HTTPStatus.OK, {"task": _to_jsonable(read_model)}

    def get_task_timeline(self, task_id: str) -> tuple[int, dict[str, Any]]:
        try:
            timeline = self.read_model_service.build_task_timeline(task_id)
        except TaskEnvelopeNotFoundError:
            return HTTPStatus.NOT_FOUND, {"error": f"Task {task_id!r} was not found"}
        return HTTPStatus.OK, timeline


class HarnessApiHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler exposing the Harness evaluation entry point."""

    server_version = "HarnessHTTP/0.1"
    service: HarnessApiService | None = None

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def _write_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path_components = _task_path_components(self.path)
        service = self.service or HarnessApiService()

        if path_components == ("health",):
            status, payload = service.health()
            self._write_json(status, payload)
            return

        if path_components == ("tasks",):
            status, payload = service.list_tasks()
            self._write_json(status, payload)
            return

        if len(path_components) == 2 and path_components[0] == "tasks":
            status, payload = service.get_task(path_components[1])
            self._write_json(status, payload)
            return

        if len(path_components) == 3 and path_components[0] == "tasks" and path_components[2] == "evaluations":
            status, payload = service.get_evaluation_history(path_components[1])
            self._write_json(status, payload)
            return

        if len(path_components) == 3 and path_components[0] == "tasks" and path_components[2] == "read-model":
            status, payload = service.get_task_read_model(path_components[1])
            self._write_json(status, payload)
            return

        if len(path_components) == 3 and path_components[0] == "tasks" and path_components[2] == "timeline":
            status, payload = service.get_task_timeline(path_components[1])
            self._write_json(status, payload)
            return

        self._write_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        path_components = _task_path_components(self.path)
        request_path = urlparse(self.path).path

        if request_path not in {"/evaluate", "/tasks", "/ingress/linear", "/ingress/manual", "/ingress/openclaw"} and not (
            len(path_components) == 3
            and path_components[0] == "tasks"
            and path_components[2] in {"reevaluate", "completion-claims", "dispatch"}
        ):
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length)
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except Exception as error:
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": f"Invalid JSON body: {error}"})
            return

        service = self.service or HarnessApiService()
        if request_path == "/tasks":
            status, response_payload = service.submit(payload)
        elif request_path == "/ingress/linear":
            status, response_payload = service.submit_linear_ingress(payload)
        elif request_path == "/ingress/manual":
            status, response_payload = service.submit_manual_ingress(payload)
        elif request_path == "/ingress/openclaw":
            status, response_payload = service.submit_openclaw_ingress(payload)
        elif request_path == "/evaluate":
            status, response_payload = service.evaluate(payload)
        elif len(path_components) == 3 and path_components[0] == "tasks" and path_components[2] == "completion-claims":
            status, response_payload = service.submit_completion_claim(path_components[1], payload)
        elif len(path_components) == 3 and path_components[0] == "tasks" and path_components[2] == "dispatch":
            status, response_payload = service.dispatch_task(path_components[1], payload)
        else:
            status, response_payload = service.reevaluate(path_components[1], payload)
        self._write_json(status, response_payload)


def run_server(
    *,
    host: str = "0.0.0.0",
    port: int = 8000,
    store_root: str = ".harness-store",
    store_backend: str | None = None,
    database_url: str | None = None,
    service: HarnessApiService | None = None,
) -> ThreadingHTTPServer:
    """Create and run the minimal HTTP API server."""

    api_service = service or HarnessApiService(
        store=build_harness_store(
            store_backend=store_backend,
            store_root=store_root,
            database_url=database_url,
        )
    )

    class _ConfiguredHarnessApiHandler(HarnessApiHandler):
        service = api_service

    server = ThreadingHTTPServer((host, port), _ConfiguredHarnessApiHandler)
    return server


def build_parser() -> argparse.ArgumentParser:
    """Build the minimal HTTP API CLI parser."""

    default_port = int(os.environ.get("PORT", "8000"))
    parser = argparse.ArgumentParser(description="Run the minimal Harness HTTP API wrapper.")
    parser.add_argument("--host", default="0.0.0.0", help="Host interface to bind")
    parser.add_argument("--port", type=int, default=default_port, help="Port to bind")
    parser.add_argument(
        "--store-root",
        default=".harness-store",
        help="Directory for persisted task snapshots and evaluation history",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the minimal HTTP API server."""

    args = build_parser().parse_args(argv)
    server = run_server(host=args.host, port=args.port, store_root=args.store_root)
    print(f"Harness API listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
