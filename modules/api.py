"""Minimal HTTP API wrapper around the Harness evaluation entry point."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import unquote, urlparse

from modules.connectors import (
    LinearConnectorInputError,
    LinearIngressInputError,
    translate_linear_submission_payload,
)
from modules.contracts.task_envelope_end_to_end import CanonicalExternalFactBundle
from modules.contracts.task_envelope_external_facts import (
    BranchFact,
    ChangedFileFact,
    ChangedFilesSummary,
    CommitFact,
    GitHubArtifactFacts,
    LinearFacts,
    LinearProjectFact,
    LinearTaskReference,
    LinearWorkflowFact,
    PullRequestFact,
    RepositoryFact,
)
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


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _require_mapping(value: Any, *, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ApiRequestError(f"{field_name} must be an object")
    return value


def _optional_mapping(value: Any, *, field_name: str) -> dict[str, Any] | None:
    if value is None:
        return None
    return _require_mapping(value, field_name=field_name)


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


def _parse_repository(payload: dict[str, Any] | None) -> RepositoryFact | None:
    if payload is None:
        return None
    return RepositoryFact(**_require_mapping(payload, field_name="external_facts.github_facts.repository"))


def _parse_branch(payload: dict[str, Any] | None) -> BranchFact | None:
    if payload is None:
        return None
    return BranchFact(**_require_mapping(payload, field_name="external_facts.github_facts.branch"))


def _parse_commit(payload: dict[str, Any] | None) -> CommitFact | None:
    if payload is None:
        return None
    return CommitFact(**_require_mapping(payload, field_name="external_facts.github_facts.commit"))


def _parse_pull_request(payload: dict[str, Any] | None) -> PullRequestFact | None:
    if payload is None:
        return None
    return PullRequestFact(**_require_mapping(payload, field_name="external_facts.github_facts.pull_request"))


def _parse_changed_files(payload: dict[str, Any] | None) -> ChangedFilesSummary | None:
    if payload is None:
        return None
    changed_files_payload = _require_mapping(payload, field_name="external_facts.github_facts.changed_files")
    files = tuple(ChangedFileFact(**item) for item in changed_files_payload.get("files", []))
    return ChangedFilesSummary(
        files=files,
        matches_expected_scope=changed_files_payload.get("matches_expected_scope"),
    )


def _parse_github_facts(payload: dict[str, Any] | None) -> GitHubArtifactFacts | None:
    if payload is None:
        return None
    github_payload = _require_mapping(payload, field_name="external_facts.github_facts")
    return GitHubArtifactFacts(
        artifact_found=github_payload.get("artifact_found", True),
        repository=_parse_repository(_optional_mapping(github_payload.get("repository"), field_name="repository")),
        branch=_parse_branch(_optional_mapping(github_payload.get("branch"), field_name="branch")),
        commit=_parse_commit(_optional_mapping(github_payload.get("commit"), field_name="commit")),
        pull_request=_parse_pull_request(_optional_mapping(github_payload.get("pull_request"), field_name="pull_request")),
        changed_files=_parse_changed_files(_optional_mapping(github_payload.get("changed_files"), field_name="changed_files")),
        artifact_refs=tuple(),
        reasons=_optional_string_tuple(github_payload.get("reasons"), field_name="external_facts.github_facts.reasons"),
    )


def _parse_linear_facts(payload: dict[str, Any] | None) -> LinearFacts | None:
    if payload is None:
        return None
    linear_payload = _require_mapping(payload, field_name="external_facts.linear_facts")
    workflow_payload = _optional_mapping(linear_payload.get("workflow"), field_name="workflow")
    project_payload = _optional_mapping(linear_payload.get("project"), field_name="project")
    task_reference_payload = _optional_mapping(linear_payload.get("task_reference"), field_name="task_reference")
    return LinearFacts(
        record_found=linear_payload.get("record_found", True),
        issue_id=linear_payload.get("issue_id"),
        issue_key=linear_payload.get("issue_key"),
        state=linear_payload.get("state"),
        workflow=LinearWorkflowFact(**workflow_payload) if workflow_payload is not None else None,
        project=LinearProjectFact(**project_payload) if project_payload is not None else None,
        task_reference=LinearTaskReference(**task_reference_payload) if task_reference_payload is not None else None,
        reasons=_optional_string_tuple(linear_payload.get("reasons"), field_name="external_facts.linear_facts.reasons"),
    )


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


def parse_evaluation_request(payload: dict[str, Any]) -> HarnessEvaluationRequest:
    """Parse a canonical HTTP evaluation request into the public evaluator input."""

    request_payload = _require_mapping(payload.get("request"), field_name="request")
    task_envelope = _require_mapping(request_payload.get("task_envelope"), field_name="task_envelope")
    _require_non_empty_string(task_envelope.get("id"), field_name="task_envelope.id")

    return HarnessEvaluationRequest(
        task_envelope=task_envelope,
        external_facts=_parse_external_facts(_optional_mapping(request_payload.get("external_facts"), field_name="external_facts")),
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

    return HarnessEvaluationRequest(
        task_envelope=merged_task,
        external_facts=_parse_external_facts(_optional_mapping(request_payload.get("external_facts"), field_name="external_facts")),
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

        status, response_payload, result = _evaluate_request(request)
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

        record = self.store.put_evaluation_record(request=request, result=result)
        response_payload["task_envelope"] = _to_jsonable(stored_task)
        response_payload["evaluation_record"] = _serialize_evaluation_record(record)
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

    def evaluate(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        try:
            request = parse_evaluation_request(payload)
        except Exception as error:
            return HTTPStatus.BAD_REQUEST, {
                "error": str(error),
                "invalid_input": True,
            }

        status, response_payload, result = _evaluate_request(request)
        if result is None:
            return status, response_payload

        if result.invalid_input:
            return status, response_payload

        stored_task = self._upsert_task(result.task_envelope)
        record = self.store.put_evaluation_record(request=request, result=result)
        response_payload["task_envelope"] = _to_jsonable(stored_task)
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

        status, response_payload, result = _evaluate_request(request)
        if result is None:
            return status, response_payload

        if result.invalid_input:
            return status, response_payload

        stored_task = self.store.update_task(result.task_envelope)
        record = self.store.put_evaluation_record(request=request, result=result)
        response_payload["task_envelope"] = _to_jsonable(stored_task)
        response_payload["evaluation_record"] = _serialize_evaluation_record(record)
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

        if request_path not in {"/evaluate", "/tasks", "/ingress/linear"} and not (
            len(path_components) == 3 and path_components[0] == "tasks" and path_components[2] == "reevaluate"
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
        elif request_path == "/evaluate":
            status, response_payload = service.evaluate(payload)
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
