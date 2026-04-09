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
from modules.contracts.failure_classification import FailureClassification, FailureSource, FailureType
from modules.contracts.task_envelope_lifecycle import apply_task_transition
from modules.contracts.task_envelope_end_to_end import CanonicalExternalFactBundle
from modules.contracts.task_envelope_external_facts import ExternalFactValidationError, GitHubArtifactFacts, LinearFacts
from modules.contracts.task_envelope_enforcement import EnforcementAction, EnforcementResult
from modules.contracts.task_envelope_reconciliation import ExpectedCodeContext
from modules.contracts.task_envelope_review import (
    ReviewDecisionResult,
    ReviewFollowUpAction,
    ReviewOutcome,
    ReviewRecord,
    ReviewRequest,
    ReviewTrigger,
    ReviewValidationError,
    ReviewerIdentity,
    validate_review_decision_result,
)
from modules.contracts.task_envelope_verification import RuntimeVerificationFacts
from modules.evaluation import HarnessEvaluationRequest, HarnessEvaluationResult, evaluate_task_case
from modules.read_model import HarnessReadModelService
from modules.reconciliation_runtime import (
    ReconciliationFailureType,
    ReconciliationFailureDisposition,
    ReconciliationHandlerRegistry,
    ReconciliationRuntimeError,
    ReconciliationAttemptStatus,
    build_default_reconciliation_registry,
    ensure_reconciliation_state,
    task_has_valid_current_run_commit_artifact,
    task_has_valid_current_run_pull_request_artifact,
)
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
_DEFAULT_INVALID_EXECUTION_RETRY_BUDGET = 1
_INVALID_EXECUTION_RETRY_BUDGET_ENV = "HARNESS_INVALID_EXECUTION_RETRY_BUDGET"
_RETRYABLE_FAILURE_CATEGORIES = frozenset(
    {
        FailureType.BOOTSTRAP_FAILURE,
        FailureType.DISPATCH_FAILURE,
        FailureType.EXECUTOR_FAILURE,
        FailureType.EVIDENCE_INSUFFICIENT,
    }
)
_CODE_EXECUTION_ARTIFACT_TYPES = frozenset({"branch", "commit", "pull_request", "changed_file"})
_CODE_EXECUTOR_TYPES = frozenset({"codex", "openclaw", "stub-executor", "stub"})
_RESERVED_SHARED_BRANCH_NAMES = frozenset({"work", "main", "master", "develop", "development", "trunk", "default"})
_TASK_SCOPED_CODE_BRANCH_PREFIXES = ("codex/", "kno-")
_TERMINAL_TASK_STATUSES = frozenset({"completed", "failed", "canceled"})
_DISPATCH_BLOCKED_STATUSES = frozenset({"in_review"})
_AUTO_DISPATCHABLE_STATUSES = frozenset({"dispatch_ready"})
_MANUAL_DISPATCHABLE_STATUSES = frozenset({"dispatch_ready", "assigned", "blocked"})
_CLARIFICATION_RESUME_TARGET_STATUSES = frozenset({"intake_ready", "planned", "dispatch_ready", "assigned", "executing"})
_DISPATCH_DEPENDENCY_STATUS_ORDER = {
    "planned": 0,
    "dispatch_ready": 1,
    "assigned": 2,
    "executing": 3,
    "completed": 4,
}
_ALLOWED_SUBMISSION_STATUS_OVERLAYS = frozenset({"intake_ready", "planned", "dispatch_ready", "assigned", "blocked"})
_ALLOWED_NEW_TASK_SUBMISSION_STATUSES = frozenset({"intake_ready", "planned", "dispatch_ready", "blocked"})


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


def _invalid_execution_retry_budget() -> int:
    raw_budget = os.getenv(_INVALID_EXECUTION_RETRY_BUDGET_ENV)
    if raw_budget is None:
        return _DEFAULT_INVALID_EXECUTION_RETRY_BUDGET
    try:
        parsed_budget = int(raw_budget)
    except ValueError:
        return _DEFAULT_INVALID_EXECUTION_RETRY_BUDGET
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
    try:
        return validate_review_decision_result(
            ReviewDecisionResult(
                request=request,
                record=record,
                recommended_target_status=decision_payload["recommended_target_status"],
                follow_up_action=ReviewFollowUpAction(decision_payload.get("follow_up_action", "none")),
            )
        )
    except ReviewValidationError as error:
        raise ApiRequestError(str(error)) from error


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
        merged_task["artifacts"]["items"] = [
            _sanitize_submitted_artifact(
                artifact,
                sanitize_submitted_verification=True,
                allow_trusted_verification_provenance=True,
            )
            for artifact in linked_artifacts
        ]

    completion_evidence_update = _optional_mapping(
        request_payload.get("completion_evidence"),
        field_name="completion_evidence",
    )
    if completion_evidence_update is not None:
        merged_task["artifacts"]["completion_evidence"].update(dict(completion_evidence_update))

    return merged_task

def _validate_submission_task_status_overlay(request_payload: dict[str, Any]) -> None:
    task_status = _optional_non_empty_string(request_payload.get("task_status"), field_name="task_status")
    if task_status is None:
        return
    if task_status not in _ALLOWED_SUBMISSION_STATUS_OVERLAYS:
        allowed = ", ".join(sorted(_ALLOWED_SUBMISSION_STATUS_OVERLAYS))
        raise ApiRequestError(
            f"task_status may only seed intake/planning lifecycle states ({allowed}); got {task_status!r}"
        )


def _new_task_submission_contract_violations(request_payload: dict[str, Any]) -> tuple[dict[str, str], ...]:
    task_envelope = _require_mapping(request_payload.get("task_envelope"), field_name="task_envelope")
    violations: list[dict[str, str]] = []

    def add_violation(*, rule: str, message: str, source: str) -> None:
        violations.append(
            {
                "rule": rule,
                "message": message,
                "source": source,
            }
        )

    if bool(request_payload.get("claimed_completion", False)):
        add_violation(
            rule="initial_claimed_completion_not_allowed",
            source="request.claimed_completion",
            message="New task submission cannot claim completion; completion truth must enter through reevaluation or completion-claim paths.",
        )
    if bool(request_payload.get("acceptance_criteria_satisfied", False)):
        add_violation(
            rule="initial_acceptance_assertion_not_allowed",
            source="request.acceptance_criteria_satisfied",
            message="New task submission cannot assert acceptance_criteria_satisfied; acceptance is decided by verification after execution evidence exists.",
        )
    if request_payload.get("runtime_facts") is not None:
        add_violation(
            rule="initial_runtime_facts_not_allowed",
            source="request.runtime_facts",
            message="New task submission cannot include runtime_facts; execution telemetry must come from dispatch, reevaluation, or completion claims.",
        )
    if request_payload.get("completion_evidence") is not None:
        add_violation(
            rule="initial_completion_evidence_overlay_not_allowed",
            source="request.completion_evidence",
            message="New task submission cannot include completion_evidence overlays; validated evidence must be produced after execution.",
        )
    overlay_task_status = _optional_non_empty_string(request_payload.get("task_status"), field_name="task_status")
    if overlay_task_status is not None and overlay_task_status not in _ALLOWED_NEW_TASK_SUBMISSION_STATUSES:
        allowed = ", ".join(sorted(_ALLOWED_NEW_TASK_SUBMISSION_STATUSES))
        add_violation(
            rule="initial_task_status_invalid",
            source="request.task_status",
            message=(
                f"New task submission may only start in pre-assignment lifecycle states ({allowed}); "
                f"got {overlay_task_status!r}."
            ),
        )
    assigned_executor = _optional_mapping(request_payload.get("assigned_executor"), field_name="assigned_executor")
    if assigned_executor is not None:
        add_violation(
            rule="initial_assigned_executor_not_allowed",
            source="request.assigned_executor",
            message="New task submission cannot pre-assign an executor; assignment truth must come from dispatcher-owned flows.",
        )

    linked_artifacts = request_payload.get("linked_artifacts")
    if isinstance(linked_artifacts, list):
        for index, artifact in enumerate(linked_artifacts):
            if not isinstance(artifact, dict):
                continue
            artifact_type = _normalized_string(artifact.get("type"))
            if artifact_type in _CODE_EXECUTION_ARTIFACT_TYPES:
                add_violation(
                    rule="initial_execution_artifact_overlay_not_allowed",
                    source=f"request.linked_artifacts[{index}]",
                    message=(
                        f"New task submission cannot attach execution artifact type {artifact_type!r} as initial proof. "
                        "Execution artifacts must be attached after real execution."
                    ),
                )

    task_status = _normalized_string(task_envelope.get("status"))
    if task_status is not None and task_status not in _ALLOWED_NEW_TASK_SUBMISSION_STATUSES:
        allowed = ", ".join(sorted(_ALLOWED_NEW_TASK_SUBMISSION_STATUSES))
        add_violation(
            rule="initial_task_status_invalid",
            source="request.task_envelope.status",
            message=(
                f"New task submission may only start in pre-assignment lifecycle states ({allowed}); "
                f"got {task_status!r}."
            ),
        )

    nested_assigned_executor = task_envelope.get("assigned_executor")
    if isinstance(nested_assigned_executor, dict):
        add_violation(
            rule="initial_nested_assigned_executor_not_allowed",
            source="request.task_envelope.assigned_executor",
            message="New task submission cannot persist assigned_executor before dispatcher-owned assignment has happened.",
        )

    timestamps = task_envelope.get("timestamps")
    if isinstance(timestamps, dict) and _normalized_string(timestamps.get("completed_at")) is not None:
        add_violation(
            rule="initial_completed_timestamp_not_allowed",
            source="request.task_envelope.timestamps.completed_at",
            message="New task submission cannot include completed_at; completion timestamps are assigned by lifecycle enforcement.",
        )

    artifacts = task_envelope.get("artifacts")
    if isinstance(artifacts, dict):
        artifact_items = artifacts.get("items")
        if isinstance(artifact_items, list):
            for index, artifact in enumerate(artifact_items):
                if not isinstance(artifact, dict):
                    continue
                artifact_type = _normalized_string(artifact.get("type"))
                if artifact_type in _CODE_EXECUTION_ARTIFACT_TYPES:
                    add_violation(
                        rule="initial_execution_artifact_not_allowed",
                        source=f"request.task_envelope.artifacts.items[{index}]",
                        message=(
                            f"New task submission cannot persist execution artifact type {artifact_type!r} as initial task truth."
                        ),
                    )

        completion_evidence = artifacts.get("completion_evidence")
        if isinstance(completion_evidence, dict):
            validated_artifact_ids = completion_evidence.get("validated_artifact_ids")
            if isinstance(validated_artifact_ids, list) and any(
                isinstance(item, str) and item.strip() for item in validated_artifact_ids
            ):
                add_violation(
                    rule="initial_validated_completion_evidence_not_allowed",
                    source="request.task_envelope.artifacts.completion_evidence.validated_artifact_ids",
                    message="New task submission cannot include validated completion evidence; validated artifact ids must be produced by later verification.",
                )
            if _normalized_string(completion_evidence.get("status")) == "satisfied":
                add_violation(
                    rule="initial_satisfied_completion_evidence_not_allowed",
                    source="request.task_envelope.artifacts.completion_evidence.status",
                    message="New task submission cannot mark completion evidence as satisfied before execution and verification.",
                )
            if _normalized_string(completion_evidence.get("validated_at")) is not None:
                add_violation(
                    rule="initial_validated_timestamp_not_allowed",
                    source="request.task_envelope.artifacts.completion_evidence.validated_at",
                    message="New task submission cannot include validated_at for completion evidence.",
                )
            validator = completion_evidence.get("validator")
            if validator is not None:
                add_violation(
                    rule="initial_validator_not_allowed",
                    source="request.task_envelope.artifacts.completion_evidence.validator",
                    message="New task submission cannot include a completion-evidence validator before verification has run.",
                )

    observability = task_envelope.get("observability")
    if isinstance(observability, dict):
        execution_metadata = observability.get("execution_metadata")
        if isinstance(execution_metadata, dict):
            advisory_claims = execution_metadata.get("advisory_completion_claims")
            if isinstance(advisory_claims, list) and any(isinstance(item, dict) for item in advisory_claims):
                add_violation(
                    rule="initial_completion_claim_history_not_allowed",
                    source="request.task_envelope.observability.execution_metadata.advisory_completion_claims",
                    message="New task submission cannot preload advisory completion claims.",
                )
            execution_attempts = execution_metadata.get("execution_attempts")
            if isinstance(execution_attempts, list) and any(isinstance(item, dict) for item in execution_attempts):
                add_violation(
                    rule="initial_execution_attempt_history_not_allowed",
                    source="request.task_envelope.observability.execution_metadata.execution_attempts",
                    message="New task submission cannot preload execution attempt history.",
                )

    reconciliation = task_envelope.get("reconciliation")
    if isinstance(reconciliation, dict):
        attempts = reconciliation.get("attempts")
        has_attempts = isinstance(attempts, list) and any(isinstance(item, dict) for item in attempts)
        has_reconciliation_state = any(
            reconciliation.get(field) not in (None, [], "not_required")
            for field in (
                "status",
                "active_failure_type",
                "last_attempt_id",
                "last_pr_url",
                "last_error",
                "resolved_at",
                "failed_at",
            )
        )
        if has_attempts or has_reconciliation_state:
            add_violation(
                rule="initial_reconciliation_history_not_allowed",
                source="request.task_envelope.reconciliation",
                message="New task submission cannot preload reconciliation history or resolved reconciliation state.",
            )

    return tuple(violations)


def _new_task_submission_contract_error_response(
    violations: tuple[dict[str, str], ...],
) -> tuple[int, dict[str, Any]]:
    message = violations[0]["message"] if violations else "New task submission violates the canonical submission contract."
    return HTTPStatus.BAD_REQUEST, {
        "error": message,
        "invalid_input": True,
        "submission_contract_violations": [deepcopy(item) for item in violations],
    }


def _parse_unresolved_conditions(request_payload: dict[str, Any]) -> tuple[str, ...]:
    return _optional_string_tuple(
        request_payload.get("unresolved_conditions"),
        field_name="unresolved_conditions",
    )


def _infer_clarification_need_type(condition: str) -> str:
    normalized = condition.strip().lower()
    if "ambig" in normalized or "unclear" in normalized or "multiple" in normalized or "conflict" in normalized:
        return "ambiguous"
    if "missing" in normalized or "unknown" in normalized or "not provided" in normalized:
        return "missing"
    return "incomplete"


def _infer_clarification_blocking_reason(unresolved_conditions: tuple[str, ...]) -> str:
    if any(_infer_clarification_need_type(condition) == "ambiguous" for condition in unresolved_conditions):
        return "ambiguous_information"
    return "missing_information"


def _clarification_transition_actor(from_status: str) -> str:
    if from_status in {"intake_ready", "executing", "blocked"}:
        return "clarification"
    if from_status == "assigned":
        return "dispatcher"
    if from_status == "reconciling":
        return "reconciliation"
    return "verification"


def _clarification_resume_target(
    task_envelope: dict[str, Any],
    *,
    preferred_status: str | None,
) -> str | None:
    if preferred_status in _CLARIFICATION_RESUME_TARGET_STATUSES:
        return preferred_status
    existing = task_envelope.get("clarification")
    if isinstance(existing, dict):
        existing_resume_target = existing.get("resume_target_status")
        if isinstance(existing_resume_target, str) and existing_resume_target in _CLARIFICATION_RESUME_TARGET_STATUSES:
            return existing_resume_target
    current_status = str(task_envelope.get("status") or "")
    if current_status in _CLARIFICATION_RESUME_TARGET_STATUSES:
        return current_status
    return "intake_ready"


def _with_submission_clarification(
    task_envelope: dict[str, Any],
    *,
    unresolved_conditions: tuple[str, ...],
    preferred_resume_target_status: str | None,
    requested_by: str,
) -> dict[str, Any]:
    if not unresolved_conditions:
        return task_envelope

    updated_task = deepcopy(task_envelope)
    blocking_reason = _infer_clarification_blocking_reason(unresolved_conditions)
    requested_at = _iso_now()
    resume_target_status = _clarification_resume_target(
        updated_task,
        preferred_status=preferred_resume_target_status,
    )
    current_status = str(updated_task.get("status") or "")
    if current_status != "blocked":
        transition = apply_task_transition(
            updated_task,
            to_status="blocked",
            actor=_clarification_transition_actor(current_status),
            reason=f"Clarification is required before work can continue: {unresolved_conditions[0]}",
            facts={"reason_provided": True},
        )
        updated_task = transition.task_envelope
        requested_at = transition.changed_at
    else:
        updated_task["timestamps"]["updated_at"] = requested_at

    existing_clarification = updated_task.get("clarification")
    clarification = dict(existing_clarification) if isinstance(existing_clarification, dict) else {}
    existing_required_inputs = [
        deepcopy(item)
        for item in clarification.get("required_inputs", [])
        if isinstance(item, dict)
    ]
    existing_descriptions = {
        str(item.get("description") or "").strip()
        for item in existing_required_inputs
        if str(item.get("description") or "").strip()
    }
    next_index = len(existing_required_inputs)
    for condition in unresolved_conditions:
        if condition in existing_descriptions:
            continue
        next_index += 1
        existing_required_inputs.append(
            {
                "id": f"clarification-input-{next_index}",
                "label": f"Required clarification {next_index}",
                "description": condition,
                "required": True,
                "need_type": _infer_clarification_need_type(condition),
                "status": "open",
                "value_summary": None,
            }
        )
        existing_descriptions.add(condition)

    clarification["status"] = "required"
    clarification["blocking_reason"] = blocking_reason
    clarification["resume_target_status"] = resume_target_status
    clarification["required_inputs"] = existing_required_inputs
    clarification["questions"] = [
        deepcopy(item)
        for item in clarification.get("questions", [])
        if isinstance(item, dict)
    ]
    clarification["responses"] = [
        deepcopy(item)
        for item in clarification.get("responses", [])
        if isinstance(item, dict)
    ]
    clarification["requested_at"] = clarification.get("requested_at") or requested_at
    clarification["resolved_at"] = None
    clarification["requested_by"] = clarification.get("requested_by") or requested_by
    clarification["resolution_summary"] = None
    updated_task["clarification"] = clarification
    return updated_task


def _resolve_submission_clarification_if_cleared(
    task_envelope: dict[str, Any],
    *,
    unresolved_conditions: tuple[str, ...],
    resolution_summary: str,
) -> dict[str, Any]:
    if unresolved_conditions:
        return task_envelope
    clarification = task_envelope.get("clarification")
    if not isinstance(clarification, dict):
        return task_envelope
    if clarification.get("status") not in {"required", "requested", "answered"}:
        return task_envelope

    resolved_task = deepcopy(task_envelope)
    updated_clarification = dict(clarification)
    updated_required_inputs = []
    for item in updated_clarification.get("required_inputs", []):
        if not isinstance(item, dict):
            continue
        updated_item = deepcopy(item)
        if updated_item.get("status") in {None, "", "open", "requested", "answered"}:
            updated_item["status"] = "provided"
        updated_required_inputs.append(updated_item)

    resolved_at = _iso_now()
    updated_clarification["status"] = "resolved"
    updated_clarification["required_inputs"] = updated_required_inputs
    updated_clarification["resolved_at"] = resolved_at
    updated_clarification["resolution_summary"] = resolution_summary
    resolved_task["clarification"] = updated_clarification
    resolved_task["timestamps"]["updated_at"] = resolved_at

    resume_target_status = _clarification_resume_target(resolved_task, preferred_status=None)
    current_status = str(resolved_task.get("status") or "")
    if current_status == "blocked" and resume_target_status in {"intake_ready", "planned", "dispatch_ready", "assigned"}:
        transition = apply_task_transition(
            resolved_task,
            to_status=resume_target_status,
            actor="clarification",
            reason="Clarification requirements were cleared and the task can resume.",
            facts={"clarification_resolved": True},
        )
        resolved_task = transition.task_envelope
        updated_clarification["resolved_at"] = transition.changed_at
        resolved_task["clarification"] = updated_clarification

    return resolved_task

_EXISTING_TASK_EVALUATE_OVERLAY_FIELDS: tuple[tuple[str, str], ...] = (
    ("task_status", "request.task_status"),
    ("assigned_executor", "request.assigned_executor"),
    ("linked_artifacts", "request.linked_artifacts"),
    ("completion_evidence", "request.completion_evidence"),
)

_EXISTING_TASK_REEVALUATE_FORBIDDEN_FIELDS: tuple[tuple[str, str], ...] = (
    ("task_envelope", "request.task_envelope"),
    ("task_status", "request.task_status"),
    ("assigned_executor", "request.assigned_executor"),
    ("linked_artifacts", "request.linked_artifacts"),
)

_COMPLETION_CLAIM_FORBIDDEN_FIELDS: tuple[tuple[str, str], ...] = (
    ("task_envelope", "request.task_envelope"),
    ("task_status", "request.task_status"),
    ("assigned_executor", "request.assigned_executor"),
    ("linked_artifacts", "request.linked_artifacts"),
)


def _existing_task_evaluate_overlay_violations(request_payload: dict[str, Any]) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    for field_name, source in _EXISTING_TASK_EVALUATE_OVERLAY_FIELDS:
        if request_payload.get(field_name) is None:
            continue
        violations.append(
            {
                "rule": "existing_task_overlay_not_allowed",
                "source": source,
                "message": "Existing-task /evaluate requests must not mutate stored task truth via submission overlays.",
            }
        )
    return violations


def _forbidden_existing_task_field_violations(
    request_payload: dict[str, Any],
    *,
    forbidden_fields: tuple[tuple[str, str], ...],
    rule: str,
    message: str,
) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    for field_name, source in forbidden_fields:
        if request_payload.get(field_name) is None:
            continue
        violations.append(
            {
                "rule": rule,
                "source": source,
                "message": message,
            }
        )
    return violations


def _reevaluation_execution_artifact_violations(request_payload: dict[str, Any]) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    if request_payload.get("runtime_facts") is None:
        return violations
    new_artifacts = _optional_object_list(
        request_payload.get("new_artifacts"),
        field_name="request.new_artifacts",
    )
    for index, artifact in enumerate(new_artifacts):
        artifact_type = _normalized_string(artifact.get("type"))
        if artifact_type not in _CODE_EXECUTION_ARTIFACT_TYPES:
            continue
        violations.append(
            {
                "rule": "reevaluation_execution_artifact_not_allowed",
                "source": f"request.new_artifacts[{index}]",
                "message": (
                    f"Existing-task reevaluation cannot combine runtime_facts with execution artifact type {artifact_type!r}. "
                    "Use POST /tasks/<task_id>/completion-claims for executor-reported repository proof."
                ),
            }
        )
    return violations


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
    _validate_submission_task_status_overlay(request_payload)
    unresolved_conditions = _parse_unresolved_conditions(request_payload)
    task_envelope = _require_mapping(request_payload.get("task_envelope"), field_name="task_envelope")
    _require_non_empty_string(task_envelope.get("id"), field_name="task_envelope.id")
    task_envelope = _sanitize_initial_task_artifact_trust(
        task_envelope,
        allow_trusted_verification_provenance=True,
    )
    task_envelope = _apply_submission_task_overlays(task_envelope, request_payload=request_payload)
    task_envelope = _prune_downgraded_validated_artifact_ids(task_envelope)
    requested_status = _optional_non_empty_string(request_payload.get("task_status"), field_name="task_status")
    task_envelope = _with_submission_clarification(
        task_envelope,
        unresolved_conditions=unresolved_conditions,
        preferred_resume_target_status=requested_status,
        requested_by="harness-intake",
    )

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
        unresolved_conditions=unresolved_conditions,
        review_reasons=_optional_string_tuple(request_payload.get("review_reasons"), field_name="review_reasons"),
        review_request=_parse_review_request(_optional_mapping(request_payload.get("review_request"), field_name="review_request")),
        review_decision=_parse_review_decision(_optional_mapping(request_payload.get("review_decision"), field_name="review_decision")),
    )


def _merge_artifacts(
    existing_task: dict[str, Any],
    *,
    new_artifacts: tuple[dict[str, Any], ...],
    sanitize_submitted_verification: bool = False,
    sanitize_non_execution_artifacts: bool = True,
    allow_trusted_verification_provenance: bool = False,
) -> dict[str, Any]:
    merged_task = deepcopy(existing_task)
    artifact_items = list(merged_task["artifacts"]["items"])
    existing_ids = {str(item.get("id")) for item in artifact_items if item.get("id") is not None}

    for artifact in new_artifacts:
        artifact_id = artifact.get("id")
        if artifact_id is not None and str(artifact_id) in existing_ids:
            raise ApiRequestError(f"new_artifacts contains duplicate artifact id {artifact_id!r}")
        sanitized_artifact = _sanitize_submitted_artifact(
            artifact,
            sanitize_submitted_verification=sanitize_submitted_verification,
            sanitize_non_execution_artifacts=sanitize_non_execution_artifacts,
            allow_trusted_verification_provenance=allow_trusted_verification_provenance,
        )
        artifact_items.append(sanitized_artifact)
        if artifact_id is not None:
            existing_ids.add(str(artifact_id))

    merged_task["artifacts"]["items"] = artifact_items
    return merged_task


def _sanitize_submitted_artifact(
    artifact: dict[str, Any],
    *,
    sanitize_submitted_verification: bool = False,
    sanitize_non_execution_artifacts: bool = True,
    allow_trusted_verification_provenance: bool = False,
) -> dict[str, Any]:
    sanitized_artifact = deepcopy(artifact)
    submitted_verification_status = _normalized_string(sanitized_artifact.get("verification_status"))
    artifact_type = _normalized_string(sanitized_artifact.get("type"))
    trusted_verification_provenance = (
        allow_trusted_verification_provenance
        and artifact_type in _CODE_EXECUTION_ARTIFACT_TYPES
        and _artifact_has_trusted_verification_provenance(sanitized_artifact)
    )
    if (
        sanitize_submitted_verification
        and submitted_verification_status == "verified"
        and not trusted_verification_provenance
        and (
            artifact_type == "pull_request"
            or artifact_type == "commit"
            or artifact_type == "branch"
            or artifact_type == "changed_file"
            or (sanitize_non_execution_artifacts and artifact_type not in _CODE_EXECUTION_ARTIFACT_TYPES)
        )
    ):
        metadata = sanitized_artifact.get("metadata") if isinstance(sanitized_artifact.get("metadata"), dict) else {}
        metadata = dict(metadata)
        metadata["submitted_verification_status"] = submitted_verification_status
        sanitized_artifact["metadata"] = metadata
        sanitized_artifact["verification_status"] = "unverified"
    return sanitized_artifact


def _artifact_has_trusted_verification_provenance(artifact: dict[str, Any]) -> bool:
    provenance = artifact.get("provenance")
    if not isinstance(provenance, dict):
        return False
    source_system = _normalized_string(provenance.get("source_system"))
    source_type = _normalized_string(provenance.get("source_type"))
    if source_system == "github" and source_type == "api":
        return True
    if source_system == "harness" and source_type in {"manual_review", "verification"}:
        return True
    return False


def _sanitize_initial_task_artifact_trust(
    task_envelope: dict[str, Any],
    *,
    allow_trusted_verification_provenance: bool = False,
) -> dict[str, Any]:
    artifacts = ((task_envelope.get("artifacts") or {}).get("items") or [])
    if not isinstance(artifacts, list) or not artifacts:
        return task_envelope

    sanitized = deepcopy(task_envelope)
    sanitized["artifacts"]["items"] = [
        _sanitize_submitted_artifact(
            artifact if isinstance(artifact, dict) else {},
            sanitize_submitted_verification=True,
            allow_trusted_verification_provenance=allow_trusted_verification_provenance,
        )
        for artifact in artifacts
        if isinstance(artifact, dict)
    ]
    return _prune_downgraded_validated_artifact_ids(sanitized)


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


def _completion_evidence_would_prematurely_satisfy(
    completion_evidence_update: dict[str, Any],
) -> bool:
    status = _normalized_string(completion_evidence_update.get("status"))
    if status == "satisfied":
        return True
    validated_artifact_ids = completion_evidence_update.get("validated_artifact_ids")
    if isinstance(validated_artifact_ids, list) and any(_normalized_string(item) for item in validated_artifact_ids):
        return True
    if _normalized_string(completion_evidence_update.get("validated_at")) is not None:
        return True
    validator = completion_evidence_update.get("validator")
    if isinstance(validator, dict) and validator:
        return True
    if _normalized_string(completion_evidence_update.get("validation_method")) is not None:
        return True
    return False


def _prune_unverified_validated_artifact_ids(task_envelope: dict[str, Any]) -> dict[str, Any]:
    completion_evidence = ((task_envelope.get("artifacts") or {}).get("completion_evidence") or {})
    if not isinstance(completion_evidence, dict):
        return task_envelope
    validated_artifact_ids = completion_evidence.get("validated_artifact_ids")
    if not isinstance(validated_artifact_ids, list):
        return task_envelope

    artifact_items = ((task_envelope.get("artifacts") or {}).get("items") or [])
    if not isinstance(artifact_items, list):
        return task_envelope

    verification_by_id = {
        str(item.get("id")): _normalized_string(item.get("verification_status"))
        for item in artifact_items
        if isinstance(item, dict) and item.get("id") is not None
    }
    filtered_ids = [
        artifact_id
        for artifact_id in validated_artifact_ids
        if verification_by_id.get(str(artifact_id)) == "verified"
    ]
    if filtered_ids == validated_artifact_ids:
        return task_envelope

    updated = deepcopy(task_envelope)
    updated_evidence = updated["artifacts"]["completion_evidence"]
    updated_evidence["validated_artifact_ids"] = filtered_ids
    if not filtered_ids:
        updated_evidence["status"] = "deferred"
        updated_evidence["validated_at"] = None
        updated_evidence["validator"] = None
        updated_evidence["validation_method"] = "deferred"
    return updated


def _prune_downgraded_validated_artifact_ids(task_envelope: dict[str, Any]) -> dict[str, Any]:
    completion_evidence = ((task_envelope.get("artifacts") or {}).get("completion_evidence") or {})
    if not isinstance(completion_evidence, dict):
        return task_envelope
    validated_artifact_ids = completion_evidence.get("validated_artifact_ids")
    if not isinstance(validated_artifact_ids, list):
        return task_envelope

    artifact_items = ((task_envelope.get("artifacts") or {}).get("items") or [])
    if not isinstance(artifact_items, list):
        return task_envelope

    downgraded_ids = {
        str(item.get("id"))
        for item in artifact_items
        if isinstance(item, dict)
        and item.get("id") is not None
        and _normalized_string(item.get("verification_status")) != "verified"
        and isinstance(item.get("metadata"), dict)
        and _normalized_string(item["metadata"].get("submitted_verification_status")) == "verified"
    }
    if not downgraded_ids:
        return task_envelope

    filtered_ids = [artifact_id for artifact_id in validated_artifact_ids if str(artifact_id) not in downgraded_ids]
    if filtered_ids == validated_artifact_ids:
        return task_envelope

    updated = deepcopy(task_envelope)
    updated_evidence = updated["artifacts"]["completion_evidence"]
    updated_evidence["validated_artifact_ids"] = filtered_ids
    if not filtered_ids:
        updated_evidence["status"] = "deferred"
        updated_evidence["validated_at"] = None
        updated_evidence["validator"] = None
        updated_evidence["validation_method"] = "deferred"
    return updated


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
    completion_claim: dict[str, Any],
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

    linked_attempt = _execution_attempt_for_completion_claim(merged_task, completion_claim=completion_claim)
    if linked_attempt is None:
        return merged_task
    linked_attempt_id = linked_attempt.get("attempt_id")
    if not isinstance(linked_attempt_id, str) or not linked_attempt_id.strip():
        return merged_task

    updated_attempts: list[Any] = [deepcopy(item) for item in existing_attempts]
    for attempt in reversed(updated_attempts):
        if not isinstance(attempt, dict):
            continue
        if attempt.get("attempt_id") != linked_attempt_id:
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
    unresolved_conditions = _parse_unresolved_conditions(request_payload)
    completion_claim = _parse_completion_claim(request_payload)
    merged_task = _with_advisory_completion_claim(task_envelope, claim=completion_claim)
    execution_attempt = _parse_execution_attempt(request_payload, completion_claim=completion_claim)
    if execution_attempt is not None:
        merged_task = _with_execution_attempt_record(merged_task, attempt=execution_attempt)

    new_artifacts = _optional_object_list(request_payload.get("new_artifacts"), field_name="new_artifacts")
    if new_artifacts:
        merged_task = _merge_artifacts(
            merged_task,
            new_artifacts=new_artifacts,
            sanitize_submitted_verification=True,
            allow_trusted_verification_provenance=False,
        )

    completion_evidence_update = _optional_mapping(
        request_payload.get("completion_evidence"),
        field_name="completion_evidence",
    )
    if completion_evidence_update is not None:
        merged_task = _merge_completion_evidence(
            merged_task,
            completion_evidence_update=completion_evidence_update,
        )
    merged_task = _prune_downgraded_validated_artifact_ids(merged_task)

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
    merged_task = _with_submission_clarification(
        merged_task,
        unresolved_conditions=unresolved_conditions,
        preferred_resume_target_status=None,
        requested_by="harness-runtime",
    )
    merged_task = _resolve_submission_clarification_if_cleared(
        merged_task,
        unresolved_conditions=unresolved_conditions,
        resolution_summary="Clarification requirements were cleared by the completion claim input.",
    )

    return HarnessEvaluationRequest(
        task_envelope=merged_task,
        external_facts=external_facts,
        claimed_completion=True,
        acceptance_criteria_satisfied=bool(request_payload.get("acceptance_criteria_satisfied", False)),
        runtime_facts=_parse_runtime_facts(_optional_mapping(request_payload.get("runtime_facts"), field_name="runtime_facts")),
        unresolved_conditions=unresolved_conditions,
        review_reasons=_optional_string_tuple(request_payload.get("review_reasons"), field_name="review_reasons"),
        review_request=review_request,
        review_decision=review_decision,
    )


def parse_reevaluation_request(task_envelope: dict[str, Any], payload: dict[str, Any]) -> HarnessEvaluationRequest:
    """Parse a reevaluation payload against an existing stored TaskEnvelope."""

    request_payload = _require_mapping(payload.get("request"), field_name="request")
    unresolved_conditions = _parse_unresolved_conditions(request_payload)
    merged_task = deepcopy(task_envelope)

    new_artifacts = _optional_object_list(request_payload.get("new_artifacts"), field_name="new_artifacts")
    if new_artifacts:
        merged_task = _merge_artifacts(
            merged_task,
            new_artifacts=new_artifacts,
            sanitize_submitted_verification=True,
            allow_trusted_verification_provenance=True,
        )

    completion_evidence_update = _optional_mapping(
        request_payload.get("completion_evidence"),
        field_name="completion_evidence",
    )
    claimed_completion = bool(request_payload.get("claimed_completion", False))
    if completion_evidence_update is not None and not claimed_completion:
        if _completion_evidence_would_prematurely_satisfy(completion_evidence_update):
            raise ApiRequestError(
                "completion_evidence that satisfies artifact proof requires claimed_completion=true on the same reevaluation request"
            )
    if completion_evidence_update is not None:
        merged_task = _merge_completion_evidence(
            merged_task,
            completion_evidence_update=completion_evidence_update,
        )
    merged_task = _prune_downgraded_validated_artifact_ids(merged_task)
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
    merged_task = _with_submission_clarification(
        merged_task,
        unresolved_conditions=unresolved_conditions,
        preferred_resume_target_status=None,
        requested_by="harness-reevaluation",
    )
    merged_task = _resolve_submission_clarification_if_cleared(
        merged_task,
        unresolved_conditions=unresolved_conditions,
        resolution_summary="Clarification requirements were cleared by the reevaluation input.",
    )

    return HarnessEvaluationRequest(
        task_envelope=merged_task,
        external_facts=external_facts,
        claimed_completion=claimed_completion,
        acceptance_criteria_satisfied=bool(request_payload.get("acceptance_criteria_satisfied", False)),
        runtime_facts=_parse_runtime_facts(_optional_mapping(request_payload.get("runtime_facts"), field_name="runtime_facts")),
        unresolved_conditions=unresolved_conditions,
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


def _dispatch_policy_decision(task_envelope: dict[str, Any], *, store: HarnessStore) -> tuple[bool, str]:
    task_status = str(task_envelope.get("status") or "")
    if task_status in _TERMINAL_TASK_STATUSES:
        return False, f"status={task_status} is terminal"
    if task_status == "blocked":
        if _has_unresolved_clarification_for_dispatch(task_envelope):
            return False, "status=blocked: clarification unresolved"
        return False, f"status={task_status} is blocked for dispatch"
    if task_status in _DISPATCH_BLOCKED_STATUSES:
        return False, f"status={task_status} is blocked for dispatch"
    if task_status not in _AUTO_DISPATCHABLE_STATUSES:
        return False, f"status={task_status} is not auto-dispatch eligible"
    dependency_block_reason = _dispatch_dependency_block_reason(task_envelope, store=store)
    if dependency_block_reason is not None:
        return False, dependency_block_reason

    execution_attempts = ((task_envelope.get("observability") or {}).get("execution_metadata") or {}).get("execution_attempts") or []
    if isinstance(execution_attempts, list) and any(isinstance(attempt, dict) for attempt in execution_attempts):
        return False, "execution attempt already recorded for current task state"

    return True, "eligible: non_terminal_non_blocked_no_existing_attempt"


def _has_unresolved_clarification_for_dispatch(task_envelope: dict[str, Any]) -> bool:
    clarification = task_envelope.get("clarification")
    if not isinstance(clarification, dict):
        return False

    if clarification.get("status") in {"required", "requested", "answered"}:
        return True

    required_inputs = clarification.get("required_inputs")
    if not isinstance(required_inputs, list):
        return False
    for item in required_inputs:
        if isinstance(item, dict) and item.get("required") and item.get("status") == "open":
            return True
    return False


def _dispatch_dependency_status_satisfies(current_status: str, required_status: str) -> bool:
    current_rank = _DISPATCH_DEPENDENCY_STATUS_ORDER.get(current_status)
    required_rank = _DISPATCH_DEPENDENCY_STATUS_ORDER.get(required_status)
    if current_rank is None or required_rank is None:
        return False
    return current_rank >= required_rank


def _dispatch_dependency_block_reason(task_envelope: dict[str, Any], *, store: HarnessStore) -> str | None:
    dependencies = task_envelope.get("dependencies")
    if not isinstance(dependencies, list):
        return None

    task_id = str(task_envelope.get("id") or "")
    for dependency in dependencies:
        if not isinstance(dependency, dict):
            continue
        if dependency.get("dependency_type") != "blocks":
            continue
        dependency_task_id = str(dependency.get("task_id") or "").strip()
        required_status = str(dependency.get("required_status") or "").strip()
        if not dependency_task_id or not required_status:
            continue
        if dependency_task_id == task_id:
            return f"Task {task_id!r} has an invalid self-dependency and cannot be dispatched"
        try:
            dependency_task = store.get_task(dependency_task_id)
        except TaskEnvelopeNotFoundError:
            return f"Task {task_id!r} is blocked on missing dependency {dependency_task_id!r}"
        dependency_status = str(dependency_task.get("status") or "")
        if not _dispatch_dependency_status_satisfies(dependency_status, required_status):
            return (
                f"Task {task_id!r} is blocked on dependency {dependency_task_id!r}; "
                f"requires status {required_status!r} but current status is {dependency_status!r}"
            )
    return None


def _manual_dispatch_allowed(task_envelope: dict[str, Any], *, store: HarnessStore) -> tuple[bool, str]:
    task_status = str(task_envelope.get("status") or "")
    if task_status in _TERMINAL_TASK_STATUSES:
        return False, f"Task {task_envelope.get('id')!r} is terminal and cannot be dispatched"
    if task_status in _DISPATCH_BLOCKED_STATUSES:
        return False, f"Task {task_envelope.get('id')!r} is currently blocked for dispatch"
    if task_status not in _MANUAL_DISPATCHABLE_STATUSES:
        return False, f"Task {task_envelope.get('id')!r} is not dispatch-ready; current status is {task_status!r}"
    if task_status == "blocked" and _has_unresolved_clarification_for_dispatch(task_envelope):
        return False, f"Task {task_envelope.get('id')!r} is blocked on clarification and cannot be dispatched"
    dependency_block_reason = _dispatch_dependency_block_reason(task_envelope, store=store)
    if dependency_block_reason is not None:
        return False, dependency_block_reason
    return True, ""


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

        review_request = enforcement_result.get("review_request")
        if isinstance(review_request, dict):
            requests.append(review_request)

        review_decision = enforcement_result.get("review_decision")
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


def _active_review_request(records: tuple[EvaluationRecord, ...]) -> dict[str, Any] | None:
    requests, decisions = _collect_review_activity(records)
    if not requests:
        return None
    if _review_status_from_activity(requests=requests, decisions=decisions) != "requested":
        return None
    return max(
        requests,
        key=lambda item: (
            _parse_iso_timestamp(item.get("requested_at")),
            str(item.get("review_request_id") or ""),
        ),
    )


def _validate_review_decision_against_active_gate(
    *,
    task_envelope: dict[str, Any],
    records: tuple[EvaluationRecord, ...],
    review_decision: ReviewDecisionResult | None,
) -> None:
    if review_decision is None:
        return

    active_request = _active_review_request(records)
    if active_request is None and task_envelope.get("status") == "in_review":
        raise ApiRequestError("review_decision requires a persisted active review request before manual resolution")
    if active_request is None:
        raise ApiRequestError("review_decision requires an active review gate")

    serialized_request = _to_jsonable(review_decision.request)
    if str(serialized_request.get("review_request_id") or "") != str(active_request.get("review_request_id") or ""):
        raise ApiRequestError("review_decision must resolve the active review request for this task")
    if serialized_request != active_request:
        raise ApiRequestError("review_decision.request must match the active review request exactly")


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


def _latest_advisory_completion_claim(task_envelope: dict[str, Any]) -> dict[str, Any] | None:
    claims = ((task_envelope.get("observability") or {}).get("execution_metadata") or {}).get(
        "advisory_completion_claims"
    ) or []
    if not isinstance(claims, list):
        return None
    return next((claim for claim in reversed(claims) if isinstance(claim, dict)), None)


def _advisory_completion_claim_by_id(task_envelope: dict[str, Any], claim_id: str | None) -> dict[str, Any] | None:
    if not isinstance(claim_id, str) or not claim_id.strip():
        return None
    normalized_claim_id = claim_id.strip()
    claims = ((task_envelope.get("observability") or {}).get("execution_metadata") or {}).get(
        "advisory_completion_claims"
    ) or []
    if not isinstance(claims, list):
        return None
    for claim in reversed(claims):
        if not isinstance(claim, dict):
            continue
        if claim.get("claim_id") == normalized_claim_id:
            return claim
    return None


def _latest_execution_attempt(task_envelope: dict[str, Any]) -> dict[str, Any] | None:
    attempts = ((task_envelope.get("observability") or {}).get("execution_metadata") or {}).get("execution_attempts") or []
    if not isinstance(attempts, list):
        return None
    return next((attempt for attempt in reversed(attempts) if isinstance(attempt, dict)), None)


def _execution_attempts(task_envelope: dict[str, Any]) -> list[dict[str, Any]]:
    attempts = ((task_envelope.get("observability") or {}).get("execution_metadata") or {}).get("execution_attempts") or []
    if not isinstance(attempts, list):
        return []
    return [attempt for attempt in attempts if isinstance(attempt, dict)]


def _execution_attempt_for_completion_claim(
    task_envelope: dict[str, Any],
    *,
    completion_claim: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    claim = completion_claim or _latest_advisory_completion_claim(task_envelope)
    if claim is None:
        return None

    attempts = ((task_envelope.get("observability") or {}).get("execution_metadata") or {}).get("execution_attempts") or []
    if not isinstance(attempts, list):
        return None

    claim_metadata = claim.get("metadata")
    attempt_id = None
    if isinstance(claim_metadata, dict):
        raw_attempt_id = claim_metadata.get("attempt_id")
        if isinstance(raw_attempt_id, str) and raw_attempt_id.strip():
            attempt_id = raw_attempt_id.strip()

    dict_attempts = [attempt for attempt in attempts if isinstance(attempt, dict)]
    if attempt_id is not None:
        matching_attempts = [attempt for attempt in reversed(dict_attempts) if attempt.get("attempt_id") == attempt_id]
        if len(matching_attempts) == 1:
            return matching_attempts[0]

    claim_id = claim.get("claim_id")
    if not isinstance(claim_id, str) or not claim_id.strip():
        return None

    matching_attempts = [attempt for attempt in reversed(dict_attempts) if attempt.get("completion_claim_id") == claim_id]
    return matching_attempts[0] if len(matching_attempts) == 1 else None


def _is_replayed_completion_claim(
    stored_task: dict[str, Any],
    *,
    completion_claim: dict[str, Any] | None,
    execution_attempt: dict[str, Any] | None,
) -> bool:
    if completion_claim is None or execution_attempt is None:
        return False

    claim_id = completion_claim.get("claim_id")
    if not isinstance(claim_id, str) or not claim_id.strip():
        return False
    attempt_id = execution_attempt.get("attempt_id")
    if not isinstance(attempt_id, str) or not attempt_id.strip():
        return False

    existing_claim = _advisory_completion_claim_by_id(stored_task, claim_id)
    if existing_claim is None:
        return False

    existing_attempt = _execution_attempt_for_completion_claim(stored_task, completion_claim=existing_claim)
    if existing_attempt is None:
        return False
    return existing_attempt.get("attempt_id") == attempt_id


def _is_successful_execution_attempt(attempt: dict[str, Any] | None) -> bool:
    if attempt is None:
        return False
    status = str(attempt.get("status") or "").strip().lower()
    return status in {"completed", "succeeded", "success"}


def _task_requires_code_execution(
    task_envelope: dict[str, Any],
    *,
    external_facts: CanonicalExternalFactBundle | None,
    attempt: dict[str, Any] | None,
) -> bool:
    completion_evidence = ((task_envelope.get("artifacts") or {}).get("completion_evidence") or {})
    required_artifact_types = {
        str(item).strip().lower()
        for item in completion_evidence.get("required_artifact_types") or []
        if isinstance(item, str) and item.strip()
    }
    if required_artifact_types.intersection(_CODE_EXECUTION_ARTIFACT_TYPES):
        return True

    if external_facts is not None and (
        external_facts.expected_code_context is not None or external_facts.github_facts is not None
    ):
        return True

    executor_type = _executor_hint_from_task(task_envelope)
    if executor_type in _CODE_EXECUTOR_TYPES and attempt is not None:
        return True
    return False


def _parse_github_repository_location(location: Any) -> tuple[str | None, str | None, str | None]:
    if not isinstance(location, str) or not location.strip():
        return None, None, None
    parsed = urlparse(location)
    host = (parsed.hostname or "").strip().lower()
    if host not in {"github.com", "www.github.com"}:
        return None, None, None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return None, None, None
    return "github.com", parts[0], parts[1]


def _parse_github_pull_request_location(location: Any) -> tuple[str, str, str, int] | None:
    if not isinstance(location, str) or not location.strip():
        return None
    parsed = urlparse(location)
    host = (parsed.hostname or "").strip().lower()
    if host not in {"github.com", "www.github.com"}:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 4 or parts[2] != "pull" or not parts[3].isdigit():
        return None
    return "github.com", parts[0], parts[1], int(parts[3])


def _normalized_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _record_context_value(
    observations: dict[str, dict[str, list[str]]],
    key: str,
    value: str | None,
    *,
    source: str,
) -> None:
    normalized = _normalized_string(value)
    if normalized is None:
        return
    observed = observations.setdefault(key, {})
    sources = observed.setdefault(normalized, [])
    if source not in sources:
        sources.append(source)


def _branch_contract_rule(
    branch_name: str | None,
    *,
    executor_type: str | None,
) -> dict[str, Any] | None:
    normalized_branch = _normalized_string(branch_name)
    if normalized_branch is None:
        return None
    branch_key = normalized_branch.casefold()
    if branch_key in _RESERVED_SHARED_BRANCH_NAMES:
        return {
            "rule": "reserved_shared_branch",
            "value": normalized_branch,
            "message": f"Branch {normalized_branch!r} is reserved/shared and cannot be used as delegated task completion evidence.",
        }
    if executor_type in _CODE_EXECUTOR_TYPES and not normalized_branch.startswith(_TASK_SCOPED_CODE_BRANCH_PREFIXES):
        return {
            "rule": "branch_not_task_scoped",
            "value": normalized_branch,
            "message": (
                f"Branch {normalized_branch!r} is not task-scoped delegated execution evidence. "
                f"Expected a branch under one of: {', '.join(_TASK_SCOPED_CODE_BRANCH_PREFIXES)}."
            ),
        }
    return None


def _pull_request_detail_from_artifact(
    artifact: dict[str, Any],
    *,
    source: str,
) -> dict[str, Any] | None:
    if artifact.get("type") != "pull_request":
        return None
    repository = artifact.get("repository") if isinstance(artifact.get("repository"), dict) else {}
    branch = artifact.get("branch") if isinstance(artifact.get("branch"), dict) else {}
    metadata = artifact.get("metadata") if isinstance(artifact.get("metadata"), dict) else {}
    repository_host = _normalized_string(repository.get("host"))
    repository_owner = _normalized_string(repository.get("owner"))
    repository_name = _normalized_string(repository.get("name"))
    return {
        "source": source,
        "url": _normalized_string(artifact.get("location")),
        "number": artifact.get("pull_request_number"),
        "state": _normalized_string(metadata.get("pull_request_state")),
        "merged": metadata.get("pull_request_merged"),
        "repository": (
            f"{repository_host}/{repository_owner}/{repository_name}"
            if repository_host and repository_owner and repository_name
            else None
        ),
        "branch_name": _normalized_string(branch.get("name")),
        "commit_sha": _normalized_string(branch.get("head_commit_sha")) or _normalized_string(artifact.get("commit_sha")),
    }


def _pull_request_detail_from_artifact_reference(
    artifact_reference: dict[str, Any],
    *,
    source: str,
) -> dict[str, Any] | None:
    metadata = artifact_reference.get("metadata") if isinstance(artifact_reference.get("metadata"), dict) else {}
    reference_type = _normalized_string(artifact_reference.get("artifact_type"))
    location = _normalized_string(artifact_reference.get("location"))
    explicit_url = _normalized_string(metadata.get("pull_request_url")) or _normalized_string(metadata.get("url"))
    url = location if _parse_github_pull_request_location(location) is not None else explicit_url
    if reference_type != "pull_request" and url is None:
        return None

    repository_host, repository_owner, repository_name = _parse_github_repository_location(url or location)
    return {
        "source": source,
        "url": url,
        "number": metadata.get("pull_request_number") or metadata.get("number"),
        "state": _normalized_string(metadata.get("pull_request_state")) or _normalized_string(metadata.get("state")),
        "merged": metadata.get("merged"),
        "repository": (
            f"{repository_host}/{repository_owner}/{repository_name}"
            if repository_host and repository_owner and repository_name
            else None
        ),
        "branch_name": (
            _normalized_string(metadata.get("branch_name"))
            or _normalized_string(metadata.get("head_branch"))
            or _normalized_string(metadata.get("branch"))
        ),
        "commit_sha": (
            _normalized_string(artifact_reference.get("commit_sha"))
            or _normalized_string(metadata.get("commit_sha"))
            or _normalized_string(metadata.get("head_commit_sha"))
            or _normalized_string(metadata.get("head_sha"))
            or _normalized_string(metadata.get("sha"))
        ),
    }


def _pull_request_detail_from_external_facts(github_facts: GitHubArtifactFacts) -> dict[str, Any] | None:
    if github_facts.pull_request is None:
        return None
    repository = None
    if github_facts.repository is not None:
        repository = (
            f"{github_facts.repository.host}/"
            f"{github_facts.repository.owner}/"
            f"{github_facts.repository.name}"
        )
    return {
        "source": "external_facts.github_facts.pull_request",
        "url": _normalized_string(github_facts.pull_request.url),
        "number": github_facts.pull_request.number,
        "state": _normalized_string(github_facts.pull_request.state),
        "merged": github_facts.pull_request.merged,
        "repository": repository,
        "branch_name": github_facts.branch.name if github_facts.branch is not None else None,
        "commit_sha": (
            github_facts.commit.sha
            if github_facts.commit is not None
            else (github_facts.branch.head_commit_sha if github_facts.branch is not None else None)
        ),
    }


def _collect_artifact_context_from_record(
    observations: dict[str, dict[str, list[str]]],
    artifact: dict[str, Any],
    *,
    source: str,
) -> None:
    artifact_type = _normalized_string(artifact.get("type"))
    if artifact_type not in _CODE_EXECUTION_ARTIFACT_TYPES:
        return

    repository = artifact.get("repository") if isinstance(artifact.get("repository"), dict) else {}
    branch = artifact.get("branch") if isinstance(artifact.get("branch"), dict) else {}

    host = _normalized_string(repository.get("host"))
    owner = _normalized_string(repository.get("owner"))
    name = _normalized_string(repository.get("name"))
    if host and owner and name:
        _record_context_value(observations, "repository", f"{host}/{owner}/{name}", source=source)

    _record_context_value(observations, "branch", branch.get("name"), source=source)
    _record_context_value(observations, "commit", artifact.get("commit_sha"), source=source)
    _record_context_value(observations, "commit", branch.get("head_commit_sha"), source=source)


def _collect_artifact_reference_context(
    observations: dict[str, dict[str, list[str]]],
    artifact_reference: dict[str, Any],
    *,
    source: str,
) -> None:
    artifact_type = _normalized_string(artifact_reference.get("artifact_type"))
    if artifact_type not in _CODE_EXECUTION_ARTIFACT_TYPES:
        return

    metadata = artifact_reference.get("metadata") if isinstance(artifact_reference.get("metadata"), dict) else {}

    repository_host = (
        _normalized_string(metadata.get("repository_host"))
        or _normalized_string(metadata.get("repo_host"))
    )
    repository_owner = (
        _normalized_string(metadata.get("repository_owner"))
        or _normalized_string(metadata.get("repo_owner"))
        or _normalized_string(metadata.get("owner"))
    )
    repository_name = (
        _normalized_string(metadata.get("repository_name"))
        or _normalized_string(metadata.get("repo_name"))
        or _normalized_string(metadata.get("name"))
    )

    if repository_host and repository_owner and repository_name:
        _record_context_value(
            observations,
            "repository",
            f"{repository_host}/{repository_owner}/{repository_name}",
            source=source,
        )
    else:
        parsed_host, parsed_owner, parsed_name = _parse_github_repository_location(artifact_reference.get("location"))
        if parsed_host and parsed_owner and parsed_name:
            _record_context_value(
                observations,
                "repository",
                f"{parsed_host}/{parsed_owner}/{parsed_name}",
                source=f"{source}:location",
            )

    _record_context_value(
        observations,
        "branch",
        _normalized_string(metadata.get("branch_name"))
        or _normalized_string(metadata.get("head_branch"))
        or _normalized_string(metadata.get("branch")),
        source=source,
    )
    _record_context_value(
        observations,
        "commit",
        _normalized_string(artifact_reference.get("commit_sha"))
        or _normalized_string(metadata.get("commit_sha"))
        or _normalized_string(metadata.get("head_commit_sha"))
        or _normalized_string(metadata.get("head_sha"))
        or _normalized_string(metadata.get("sha")),
        source=source,
    )


def _observations_snapshot(observations: dict[str, dict[str, list[str]]]) -> dict[str, list[dict[str, Any]]]:
    snapshot: dict[str, list[dict[str, Any]]] = {}
    for key, values in observations.items():
        snapshot[key] = [
            {"value": value, "sources": sorted(sources)}
            for value, sources in sorted(values.items())
        ]
    return snapshot


def _validate_execution_attempt(
    request: HarnessEvaluationRequest,
    *,
    request_payload: dict[str, Any],
) -> tuple[bool, dict[str, Any] | None]:
    attempt = _execution_attempt_for_completion_claim(request.task_envelope)
    if attempt is None or not _is_successful_execution_attempt(attempt):
        return True, None
    if not _task_requires_code_execution(
        request.task_envelope,
        external_facts=request.external_facts,
        attempt=attempt,
    ):
        return True, None

    observations: dict[str, dict[str, list[str]]] = {}
    pull_request_observations: list[dict[str, Any]] = []
    payload_artifacts = _optional_object_list(
        request_payload.get("new_artifacts"),
        field_name="request.new_artifacts",
    )
    for index, artifact in enumerate(payload_artifacts):
        _collect_artifact_context_from_record(observations, artifact, source=f"request.new_artifacts[{index}]")
        pull_request_detail = _pull_request_detail_from_artifact(
            artifact,
            source=f"request.new_artifacts[{index}]",
        )
        if pull_request_detail is not None:
            pull_request_observations.append(pull_request_detail)

    attempt_artifacts = attempt.get("artifact_references") if isinstance(attempt.get("artifact_references"), list) else []
    for index, artifact_reference in enumerate(attempt_artifacts):
        if not isinstance(artifact_reference, dict):
            continue
        _collect_artifact_reference_context(
            observations,
            artifact_reference,
            source=f"execution_attempt.artifact_references[{index}]",
        )
        pull_request_detail = _pull_request_detail_from_artifact_reference(
            artifact_reference,
            source=f"execution_attempt.artifact_references[{index}]",
        )
        if pull_request_detail is not None:
            pull_request_observations.append(pull_request_detail)

    if request.external_facts is not None:
        expected_context = request.external_facts.expected_code_context
        if expected_context is not None:
            if (
                _normalized_string(expected_context.repository_host)
                and _normalized_string(expected_context.repository_owner)
                and _normalized_string(expected_context.repository_name)
            ):
                _record_context_value(
                    observations,
                    "repository",
                    (
                        f"{expected_context.repository_host.strip()}/"
                        f"{expected_context.repository_owner.strip()}/"
                        f"{expected_context.repository_name.strip()}"
                    ),
                    source="external_facts.expected_code_context",
                )
            _record_context_value(
                observations,
                "branch",
                expected_context.branch_name,
                source="external_facts.expected_code_context",
            )
            _record_context_value(
                observations,
                "commit",
                None,
                source="external_facts.expected_code_context",
            )

        github_facts = request.external_facts.github_facts
        if github_facts is not None:
            if github_facts.repository is not None:
                _record_context_value(
                    observations,
                    "repository",
                    (
                        f"{github_facts.repository.host}/"
                        f"{github_facts.repository.owner}/"
                        f"{github_facts.repository.name}"
                    ),
                    source="external_facts.github_facts.repository",
                )
            if github_facts.branch is not None:
                _record_context_value(
                    observations,
                    "branch",
                    github_facts.branch.name,
                    source="external_facts.github_facts.branch",
                )
                _record_context_value(
                    observations,
                    "commit",
                    github_facts.branch.head_commit_sha,
                    source="external_facts.github_facts.branch",
                )
            if github_facts.commit is not None:
                _record_context_value(
                    observations,
                    "commit",
                    github_facts.commit.sha,
                    source="external_facts.github_facts.commit",
                )
            pull_request_detail = _pull_request_detail_from_external_facts(github_facts)
            if pull_request_detail is not None:
                pull_request_observations.append(pull_request_detail)

    attempts = _execution_attempts(request.task_envelope)
    used_task_artifact_fallback = False
    needs_repository = not observations.get("repository")
    needs_branch = not observations.get("branch")
    needs_commit = not observations.get("commit")
    if len(attempts) == 1 and (needs_repository or needs_branch or needs_commit):
        artifact_items = ((request.task_envelope.get("artifacts") or {}).get("items") or [])
        if isinstance(artifact_items, list):
            for index, artifact in enumerate(artifact_items):
                if not isinstance(artifact, dict):
                    continue
                _collect_artifact_context_from_record(
                    observations,
                    artifact,
                    source=f"task.artifacts[{index}]",
                )
                used_task_artifact_fallback = True
                pull_request_detail = _pull_request_detail_from_artifact(
                    artifact,
                    source=f"task.artifacts[{index}]",
                )
                if pull_request_detail is not None:
                    pull_request_observations.append(pull_request_detail)

    repository_values = observations.get("repository", {})
    branch_values = observations.get("branch", {})
    commit_values = observations.get("commit", {})
    executor_type = _executor_hint_from_task(request.task_envelope)
    existing_artifacts = ((request.task_envelope.get("artifacts") or {}).get("items") or [])
    has_pull_request_artifact = (
        any(isinstance(item, dict) and item.get("type") == "pull_request" for item in existing_artifacts)
        or any(isinstance(item, dict) and item.get("type") == "pull_request" for item in payload_artifacts)
    )
    has_valid_current_run_pr_artifact = task_has_valid_current_run_pull_request_artifact(
        request.task_envelope,
        external_facts=_to_jsonable(request.external_facts) if request.external_facts is not None else None,
    )
    commit_resolution_pending = bool(
        repository_values
        and branch_values
        and not commit_values
        and (not has_pull_request_artifact or has_valid_current_run_pr_artifact)
    )

    reasons: list[str] = []
    if not repository_values:
        reasons.append("Successful execution attempt is missing repository identity for the current run.")
    if not commit_values and not commit_resolution_pending:
        reasons.append("Successful execution attempt is missing commit SHA for the current run.")

    rule_failures: list[dict[str, Any]] = []
    if not branch_values:
        rule_failures.append(
            {
                "rule": "missing_branch_identity",
                "message": "Successful execution attempt is missing branch identity for the current run.",
            }
        )
    for branch_name in branch_values.keys():
        branch_rule = _branch_contract_rule(branch_name, executor_type=executor_type)
        if branch_rule is not None:
            rule_failures.append(branch_rule)

    current_repository = next(iter(repository_values.keys()), None) if len(repository_values) == 1 else None
    current_branch = next(iter(branch_values.keys()), None) if len(branch_values) == 1 else None
    current_commit = next(iter(commit_values.keys()), None) if len(commit_values) == 1 else None

    for detail in pull_request_observations:
        url = _normalized_string(detail.get("url"))
        parsed_pr = _parse_github_pull_request_location(url) if url is not None else None
        raw_number = detail.get("number")
        number = raw_number if isinstance(raw_number, int) else None
        state = _normalized_string(detail.get("state"))
        merged = detail.get("merged")
        repository = _normalized_string(detail.get("repository"))
        branch_name = _normalized_string(detail.get("branch_name"))
        commit_sha = _normalized_string(detail.get("commit_sha"))
        source = str(detail.get("source") or "pull_request")

        if url is None:
            rule_failures.append(
                {
                    "rule": "missing_pr_url",
                    "source": source,
                    "message": f"{source} is missing a GitHub pull request URL.",
                }
            )
            continue
        if parsed_pr is None:
            rule_failures.append(
                {
                    "rule": "invalid_pr_url",
                    "source": source,
                    "value": url,
                    "message": f"{source} does not contain a real numeric GitHub pull request URL.",
                }
            )
            continue
        _, _, _, parsed_number = parsed_pr
        if number is not None and number != parsed_number:
            rule_failures.append(
                {
                    "rule": "pull_request_number_mismatch",
                    "source": source,
                    "value": url,
                    "message": f"{source} reports PR number {number} but URL points to PR #{parsed_number}.",
                }
            )
        if state is None:
            rule_failures.append(
                {
                    "rule": "unknown_pull_request_state",
                    "source": source,
                    "value": url,
                    "message": f"{source} does not prove that the pull request is currently open.",
                }
            )
        elif state == "closed" or merged is True:
            rule_failures.append(
                {
                    "rule": "stale_pull_request_not_allowed",
                    "source": source,
                    "value": url,
                    "message": f"{source} references a closed or historical pull request and cannot prove the current run.",
                }
            )
        if current_repository is not None and repository is not None and repository != current_repository:
            rule_failures.append(
                {
                    "rule": "pull_request_repository_mismatch",
                    "source": source,
                    "value": url,
                    "message": f"{source} references a pull request from a different repository than the current run.",
                }
            )
        if current_branch is not None and branch_name is not None and branch_name != current_branch:
            rule_failures.append(
                {
                    "rule": "pull_request_branch_mismatch",
                    "source": source,
                    "value": url,
                    "message": f"{source} references a pull request branch that does not match the current run branch.",
                }
            )
        if current_commit is not None and commit_sha is not None and commit_sha != current_commit:
            rule_failures.append(
                {
                    "rule": "pull_request_commit_mismatch",
                    "source": source,
                    "value": url,
                    "message": f"{source} references a pull request commit that does not match the current run commit.",
                }
            )

    validation = {
        "validated_at": _iso_now(),
        "validated_by": "execution_validation",
        "policy": {
            "require_repository": True,
            "require_exact_branch": True,
            "require_commit": True,
            "allow_missing_pull_request": True,
            "task_artifact_fallback_requires_single_attempt": True,
            "allow_commit_resolution_via_reconciliation": True,
            "allow_missing_commit_artifact_with_verified_pull_request": True,
            "reject_reserved_shared_branch": True,
            "reject_non_numeric_pull_request_url": True,
            "reject_closed_or_historical_pull_request": True,
        },
        "context_observations": {
            **_observations_snapshot(observations),
            "used_task_artifact_fallback": used_task_artifact_fallback,
            "commit_resolution_pending": commit_resolution_pending,
            "has_valid_current_run_pull_request_artifact": has_valid_current_run_pr_artifact,
        },
        "pull_request_observations": deepcopy(pull_request_observations),
        "rule_failures": deepcopy(rule_failures),
    }
    if rule_failures:
        validation["status"] = "invalid"
        validation["failure_type"] = FailureType.CONTRACT_VIOLATION.value
        validation["retryable"] = False
        validation["reasons"] = [str(item["message"]) for item in rule_failures if isinstance(item.get("message"), str)]
        return False, validation
    if reasons:
        validation["status"] = "invalid"
        validation["failure_type"] = FailureType.INVALID_EXECUTION_ATTEMPT.value
        validation["retryable"] = True
        validation["reasons"] = reasons
        return False, validation

    validation["status"] = "valid"
    validation["retryable"] = False
    validation["reasons"] = []
    return True, validation


def _with_execution_attempt_validation(
    task_envelope: dict[str, Any],
    *,
    completion_claim: dict[str, Any] | None,
    validation: dict[str, Any],
) -> dict[str, Any]:
    linked_attempt = _execution_attempt_for_completion_claim(task_envelope, completion_claim=completion_claim)
    if linked_attempt is None:
        return task_envelope
    linked_attempt_id = _normalized_string(linked_attempt.get("attempt_id"))
    if linked_attempt_id is None:
        return task_envelope

    merged_task = deepcopy(task_envelope)
    execution_metadata = dict(merged_task["observability"]["execution_metadata"] or {})
    existing_attempts = execution_metadata.get("execution_attempts")
    if not isinstance(existing_attempts, list):
        raise ApiRequestError("observability.execution_metadata.execution_attempts must be an array")

    updated_attempts: list[Any] = [deepcopy(item) for item in existing_attempts]
    for attempt in reversed(updated_attempts):
        if not isinstance(attempt, dict):
            continue
        if attempt.get("attempt_id") != linked_attempt_id:
            continue
        metadata = dict(attempt.get("metadata") or {})
        metadata["attempt_validation"] = deepcopy(validation)
        attempt["metadata"] = metadata
        break
    else:
        return merged_task

    execution_metadata["execution_attempts"] = updated_attempts
    merged_task["observability"]["execution_metadata"] = execution_metadata
    merged_task["timestamps"]["updated_at"] = _iso_now()
    return merged_task


def _invalid_execution_attempt_count(task_envelope: dict[str, Any]) -> int:
    count = 0
    for attempt in _execution_attempts(task_envelope):
        metadata = attempt.get("metadata") if isinstance(attempt.get("metadata"), dict) else {}
        validation = metadata.get("attempt_validation") if isinstance(metadata.get("attempt_validation"), dict) else {}
        if validation.get("failure_type") == FailureType.INVALID_EXECUTION_ATTEMPT.value:
            count += 1
    return count


def _invalid_execution_retry_context(
    *,
    retry_number: int,
    max_retries: int,
    reason: str,
) -> dict[str, Any]:
    return {
        "attempt_number": retry_number,
        "max_retries": max_retries,
        "triggered_by_category": FailureType.INVALID_EXECUTION_ATTEMPT.value,
        "triggered_by_reason": reason,
        "is_final_attempt": retry_number >= max_retries,
        "scheduled_at": _iso_now(),
    }


def _execution_attempt_failure_result(
    *,
    task_envelope: dict[str, Any],
    failure_type: FailureType,
    reason: str,
    retryable: bool,
    target_status: str | None,
) -> HarnessEvaluationResult:
    failure = FailureClassification(
        failure_type=failure_type,
        source=FailureSource.EXECUTOR,
        reason=reason,
        terminal=not retryable,
        recoverable=retryable,
    )
    action = EnforcementAction.NO_OP if target_status is None else EnforcementAction.TRANSITION_APPLIED
    enforcement_result = EnforcementResult(
        action=action,
        task_envelope=task_envelope,
        evidence_result=None,
        reconciliation_result=None,
        verification_result=None,
        review_request=None,
        review_decision=None,
        transition_result=None,
        target_status=target_status,
        reasons=(reason,),
        failure_classification=failure,
        error=reason,
    )
    return HarnessEvaluationResult(
        action=action,
        target_status=target_status,
        task_envelope=task_envelope,
        enforcement_result=enforcement_result,
        accepted_completion=False,
        requires_review=False,
        invalid_input=False,
        failure_classification=failure,
        reasons=(reason,),
        error=reason,
    )


def _requires_missing_pr_reconciliation(request: HarnessEvaluationRequest) -> bool:
    if not request.claimed_completion:
        return False
    if task_has_valid_current_run_pull_request_artifact(
        request.task_envelope,
        external_facts=_to_jsonable(request.external_facts) if request.external_facts is not None else None,
    ):
        return False
    return _is_successful_execution_attempt(_execution_attempt_for_completion_claim(request.task_envelope))


def _requires_missing_commit_reconciliation(request: HarnessEvaluationRequest) -> bool:
    if not request.claimed_completion:
        return False
    if not _is_successful_execution_attempt(_execution_attempt_for_completion_claim(request.task_envelope)):
        return False
    external_facts = _to_jsonable(request.external_facts) if request.external_facts is not None else None
    if not task_has_valid_current_run_pull_request_artifact(
        request.task_envelope,
        external_facts=external_facts,
    ):
        return False
    if task_has_valid_current_run_commit_artifact(
        request.task_envelope,
        external_facts=external_facts,
    ):
        return False
    return True


def _completion_claim_reconciliation_failure_type(
    request: HarnessEvaluationRequest,
) -> ReconciliationFailureType | None:
    if _requires_missing_pr_reconciliation(request):
        return ReconciliationFailureType.MISSING_PR_AFTER_EXECUTION
    if _requires_missing_commit_reconciliation(request):
        return ReconciliationFailureType.MISSING_COMMIT_AFTER_EXECUTION
    return None


def _reconciliation_failure_response_shape(
    *,
    target_status: str,
) -> tuple[str, bool]:
    if target_status == "blocked":
        return "reconciliation_blocked", False
    if target_status == "failed":
        return "reconciliation_terminal_failed", False
    return "reconciliation_failed", True


def _with_reconciliation_resolved_code_context(
    request: HarnessEvaluationRequest,
    *,
    attempt: dict[str, Any] | None,
) -> HarnessEvaluationRequest:
    if not isinstance(attempt, dict):
        return request
    details = attempt.get("details")
    if not isinstance(details, dict):
        return request

    repository = details.get("repository")
    if not isinstance(repository, dict):
        return request

    repository_host = _normalized_string(repository.get("host")) or "github.com"
    repository_owner = _normalized_string(repository.get("owner"))
    repository_name = _normalized_string(repository.get("name"))
    branch_name = _normalized_string(details.get("branch_name"))
    base_branch = _normalized_string(details.get("base_branch"))
    commit_sha = _normalized_string(details.get("commit_sha"))
    if not repository_owner or not repository_name or not branch_name or not commit_sha:
        return request

    external_facts = _to_jsonable(request.external_facts) if request.external_facts is not None else {}
    if not isinstance(external_facts, dict):
        external_facts = {}
    expected_code_context = external_facts.get("expected_code_context")
    if not isinstance(expected_code_context, dict):
        expected_code_context = {}
    expected_code_context.update(
        {
            "repository_host": repository_host,
            "repository_owner": repository_owner,
            "repository_name": repository_name,
            "branch_name": branch_name,
            "base_branch": base_branch,
        }
    )
    external_facts["expected_code_context"] = expected_code_context

    github_facts = external_facts.get("github_facts")
    if not isinstance(github_facts, dict):
        github_facts = {}
    github_facts["repository"] = {
        "host": repository_host,
        "owner": repository_owner,
        "name": repository_name,
    }
    github_facts["branch"] = {
        "name": branch_name,
        "base_branch": base_branch,
        "head_commit_sha": commit_sha,
    }
    github_facts["commit"] = {"sha": commit_sha}
    external_facts["github_facts"] = github_facts

    return replace(
        request,
        external_facts=_parse_external_facts(external_facts),
    )


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

    def __init__(
        self,
        *,
        store: HarnessStore | None = None,
        reconciliation_registry: ReconciliationHandlerRegistry | None = None,
    ) -> None:
        self.store = store or build_harness_store()
        self.read_model_service = HarnessReadModelService(store=self.store)
        self.reconciliation_registry = reconciliation_registry or build_default_reconciliation_registry()

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

    def _run_automatic_dispatch(
        self,
        *,
        task_id: str,
        task_envelope: dict[str, Any],
        response_payload: dict[str, Any],
        reason: str,
        dispatch_trigger: str,
        dispatch_policy_stage: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        dispatch_status, dispatch_payload = self.dispatch_task(
            task_id,
            {
                "request": {
                    "executor": _executor_hint_from_task(task_envelope),
                    "execution_parameters": {
                        "dispatch_policy_reason": reason,
                        "dispatch_policy_stage": dispatch_policy_stage,
                    },
                    "dispatch_mode": "automatic",
                    "dispatch_trigger": dispatch_trigger,
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
                task_envelope = dispatch_payload["task_envelope"]
                response_payload["task_envelope"] = _to_jsonable(task_envelope)
            if isinstance(dispatch_payload.get("evaluation_record"), dict):
                response_payload["evaluation_record"] = deepcopy(dispatch_payload["evaluation_record"])
        else:
            response_payload["automatic_dispatch"]["error"] = dispatch_payload.get("error")
        return task_envelope, response_payload

    def _task_with_transition(
        self,
        task_envelope: dict[str, Any],
        *,
        to_status: str,
        reason: str,
        actor: str,
        facts: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if task_envelope.get("status") == to_status:
            return task_envelope
        transition = apply_task_transition(
            task_envelope,
            to_status=to_status,
            actor=actor,
            reason=reason,
            facts=facts,
        )
        return transition.task_envelope

    def _run_completion_claim_reconciliation(
        self,
        request: HarnessEvaluationRequest,
    ) -> tuple[HarnessEvaluationRequest | None, dict[str, Any] | None]:
        active_request = request
        handled_failure_types: list[ReconciliationFailureType] = []

        for _ in range(len(ReconciliationFailureType) + 1):
            failure_type = _completion_claim_reconciliation_failure_type(active_request)
            if failure_type is None:
                return active_request, None

            if failure_type in handled_failure_types:
                return None, {
                    "action": "reconciliation_failed",
                    "accepted_completion": False,
                    "requires_review": True,
                    "invalid_input": False,
                    "target_status": "in_review",
                    "error": f"Reconciliation failure type {failure_type.value!r} remained unresolved after handler execution.",
                    "reasons": [
                        f"Reconciliation failure type {failure_type.value!r} remained unresolved after handler execution."
                    ],
                    "reconciliation_attempt": None,
                    "task_envelope": _to_jsonable(active_request.task_envelope),
                }

            handled_failure_types.append(failure_type)

            if failure_type == ReconciliationFailureType.MISSING_COMMIT_AFTER_EXECUTION:
                reason = "Execution completed without a verified commit artifact; invoking reconciliation handler."
            else:
                reason = "Execution completed without a pull request artifact; invoking reconciliation handler."
            reconciling_task = ensure_reconciliation_state(active_request.task_envelope)
            reconciling_task = self._task_with_transition(
                reconciling_task,
                to_status="reconciling",
                reason=reason,
                actor="reconciliation",
            )

            try:
                handler_result = self.reconciliation_registry.handle(
                    failure_type,
                    task_envelope=reconciling_task,
                    external_facts=_to_jsonable(active_request.external_facts) if active_request.external_facts is not None else None,
                    started_at=_iso_now(),
                )
            except ReconciliationRuntimeError as error:
                target_status = (
                    "blocked"
                    if error.disposition == ReconciliationFailureDisposition.BLOCKED_RETRYABLE
                    else "failed"
                    if error.disposition == ReconciliationFailureDisposition.TERMINAL_FAILED
                    else "in_review"
                )
                action, requires_review = _reconciliation_failure_response_shape(target_status=target_status)
                reason_prefix = (
                    "Post-execution reconciliation blocked by retryable provider failure"
                    if target_status == "blocked"
                    else "Post-execution reconciliation established a terminal execution failure"
                    if target_status == "failed"
                    else "Post-execution reconciliation failed"
                )
                failed_task = self._task_with_transition(
                    reconciling_task,
                    to_status=target_status,
                    reason=f"{reason_prefix}: {error}",
                    actor="reconciliation",
                    facts={"terminal_failure": True} if target_status == "failed" else None,
                )
                failed_task = ensure_reconciliation_state(failed_task)
                failed_task["reconciliation"]["status"] = ReconciliationAttemptStatus.FAILED.value
                failed_task["reconciliation"]["active_failure_type"] = failure_type.value
                failed_task["reconciliation"]["last_error"] = str(error)
                failed_task["timestamps"]["updated_at"] = _iso_now()
                self.store.update_task(failed_task)
                return None, {
                    "action": action,
                    "accepted_completion": False,
                    "requires_review": requires_review,
                    "invalid_input": False,
                    "target_status": target_status,
                    "error": str(error),
                    "reasons": [str(error)],
                    "reconciliation_attempt": None,
                    "task_envelope": _to_jsonable(failed_task),
                }

            if handler_result.status == ReconciliationAttemptStatus.FAILED:
                action, requires_review = _reconciliation_failure_response_shape(target_status=handler_result.target_status)
                reason_prefix = (
                    "Post-execution reconciliation blocked by retryable provider failure"
                    if handler_result.target_status == "blocked"
                    else "Post-execution reconciliation established a terminal execution failure"
                    if handler_result.target_status == "failed"
                    else "Post-execution reconciliation failed"
                )
                failed_task = self._task_with_transition(
                    handler_result.task_envelope,
                    to_status=handler_result.target_status,
                    reason=f"{reason_prefix}: {handler_result.error}",
                    actor="reconciliation",
                    facts={"terminal_failure": True} if handler_result.target_status == "failed" else None,
                )
                self.store.update_task(failed_task)
                return None, {
                    "action": action,
                    "accepted_completion": False,
                    "requires_review": requires_review,
                    "invalid_input": False,
                    "target_status": handler_result.target_status,
                    "error": handler_result.error,
                    "reasons": [handler_result.error or "Reconciliation failed."],
                    "reconciliation_attempt": deepcopy(handler_result.attempt),
                    "task_envelope": _to_jsonable(failed_task),
                }

            active_request = replace(
                active_request,
                task_envelope=handler_result.task_envelope,
            )
            active_request = _with_reconciliation_resolved_code_context(
                active_request,
                attempt=handler_result.attempt,
            )

        return None, {
            "action": "reconciliation_failed",
            "accepted_completion": False,
            "requires_review": True,
            "invalid_input": False,
            "target_status": "in_review",
            "error": "Reconciliation exceeded the maximum chained handler depth.",
            "reasons": ["Reconciliation exceeded the maximum chained handler depth."],
            "reconciliation_attempt": None,
            "task_envelope": _to_jsonable(active_request.task_envelope),
        }

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

    def _handle_invalid_execution_attempt(
        self,
        *,
        task_id: str,
        request: HarnessEvaluationRequest,
        validation: dict[str, Any],
    ) -> tuple[int, dict[str, Any]]:
        completion_claim = _latest_advisory_completion_claim(request.task_envelope)
        validated_task = _with_execution_attempt_validation(
            request.task_envelope,
            completion_claim=completion_claim,
            validation=validation,
        )
        self.store.update_task(validated_task)

        reasons = tuple(str(item) for item in validation.get("reasons") or () if isinstance(item, str) and item.strip())
        reason = reasons[0] if reasons else "Execution attempt is invalid for completion handling."
        failure_type = FailureType(str(validation.get("failure_type") or FailureType.INVALID_EXECUTION_ATTEMPT.value))
        retryable_validation = bool(validation.get("retryable"))
        retry_budget = _invalid_execution_retry_budget()
        invalid_attempt_count = _invalid_execution_attempt_count(validated_task)
        retry_number = invalid_attempt_count

        executor = _executor_hint_from_task(validated_task)
        can_retry = (
            failure_type == FailureType.INVALID_EXECUTION_ATTEMPT
            and retryable_validation
            and executor in _CODE_EXECUTOR_TYPES
            and retry_number <= retry_budget
        )
        retry_context = (
            _invalid_execution_retry_context(
                retry_number=retry_number,
                max_retries=retry_budget,
                reason=reason,
            )
            if can_retry
            else None
        )

        evaluation_request = replace(
            request,
            task_envelope=validated_task,
            retry_context=deepcopy(retry_context) if retry_context is not None else None,
        )
        evaluation_result = _execution_attempt_failure_result(
            task_envelope=validated_task,
            failure_type=failure_type,
            reason=reason,
            retryable=can_retry,
            target_status=None,
        )
        evaluation_record = self.store.put_evaluation_record(request=evaluation_request, result=evaluation_result)

        if can_retry:
            dispatch_status, dispatch_payload = self.dispatch_task(
                task_id,
                {
                    "request": {
                        "executor": executor,
                        "dispatch_mode": "automatic",
                        "dispatch_trigger": "invalid_execution_attempt_retry",
                        "dispatch_reason": reason,
                        "execution_parameters": {
                            "prior_invalid_attempt_id": ((completion_claim or {}).get("metadata") or {}).get("attempt_id"),
                        },
                    }
                },
            )
            if isinstance(dispatch_payload, dict):
                dispatch_payload["invalid_execution_attempt"] = {
                    "status": "retry_scheduled",
                    "validation": deepcopy(validation),
                    "retry_context": deepcopy(retry_context),
                    "evaluation_record": _serialize_evaluation_record(evaluation_record),
                }
            return dispatch_status, dispatch_payload

        failed_reason = reason
        if executor not in _CODE_EXECUTOR_TYPES:
            failed_reason = (
                f"{reason} Automatic retry could not be scheduled because no compatible executor was assigned."
            )
        failed_task = self._task_with_transition(
            validated_task,
            to_status="failed",
            reason=failed_reason,
            actor="verification",
            facts={"terminal_failure": True, "reason_provided": True},
        )
        self.store.update_task(failed_task)
        failure_record = self.store.put_evaluation_record(
            request=replace(request, task_envelope=failed_task),
            result=_execution_attempt_failure_result(
                task_envelope=failed_task,
                failure_type=failure_type,
                reason=failed_reason,
                retryable=False,
                target_status="failed",
            ),
        )
        response_action = (
            "contract_violation_failed"
            if failure_type == FailureType.CONTRACT_VIOLATION
            else "invalid_execution_attempt_failed"
        )
        response_key = (
            "contract_violation"
            if failure_type == FailureType.CONTRACT_VIOLATION
            else "invalid_execution_attempt"
        )
        return HTTPStatus.OK, {
            "action": response_action,
            "accepted_completion": False,
            "requires_review": False,
            "invalid_input": False,
            "target_status": "failed",
            "error": failed_reason,
            "reasons": list(reasons) or [failed_reason],
            response_key: {
                "status": "failed",
                "validation": deepcopy(validation),
                "retry_budget": retry_budget,
                "invalid_attempt_count": invalid_attempt_count,
                "initial_evaluation_record": _serialize_evaluation_record(evaluation_record),
                "failure_evaluation_record": _serialize_evaluation_record(failure_record),
            },
            "task_envelope": _to_jsonable(failed_task),
            "evaluation_record": _serialize_evaluation_record(failure_record),
        }

    def submit(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        try:
            request = parse_evaluation_request(payload)
            request_payload = _require_mapping(payload.get("request"), field_name="request")
        except Exception as error:
            return HTTPStatus.BAD_REQUEST, {
                "error": str(error),
                "invalid_input": True,
            }

        contract_violations = _new_task_submission_contract_violations(request_payload)
        if contract_violations:
            return _new_task_submission_contract_error_response(contract_violations)

        task_id = str(request.task_envelope["id"])
        try:
            self.store.get_task(task_id)
            return HTTPStatus.CONFLICT, {
                "error": f"Task {task_id!r} already exists; use reevaluate for existing tasks",
                "duplicate_task_id": True,
            }
        except TaskEnvelopeNotFoundError:
            pass

        try:
            _validate_review_decision_against_active_gate(
                task_envelope=request.task_envelope,
                records=(),
                review_decision=request.review_decision,
            )
        except Exception as error:
            return HTTPStatus.BAD_REQUEST, {
                "error": str(error),
                "invalid_input": True,
            }

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

        should_dispatch, reason = _dispatch_policy_decision(stored_task, store=self.store)
        if should_dispatch:
            stored_task, response_payload = self._run_automatic_dispatch(
                task_id=task_id,
                task_envelope=stored_task,
                response_payload=response_payload,
                reason=reason,
                dispatch_trigger="automatic_policy_post_ingestion",
                dispatch_policy_stage="post_ingestion",
            )
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
        existing_records: tuple[EvaluationRecord, ...] = ()
        try:
            stored_task = self.store.get_task(task_id)
        except TaskEnvelopeNotFoundError:
            pass
        else:
            existing_records = self.store.list_evaluation_records(task_id)
            request_payload = _require_mapping(payload.get("request"), field_name="request")
            _validate_submission_task_status_overlay(request_payload)
            overlay_violations = _existing_task_evaluate_overlay_violations(request_payload)
            if overlay_violations:
                return HTTPStatus.BAD_REQUEST, {
                    "error": (
                        f"Existing task {task_id!r} cannot be mutated through POST /evaluate submission overlays; "
                        f"use POST /tasks/{task_id}/reevaluate instead."
                    ),
                    "invalid_input": True,
                    "violations": overlay_violations,
                    "reevaluate_path": f"/tasks/{task_id}/reevaluate",
                }
            request = replace(
                request,
                task_envelope=_with_submission_clarification(
                    _apply_submission_task_overlays(stored_task, request_payload=request_payload),
                    unresolved_conditions=request.unresolved_conditions,
                    preferred_resume_target_status=_optional_non_empty_string(
                        request_payload.get("task_status"),
                        field_name="task_status",
                    ),
                    requested_by="harness-reevaluation",
                ),
                review_is_active=_review_gate_is_active(stored_task, existing_records),
            )

        try:
            _validate_review_decision_against_active_gate(
                task_envelope=request.task_envelope,
                records=existing_records,
                review_decision=request.review_decision,
            )
        except Exception as error:
            return HTTPStatus.BAD_REQUEST, {
                "error": str(error),
                "invalid_input": True,
            }

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
        if (
            request.review_decision is not None
            and request.review_decision.follow_up_action == ReviewFollowUpAction.REDISPATCH
            and str(stored_task.get("status") or "") == "dispatch_ready"
        ):
            stored_task, response_payload = self._run_automatic_dispatch(
                task_id=task_id,
                task_envelope=stored_task,
                response_payload=response_payload,
                reason="Manual review authorized redispatch after the prior execution path was rejected.",
                dispatch_trigger="manual_review_authorize_redispatch",
                dispatch_policy_stage="post_review_reevaluation",
            )
        return status, response_payload

    def reevaluate(self, task_id: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        try:
            stored_task = self.store.get_task(task_id)
        except TaskEnvelopeNotFoundError:
            return HTTPStatus.NOT_FOUND, {"error": f"Task {task_id!r} was not found"}

        try:
            request_payload = _require_mapping(payload.get("request"), field_name="request")
            violations = _forbidden_existing_task_field_violations(
                request_payload,
                forbidden_fields=_EXISTING_TASK_REEVALUATE_FORBIDDEN_FIELDS,
                rule="existing_task_mutation_field_not_allowed",
                message="Existing-task reevaluation must use canonical reevaluation fields instead of submission-style mutation fields.",
            )
            if violations:
                return HTTPStatus.BAD_REQUEST, {
                    "error": (
                        f"Existing task {task_id!r} cannot be mutated through invalid reevaluation fields; "
                        f"use POST /tasks/{task_id}/reevaluate with canonical reevaluation inputs only."
                    ),
                    "invalid_input": True,
                    "violations": violations,
                }
            execution_artifact_violations = _reevaluation_execution_artifact_violations(request_payload)
            if execution_artifact_violations:
                return HTTPStatus.BAD_REQUEST, {
                    "error": (
                        f"Existing task {task_id!r} cannot combine runtime_facts with execution artifacts through reevaluation; "
                        f"use POST /tasks/{task_id}/completion-claims for executor-reported repository proof."
                    ),
                    "invalid_input": True,
                    "violations": execution_artifact_violations,
                    "completion_claim_path": f"/tasks/{task_id}/completion-claims",
                }
            request = parse_reevaluation_request(stored_task, payload)
        except Exception as error:
            return HTTPStatus.BAD_REQUEST, {
                "error": str(error),
                "invalid_input": True,
            }

        existing_records = self.store.list_evaluation_records(task_id)
        request = replace(
            request,
            review_is_active=_review_gate_is_active(
                stored_task,
                existing_records,
            ),
        )

        try:
            _validate_review_decision_against_active_gate(
                task_envelope=stored_task,
                records=existing_records,
                review_decision=request.review_decision,
            )
        except Exception as error:
            return HTTPStatus.BAD_REQUEST, {
                "error": str(error),
                "invalid_input": True,
            }

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
        if (
            request.review_decision is not None
            and request.review_decision.follow_up_action == ReviewFollowUpAction.REDISPATCH
            and str(stored_task.get("status") or "") == "dispatch_ready"
        ):
            stored_task, response_payload = self._run_automatic_dispatch(
                task_id=task_id,
                task_envelope=stored_task,
                response_payload=response_payload,
                reason="Manual review authorized redispatch after the prior execution path was rejected.",
                dispatch_trigger="manual_review_authorize_redispatch",
                dispatch_policy_stage="post_review_reevaluation",
            )
        elif str(stored_task.get("status") or "") == "dispatch_ready":
            should_dispatch, reason = _dispatch_policy_decision(stored_task, store=self.store)
            if should_dispatch:
                stored_task, response_payload = self._run_automatic_dispatch(
                    task_id=task_id,
                    task_envelope=stored_task,
                    response_payload=response_payload,
                    reason=reason,
                    dispatch_trigger="automatic_policy_post_reevaluation",
                    dispatch_policy_stage="post_reevaluation",
                )
            else:
                response_payload["automatic_dispatch"] = {
                    "attempted": False,
                    "dispatchable": False,
                    "reason": reason,
                }
        return status, response_payload

    def submit_completion_claim(self, task_id: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        try:
            stored_task = self.store.get_task(task_id)
        except TaskEnvelopeNotFoundError:
            return HTTPStatus.NOT_FOUND, {"error": f"Task {task_id!r} was not found"}

        try:
            request_payload = _require_mapping(payload.get("request"), field_name="request")
            violations = _forbidden_existing_task_field_violations(
                request_payload,
                forbidden_fields=_COMPLETION_CLAIM_FORBIDDEN_FIELDS,
                rule="completion_claim_mutation_field_not_allowed",
                message="Completion-claim requests must not carry submission-style mutation fields for stored tasks.",
            )
            if violations:
                return HTTPStatus.BAD_REQUEST, {
                    "error": (
                        f"Existing task {task_id!r} cannot be mutated through invalid completion-claim fields; "
                        f"use POST /tasks/{task_id}/completion-claims with completion-claim inputs only."
                    ),
                    "invalid_input": True,
                    "violations": violations,
                }
            request = parse_completion_claim_request(stored_task, payload)
        except Exception as error:
            return HTTPStatus.BAD_REQUEST, {
                "error": str(error),
                "invalid_input": True,
            }

        existing_records = self.store.list_evaluation_records(task_id)
        request = replace(
            request,
            review_is_active=_review_gate_is_active(
                stored_task,
                existing_records,
            ),
        )

        try:
            _validate_review_decision_against_active_gate(
                task_envelope=stored_task,
                records=existing_records,
                review_decision=request.review_decision,
            )
        except Exception as error:
            return HTTPStatus.BAD_REQUEST, {
                "error": str(error),
                "invalid_input": True,
            }

        latest_claim = _latest_advisory_completion_claim(request.task_envelope)
        replay_attempt = _latest_execution_attempt(request.task_envelope)
        if _is_replayed_completion_claim(
            stored_task,
            completion_claim=latest_claim,
            execution_attempt=replay_attempt,
        ):
            return HTTPStatus.OK, {
                "task_envelope": _to_jsonable(stored_task),
                "accepted_completion": stored_task.get("status") == "completed",
                "requires_review": _review_gate_is_active(stored_task, existing_records),
                "action": "completion_claim_replayed",
                "replayed_claim_id": latest_claim.get("claim_id"),
                "replayed_attempt_id": replay_attempt.get("attempt_id"),
            }

        attempt_valid, attempt_validation = _validate_execution_attempt(request, request_payload=request_payload)
        if not attempt_valid and attempt_validation is not None:
            return self._handle_invalid_execution_attempt(
                task_id=task_id,
                request=request,
                validation=attempt_validation,
            )
        if attempt_validation is not None:
            completion_claim = _latest_advisory_completion_claim(request.task_envelope)
            request = replace(
                request,
                task_envelope=_with_execution_attempt_validation(
                    request.task_envelope,
                    completion_claim=completion_claim,
                    validation=attempt_validation,
                ),
            )

        request, reconciliation_response = self._run_completion_claim_reconciliation(request)
        if reconciliation_response is not None:
            return HTTPStatus.OK, reconciliation_response
        if request is None:
            return HTTPStatus.OK, {"error": "Completion-claim reconciliation did not return a request"}
        request = replace(
            request,
            task_envelope=_prune_unverified_validated_artifact_ids(request.task_envelope),
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
        latest_claim = _latest_advisory_completion_claim(request.task_envelope)
        if latest_claim is not None:
            stored_task = self.store.update_task(
                _with_reevaluation_linked_execution_attempt(
                    stored_task,
                    completion_claim=latest_claim,
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

        dispatch_allowed, dispatch_reason = _manual_dispatch_allowed(stored_task, store=self.store)
        if not dispatch_allowed:
            return HTTPStatus.CONFLICT, {"error": dispatch_reason}

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
