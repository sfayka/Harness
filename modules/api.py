"""Minimal HTTP API wrapper around the Harness evaluation entry point."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from enum import Enum
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

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


class ApiRequestError(ValueError):
    """Raised when the HTTP API receives malformed request payloads."""


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

    request_payload = _require_mapping(payload, field_name="request")
    task_envelope = _require_mapping(request_payload.get("task_envelope"), field_name="task_envelope")

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

    result = evaluate_task_case(request)
    status = HTTPStatus.BAD_REQUEST if result.invalid_input else HTTPStatus.OK
    return status, _to_jsonable(result)


class HarnessApiHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler exposing the Harness evaluation entry point."""

    server_version = "HarnessHTTP/0.1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def _write_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._write_json(HTTPStatus.OK, {"status": "ok"})
            return
        self._write_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/evaluate":
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length)
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except Exception as error:
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": f"Invalid JSON body: {error}"})
            return

        status, response_payload = evaluate_http_payload(payload)
        self._write_json(status, response_payload)


def run_server(*, host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    """Create and run the minimal HTTP API server."""

    server = ThreadingHTTPServer((host, port), HarnessApiHandler)
    return server


def build_parser() -> argparse.ArgumentParser:
    """Build the minimal HTTP API CLI parser."""

    parser = argparse.ArgumentParser(description="Run the minimal Harness HTTP API wrapper.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the minimal HTTP API server."""

    args = build_parser().parse_args(argv)
    server = run_server(host=args.host, port=args.port)
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
