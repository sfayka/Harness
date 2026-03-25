from __future__ import annotations

import json
import tempfile
import threading
import unittest
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from enum import Enum
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from modules.api import HarnessApiService, evaluate_http_payload, run_server
from modules.contracts.task_envelope_review import (
    ReviewOutcome,
    ReviewRequest,
    ReviewTrigger,
    ReviewerIdentity,
    resolve_review_request,
)
from modules.demo_cases import build_demo_request
from modules.store import FileBackedHarnessStore


def _to_jsonable(value):
    if is_dataclass(value):
        return {key: _to_jsonable(val) for key, val in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _to_jsonable(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    return value


def _request_payload(case_name: str) -> dict:
    return {"request": _to_jsonable(build_demo_request(case_name))}


def _linear_ingress_payload(case_name: str, *, task_id: str | None = None) -> dict:
    canonical_request = _request_payload(case_name)["request"]
    task = deepcopy(canonical_request["task_envelope"])
    external_facts = deepcopy(canonical_request.get("external_facts") or {})

    payload = {
        "issue": {
            "id": f"lin-{task['id']}",
            "identifier": f"HAR-{task['id']}",
            "title": task["title"],
            "description": task["description"],
        },
        "state": {
            "id": "workflow_in_progress" if case_name == "accepted_completion" else "workflow_completed",
            "name": "in_progress" if case_name == "accepted_completion" else "completed",
            "type": "started" if case_name == "accepted_completion" else "completed",
        },
        "project": {
            "id": "project-harness",
            "name": "Harness",
        },
        "task_reference": {
            "harness_task_id": task_id or task["id"],
            "external_ref": f"HAR-{task['id']}",
        },
        "labels": ["linear", "ingress"],
        "priority": task.get("priority", "normal"),
        "task_status": task["status"],
        "acceptance_criteria": deepcopy(task["acceptance_criteria"]),
        "linked_artifacts": deepcopy(task["artifacts"]["items"]),
        "completion_evidence": deepcopy(task["artifacts"]["completion_evidence"]),
        "external_facts": {},
        "claimed_completion": canonical_request.get("claimed_completion", False),
        "acceptance_criteria_satisfied": canonical_request.get("acceptance_criteria_satisfied", False),
        "runtime_facts": _to_jsonable(canonical_request.get("runtime_facts") or {}),
    }

    if task.get("assigned_executor") is not None:
        payload["assigned_executor"] = deepcopy(task["assigned_executor"])

    if external_facts.get("expected_code_context") is not None:
        payload["external_facts"]["expected_code_context"] = deepcopy(external_facts["expected_code_context"])
    if external_facts.get("github_facts") is not None:
        payload["external_facts"]["github_facts"] = deepcopy(external_facts["github_facts"])

    if case_name == "review_required":
        payload["state"] = {
            "id": "workflow_in_progress",
            "name": "in_progress",
            "type": "started",
        }

    return payload


def _review_note_artifact(artifact_id: str = "artifact-review-note-1") -> dict:
    return {
        "id": artifact_id,
        "type": "review_note",
        "title": "Manual evidence note",
        "description": "Evidence was manually confirmed during reevaluation.",
        "location": None,
        "content_type": "text/plain",
        "external_id": None,
        "commit_sha": None,
        "pull_request_number": None,
        "review_state": None,
        "provenance": {
            "source_system": "harness",
            "source_type": "manual_review",
            "source_id": f"review/{artifact_id}",
            "captured_by": "operator",
        },
        "verification_status": "verified",
        "repository": None,
        "branch": None,
        "changed_files": [],
        "external_refs": [],
        "captured_at": "2026-03-24T17:10:00Z",
        "metadata": {},
    }


def _progress_artifact(artifact_id: str = "artifact-progress-1") -> dict:
    return {
        "id": artifact_id,
        "type": "progress_artifact",
        "title": "Progress snapshot",
        "description": "Progress carried across reevaluations.",
        "location": None,
        "content_type": "application/json",
        "external_id": None,
        "commit_sha": None,
        "pull_request_number": None,
        "review_state": None,
        "provenance": {
            "source_system": "codex",
            "source_type": "executor_report",
            "source_id": f"progress/{artifact_id}",
            "captured_by": "harness-api",
        },
        "verification_status": "informational",
        "repository": None,
        "branch": None,
        "changed_files": [],
        "external_refs": [],
        "captured_at": "2026-03-24T17:15:00Z",
        "metadata": {
            "completed_items": "2",
            "remaining_items": "1",
        },
    }


def _handoff_artifact(artifact_id: str = "artifact-handoff-1") -> dict:
    return {
        "id": artifact_id,
        "type": "handoff_artifact",
        "title": "Session handoff",
        "description": "Resume from external reconciliation on the next session.",
        "location": None,
        "content_type": "application/json",
        "external_id": None,
        "commit_sha": None,
        "pull_request_number": None,
        "review_state": None,
        "provenance": {
            "source_system": "codex",
            "source_type": "executor_report",
            "source_id": f"handoff/{artifact_id}",
            "captured_by": "harness-api",
        },
        "verification_status": "informational",
        "repository": None,
        "branch": None,
        "changed_files": [],
        "external_refs": [],
        "captured_at": "2026-03-24T17:20:00Z",
        "metadata": {
            "from_session_id": "session-1",
            "resume_hint": "Continue verification after the next sync.",
        },
    }


def _review_decision_payload(task_id: str) -> dict:
    review_request = ReviewRequest(
        review_request_id="review-request-api-1",
        task_id=task_id,
        requested_at="2026-03-24T17:30:00Z",
        requested_by="verification",
        trigger=ReviewTrigger.VERIFICATION,
        summary="Manual confirmation is required before completion can be accepted.",
        presented_sections=("task_state", "evidence", "reconciliation"),
        allowed_outcomes=(ReviewOutcome.ACCEPT_COMPLETION,),
    )
    review_decision = resolve_review_request(
        review_request,
        review_id="review-api-1",
        reviewer=ReviewerIdentity(
            reviewer_id="operator-1",
            reviewer_name="Casey Reviewer",
            authority_role="operator",
        ),
        outcome=ReviewOutcome.ACCEPT_COMPLETION,
        reasoning="Additional evidence and manual review resolve the remaining uncertainty.",
    )
    return _to_jsonable(review_decision)


class HarnessApiPayloadTests(unittest.TestCase):
    def test_accepts_completion_payload(self) -> None:
        status, payload = evaluate_http_payload(_request_payload("accepted_completion"))

        self.assertEqual(status, 200)
        self.assertEqual(payload["action"], "transition_applied")
        self.assertEqual(payload["task_envelope"]["status"], "completed")

    def test_rejects_invalid_input_payload(self) -> None:
        status, payload = evaluate_http_payload(_request_payload("invalid_input"))

        self.assertEqual(status, 400)
        self.assertEqual(payload["action"], "invalid_input")
        self.assertTrue(payload["invalid_input"])


class HarnessApiServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.service = HarnessApiService(store=FileBackedHarnessStore(self.temp_dir.name))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_service_persists_evaluation_and_task_snapshot(self) -> None:
        status, payload = self.service.evaluate(_request_payload("accepted_completion"))

        self.assertEqual(status, 200)
        self.assertEqual(payload["task_envelope"]["status"], "completed")
        self.assertEqual(payload["evaluation_record"]["task_id"], payload["task_envelope"]["id"])

        task_status, task_payload = self.service.get_task(payload["task_envelope"]["id"])
        history_status, history_payload = self.service.get_evaluation_history(payload["task_envelope"]["id"])

        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["status"], "completed")
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 1)

    def test_service_rejects_invalid_input_without_persisting_state(self) -> None:
        task_id = _request_payload("invalid_input")["request"]["task_envelope"]["id"]

        status, payload = self.service.evaluate(_request_payload("invalid_input"))
        task_status, task_payload = self.service.get_task(task_id)
        history_status, history_payload = self.service.get_evaluation_history(task_id)

        self.assertEqual(status, 400)
        self.assertTrue(payload["invalid_input"])
        self.assertEqual(task_status, 404)
        self.assertIn("not found", task_payload["error"].lower())
        self.assertEqual(history_status, 404)
        self.assertIn("not found", history_payload["error"].lower())

    def test_service_lists_dashboard_tasks_from_read_model_surface(self) -> None:
        self.service.submit(_request_payload("accepted_completion"))
        self.service.submit(_request_payload("blocked_insufficient_evidence"))

        status, payload = self.service.list_tasks()

        self.assertEqual(status, 200)
        self.assertEqual(len(payload["tasks"]), 2)
        self.assertIn("verification_summary", payload["tasks"][0])
        self.assertIn("timeline", payload["tasks"][0])

    def test_service_submit_persists_new_task_and_initial_evaluation(self) -> None:
        status, payload = self.service.submit(_request_payload("accepted_completion"))

        task_status, task_payload = self.service.get_task(payload["task_envelope"]["id"])
        history_status, history_payload = self.service.get_evaluation_history(payload["task_envelope"]["id"])

        self.assertEqual(status, 200)
        self.assertEqual(payload["task_envelope"]["status"], "completed")
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["status"], "completed")
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 1)

    def test_service_submit_rejects_duplicate_task_id(self) -> None:
        initial_status, initial_payload = self.service.submit(_request_payload("accepted_completion"))
        duplicate_status, duplicate_payload = self.service.submit(_request_payload("accepted_completion"))
        history_status, history_payload = self.service.get_evaluation_history(initial_payload["task_envelope"]["id"])

        self.assertEqual(initial_status, 200)
        self.assertEqual(duplicate_status, 409)
        self.assertTrue(duplicate_payload["duplicate_task_id"])
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 1)

    def test_service_can_submit_linear_ingress_payload_via_canonical_submission_path(self) -> None:
        status, payload = self.service.submit_linear_ingress(_linear_ingress_payload("accepted_completion"))

        task_status, task_payload = self.service.get_task(payload["task_envelope"]["id"])
        history_status, history_payload = self.service.get_evaluation_history(payload["task_envelope"]["id"])

        self.assertEqual(status, 200)
        self.assertEqual(payload["task_envelope"]["origin"]["source_system"], "linear")
        self.assertEqual(payload["task_envelope"]["status"], "completed")
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["extensions"]["linear"]["issue_id"], f"lin-{payload['task_envelope']['id']}")
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 1)

    def test_service_can_reevaluate_existing_blocked_task_to_completed(self) -> None:
        initial_payload = _request_payload("blocked_insufficient_evidence")
        initial_status, initial_response = self.service.evaluate(initial_payload)

        reevaluation_payload = {
            "request": {
                "new_artifacts": [_review_note_artifact()],
                "completion_evidence": {
                    "validated_artifact_ids": [
                        "artifact-pr-1",
                        "artifact-commit-1",
                        "artifact-review-note-1",
                    ]
                },
                "external_facts": deepcopy(_request_payload("accepted_completion")["request"]["external_facts"]),
                "claimed_completion": True,
                "acceptance_criteria_satisfied": True,
                "runtime_facts": deepcopy(initial_payload["request"]["runtime_facts"]),
            }
        }
        reevaluation_status, reevaluation_response = self.service.reevaluate(
            initial_response["task_envelope"]["id"],
            reevaluation_payload,
        )

        self.assertEqual(initial_status, 200)
        self.assertEqual(initial_response["task_envelope"]["status"], "blocked")
        self.assertEqual(reevaluation_status, 200)
        self.assertEqual(reevaluation_response["task_envelope"]["status"], "completed")
        self.assertEqual(reevaluation_response["action"], "transition_applied")


class HarnessHttpApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.server = run_server(host="127.0.0.1", port=0, store_root=self.temp_dir.name)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp_dir.cleanup()

    def _get_json(self, path: str) -> tuple[int, dict]:
        try:
            with urlopen(self.base_url + path) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            try:
                return error.code, json.loads(error.read().decode("utf-8"))
            finally:
                error.close()

    def _post_json(self, path: str, payload: dict) -> tuple[int, dict]:
        request = Request(
            self.base_url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            try:
                return error.code, json.loads(error.read().decode("utf-8"))
            finally:
                error.close()

    def test_health_endpoint(self) -> None:
        status, payload = self._get_json("/health")

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")

    def test_api_submit_accepts_new_task_and_persists_initial_result(self) -> None:
        status, payload = self._post_json("/tasks", _request_payload("accepted_completion"))
        task_id = payload["task_envelope"]["id"]

        task_status, task_payload = self._get_json(f"/tasks/{task_id}")
        history_status, history_payload = self._get_json(f"/tasks/{task_id}/evaluations")

        self.assertEqual(status, 200)
        self.assertEqual(payload["task_envelope"]["status"], "completed")
        self.assertIn("evaluation_record", payload)
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["status"], "completed")
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 1)

    def test_api_lists_dashboard_tasks(self) -> None:
        self._post_json("/tasks", _request_payload("accepted_completion"))
        self._post_json("/tasks", _request_payload("blocked_insufficient_evidence"))

        status, payload = self._get_json("/tasks")

        self.assertEqual(status, 200)
        self.assertEqual(len(payload["tasks"]), 2)
        self.assertIn("task_id", payload["tasks"][0])
        self.assertIn("review_summary", payload["tasks"][0])

    def test_api_submit_can_persist_initial_blocked_result(self) -> None:
        status, payload = self._post_json("/tasks", _request_payload("blocked_insufficient_evidence"))
        task_id = payload["task_envelope"]["id"]

        task_status, task_payload = self._get_json(f"/tasks/{task_id}")

        self.assertEqual(status, 200)
        self.assertEqual(payload["target_status"], "blocked")
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["status"], "blocked")

    def test_api_submit_can_persist_initial_review_required_result(self) -> None:
        status, payload = self._post_json("/tasks", _request_payload("review_required"))
        task_id = payload["task_envelope"]["id"]

        task_status, task_payload = self._get_json(f"/tasks/{task_id}")
        history_status, history_payload = self._get_json(f"/tasks/{task_id}/evaluations")

        self.assertEqual(status, 200)
        self.assertEqual(payload["action"], "review_required")
        self.assertTrue(payload["requires_review"])
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["id"], task_id)
        self.assertEqual(history_status, 200)
        self.assertEqual(history_payload["evaluations"][0]["result"]["action"], "review_required")

    def test_api_submit_rejects_invalid_input_without_persisting_state(self) -> None:
        invalid_payload = _request_payload("invalid_input")
        task_id = invalid_payload["request"]["task_envelope"]["id"]

        status, payload = self._post_json("/tasks", invalid_payload)
        task_status, task_payload = self._get_json(f"/tasks/{task_id}")

        self.assertEqual(status, 400)
        self.assertTrue(payload["invalid_input"])
        self.assertEqual(task_status, 404)
        self.assertIn("not found", task_payload["error"].lower())

    def test_api_submit_rejects_duplicate_task_id_with_conflict(self) -> None:
        initial_status, initial_payload = self._post_json("/tasks", _request_payload("accepted_completion"))
        duplicate_status, duplicate_payload = self._post_json("/tasks", _request_payload("accepted_completion"))
        history_status, history_payload = self._get_json(
            f"/tasks/{initial_payload['task_envelope']['id']}/evaluations"
        )

        self.assertEqual(initial_status, 200)
        self.assertEqual(duplicate_status, 409)
        self.assertTrue(duplicate_payload["duplicate_task_id"])
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 1)

    def test_api_linear_ingress_can_submit_accepted_task(self) -> None:
        status, payload = self._post_json("/ingress/linear", _linear_ingress_payload("accepted_completion"))
        task_id = payload["task_envelope"]["id"]

        task_status, task_payload = self._get_json(f"/tasks/{task_id}")
        history_status, history_payload = self._get_json(f"/tasks/{task_id}/evaluations")

        self.assertEqual(status, 200)
        self.assertEqual(payload["task_envelope"]["origin"]["source_system"], "linear")
        self.assertEqual(payload["task_envelope"]["status"], "completed")
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["extensions"]["linear"]["issue_id"], f"lin-{task_id}")
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 1)

    def test_api_linear_ingress_can_submit_initial_blocked_task(self) -> None:
        status, payload = self._post_json("/ingress/linear", _linear_ingress_payload("blocked_insufficient_evidence"))
        task_id = payload["task_envelope"]["id"]

        task_status, task_payload = self._get_json(f"/tasks/{task_id}")

        self.assertEqual(status, 200)
        self.assertEqual(payload["target_status"], "blocked")
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["status"], "blocked")

    def test_api_linear_ingress_rejects_invalid_payload_without_persisting_state(self) -> None:
        payload = _linear_ingress_payload("accepted_completion", task_id="task-linear-invalid-1")
        del payload["issue"]["title"]

        status, response_payload = self._post_json("/ingress/linear", payload)
        task_status, task_payload = self._get_json("/tasks/task-linear-invalid-1")

        self.assertEqual(status, 400)
        self.assertTrue(response_payload["invalid_input"])
        self.assertEqual(task_status, 404)
        self.assertIn("not found", task_payload["error"].lower())

    def test_api_linear_ingress_rejects_duplicate_task_id_consistently(self) -> None:
        payload = _linear_ingress_payload("accepted_completion", task_id="task-linear-duplicate-1")

        initial_status, _ = self._post_json("/ingress/linear", payload)
        duplicate_status, duplicate_payload = self._post_json("/ingress/linear", payload)
        history_status, history_payload = self._get_json("/tasks/task-linear-duplicate-1/evaluations")

        self.assertEqual(initial_status, 200)
        self.assertEqual(duplicate_status, 409)
        self.assertTrue(duplicate_payload["duplicate_task_id"])
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 1)

    def test_api_persists_accepted_completion_and_exposes_history(self) -> None:
        status, payload = self._post_json("/evaluate", _request_payload("accepted_completion"))
        task_id = payload["task_envelope"]["id"]

        task_status, task_payload = self._get_json(f"/tasks/{task_id}")
        history_status, history_payload = self._get_json(f"/tasks/{task_id}/evaluations")

        self.assertEqual(status, 200)
        self.assertEqual(payload["action"], "transition_applied")
        self.assertEqual(payload["task_envelope"]["status"], "completed")
        self.assertIn("evaluation_record", payload)
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["status"], "completed")
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 1)
        self.assertEqual(history_payload["evaluations"][0]["result"]["task_envelope"]["status"], "completed")

    def test_api_persists_blocked_result(self) -> None:
        status, payload = self._post_json("/evaluate", _request_payload("blocked_insufficient_evidence"))
        task_id = payload["task_envelope"]["id"]

        task_status, task_payload = self._get_json(f"/tasks/{task_id}")
        history_status, history_payload = self._get_json(f"/tasks/{task_id}/evaluations")

        self.assertEqual(status, 200)
        self.assertEqual(payload["target_status"], "blocked")
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["status"], "blocked")
        self.assertEqual(history_status, 200)
        self.assertEqual(history_payload["evaluations"][0]["result"]["target_status"], "blocked")

    def test_api_persists_reconciliation_mismatch_result(self) -> None:
        status, payload = self._post_json("/evaluate", _request_payload("blocked_reconciliation_mismatch"))
        task_id = payload["task_envelope"]["id"]

        task_status, task_payload = self._get_json(f"/tasks/{task_id}")
        history_status, history_payload = self._get_json(f"/tasks/{task_id}/evaluations")

        self.assertEqual(status, 200)
        self.assertEqual(payload["target_status"], "blocked")
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["status"], "blocked")
        self.assertEqual(history_status, 200)
        self.assertEqual(
            history_payload["evaluations"][0]["result"]["enforcement_result"]["verification_result"]["outcome"],
            "external_mismatch",
        )

    def test_api_persists_review_required_result(self) -> None:
        status, payload = self._post_json("/evaluate", _request_payload("review_required"))
        task_id = payload["task_envelope"]["id"]

        task_status, task_payload = self._get_json(f"/tasks/{task_id}")
        history_status, history_payload = self._get_json(f"/tasks/{task_id}/evaluations")

        self.assertEqual(status, 200)
        self.assertEqual(payload["action"], "review_required")
        self.assertTrue(payload["requires_review"])
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["status"], payload["task_envelope"]["status"])
        self.assertEqual(history_status, 200)
        self.assertEqual(history_payload["evaluations"][0]["result"]["action"], "review_required")

    def test_api_rejects_invalid_input_without_persisting_state(self) -> None:
        invalid_payload = _request_payload("invalid_input")
        task_id = invalid_payload["request"]["task_envelope"]["id"]

        status, payload = self._post_json("/evaluate", invalid_payload)
        task_status, task_payload = self._get_json(f"/tasks/{task_id}")
        history_status, history_payload = self._get_json(f"/tasks/{task_id}/evaluations")

        self.assertEqual(status, 400)
        self.assertEqual(payload["action"], "invalid_input")
        self.assertTrue(payload["invalid_input"])
        self.assertEqual(task_status, 404)
        self.assertEqual(history_status, 404)
        self.assertIn("not found", task_payload["error"].lower())
        self.assertIn("not found", history_payload["error"].lower())

    def test_api_retrieves_append_only_evaluation_history(self) -> None:
        payload = _request_payload("accepted_completion")
        task_id = payload["request"]["task_envelope"]["id"]

        first_status, _ = self._post_json("/evaluate", payload)
        second_status, _ = self._post_json("/evaluate", payload)
        history_status, history_payload = self._get_json(f"/tasks/{task_id}/evaluations")

        self.assertEqual(first_status, 200)
        self.assertEqual(second_status, 200)
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 2)

    def test_api_returns_not_found_for_missing_task(self) -> None:
        task_status, task_payload = self._get_json("/tasks/missing-task")
        history_status, history_payload = self._get_json("/tasks/missing-task/evaluations")

        self.assertEqual(task_status, 404)
        self.assertEqual(history_status, 404)
        self.assertIn("not found", task_payload["error"].lower())
        self.assertIn("not found", history_payload["error"].lower())

    def test_api_rejects_malformed_json(self) -> None:
        request = Request(
            self.base_url + "/evaluate",
            data=b"{not-json",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request):
                self.fail("Expected malformed JSON request to be rejected")
        except HTTPError as error:
            self.assertEqual(error.code, 400)
            error.close()

    def test_api_sets_cors_headers_for_browser_clients(self) -> None:
        request = Request(self.base_url + "/tasks", method="OPTIONS")

        with urlopen(request) as response:
            self.assertEqual(response.status, 204)
            self.assertEqual(response.headers["Access-Control-Allow-Origin"], "*")
            self.assertIn("GET", response.headers["Access-Control-Allow-Methods"])

    def test_api_can_reevaluate_blocked_task_to_completed_when_new_evidence_arrives(self) -> None:
        initial_payload = _request_payload("blocked_insufficient_evidence")
        initial_status, initial_response = self._post_json("/evaluate", initial_payload)
        task_id = initial_response["task_envelope"]["id"]

        reevaluation_payload = {
            "request": {
                "new_artifacts": [_review_note_artifact()],
                "completion_evidence": {
                    "validated_artifact_ids": [
                        "artifact-pr-1",
                        "artifact-commit-1",
                        "artifact-review-note-1",
                    ]
                },
                "external_facts": deepcopy(_request_payload("accepted_completion")["request"]["external_facts"]),
                "claimed_completion": True,
                "acceptance_criteria_satisfied": True,
                "runtime_facts": deepcopy(initial_payload["request"]["runtime_facts"]),
            }
        }
        reevaluation_status, reevaluation_response = self._post_json(
            f"/tasks/{task_id}/reevaluate",
            reevaluation_payload,
        )
        history_status, history_payload = self._get_json(f"/tasks/{task_id}/evaluations")

        self.assertEqual(initial_status, 200)
        self.assertEqual(initial_response["task_envelope"]["status"], "blocked")
        self.assertEqual(reevaluation_status, 200)
        self.assertEqual(reevaluation_response["task_envelope"]["status"], "completed")
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 2)

    def test_api_can_reevaluate_completed_task_back_to_blocked_for_contradictory_facts(self) -> None:
        initial_payload = _request_payload("accepted_completion")
        initial_status, initial_response = self._post_json("/evaluate", initial_payload)
        task_id = initial_response["task_envelope"]["id"]

        reevaluation_payload = {
            "request": {
                "external_facts": deepcopy(_request_payload("blocked_reconciliation_mismatch")["request"]["external_facts"]),
                "claimed_completion": True,
                "acceptance_criteria_satisfied": True,
                "runtime_facts": deepcopy(initial_payload["request"]["runtime_facts"]),
            }
        }
        reevaluation_status, reevaluation_response = self._post_json(
            f"/tasks/{task_id}/reevaluate",
            reevaluation_payload,
        )

        self.assertEqual(initial_status, 200)
        self.assertEqual(initial_response["task_envelope"]["status"], "completed")
        self.assertEqual(reevaluation_status, 200)
        self.assertEqual(reevaluation_response["task_envelope"]["status"], "blocked")
        self.assertEqual(
            reevaluation_response["enforcement_result"]["verification_result"]["outcome"],
            "external_mismatch",
        )

    def test_api_can_reevaluate_review_required_path_to_completed_after_manual_review(self) -> None:
        accepted_payload = _request_payload("accepted_completion")
        initial_payload = {
            "request": deepcopy(accepted_payload["request"]),
        }
        initial_payload["request"]["task_envelope"]["status"] = "blocked"
        initial_payload["request"]["task_envelope"]["timestamps"]["completed_at"] = None
        initial_payload["request"]["review_request"] = deepcopy(_request_payload("review_required")["request"]["review_request"])
        initial_payload["request"]["review_request"]["task_id"] = initial_payload["request"]["task_envelope"]["id"]
        initial_payload["request"]["external_facts"] = deepcopy(_request_payload("review_required")["request"]["external_facts"])

        initial_status, initial_response = self._post_json("/evaluate", initial_payload)
        task_id = initial_response["task_envelope"]["id"]

        reevaluation_payload = {
            "request": {
                "review_decision": _review_decision_payload(task_id),
            }
        }
        reevaluation_status, reevaluation_response = self._post_json(
            f"/tasks/{task_id}/reevaluate",
            reevaluation_payload,
        )

        self.assertEqual(initial_status, 200)
        self.assertEqual(initial_response["action"], "review_required")
        self.assertEqual(reevaluation_status, 200)
        self.assertEqual(reevaluation_response["task_envelope"]["status"], "completed")
        self.assertIn(reevaluation_response["action"], {"transition_applied", "follow_up_authorized"})

    def test_api_can_reevaluate_pending_task_to_completed_when_external_facts_arrive(self) -> None:
        initial_payload = _request_payload("accepted_completion")
        initial_payload["request"]["external_facts"] = None

        initial_status, initial_response = self._post_json("/evaluate", initial_payload)
        task_id = initial_payload["request"]["task_envelope"]["id"]

        reevaluation_payload = {
            "request": {
                "external_facts": deepcopy(_request_payload("accepted_completion")["request"]["external_facts"]),
                "claimed_completion": True,
                "acceptance_criteria_satisfied": True,
                "runtime_facts": deepcopy(initial_payload["request"]["runtime_facts"]),
            }
        }
        reevaluation_status, reevaluation_response = self._post_json(
            f"/tasks/{task_id}/reevaluate",
            reevaluation_payload,
        )

        self.assertEqual(initial_status, 200)
        self.assertEqual(initial_response["task_envelope"]["status"], "blocked")
        self.assertEqual(
            initial_response["enforcement_result"]["verification_result"]["outcome"],
            "blocked_unresolved_conditions",
        )
        self.assertEqual(reevaluation_status, 200)
        self.assertEqual(reevaluation_response["task_envelope"]["status"], "completed")

    def test_api_appends_long_running_support_artifacts_across_reevaluations(self) -> None:
        initial_payload = _request_payload("blocked_insufficient_evidence")
        initial_status, initial_response = self._post_json("/evaluate", initial_payload)
        task_id = initial_response["task_envelope"]["id"]

        first_reevaluation_status, _ = self._post_json(
            f"/tasks/{task_id}/reevaluate",
            {
                "request": {
                    "new_artifacts": [_progress_artifact()],
                    "external_facts": deepcopy(initial_payload["request"]["external_facts"]),
                    "claimed_completion": True,
                    "acceptance_criteria_satisfied": True,
                    "runtime_facts": deepcopy(initial_payload["request"]["runtime_facts"]),
                }
            },
        )
        second_reevaluation_status, _ = self._post_json(
            f"/tasks/{task_id}/reevaluate",
            {
                "request": {
                    "new_artifacts": [_handoff_artifact()],
                    "external_facts": deepcopy(initial_payload["request"]["external_facts"]),
                    "claimed_completion": True,
                    "acceptance_criteria_satisfied": True,
                    "runtime_facts": deepcopy(initial_payload["request"]["runtime_facts"]),
                }
            },
        )
        task_status, task_payload = self._get_json(f"/tasks/{task_id}")
        history_status, history_payload = self._get_json(f"/tasks/{task_id}/evaluations")

        artifact_types = [item["type"] for item in task_payload["task"]["artifacts"]["items"]]

        self.assertEqual(initial_status, 200)
        self.assertEqual(first_reevaluation_status, 200)
        self.assertEqual(second_reevaluation_status, 200)
        self.assertEqual(task_status, 200)
        self.assertEqual(history_status, 200)
        self.assertIn("progress_artifact", artifact_types)
        self.assertIn("handoff_artifact", artifact_types)
        self.assertEqual(len(history_payload["evaluations"]), 3)
        self.assertEqual(
            task_payload["task"]["artifacts"]["completion_evidence"]["validated_artifact_ids"],
            ["artifact-pr-1", "artifact-commit-1"],
        )

    def test_api_rejects_invalid_reevaluation_without_corrupting_store_state(self) -> None:
        initial_payload = _request_payload("accepted_completion")
        initial_status, initial_response = self._post_json("/evaluate", initial_payload)
        task_id = initial_response["task_envelope"]["id"]
        before_task_status, before_task_payload = self._get_json(f"/tasks/{task_id}")
        before_history_status, before_history_payload = self._get_json(f"/tasks/{task_id}/evaluations")

        invalid_status, invalid_payload = self._post_json(
            f"/tasks/{task_id}/reevaluate",
            {
                "request": {
                    "new_artifacts": [_review_note_artifact("artifact-pr-1")],
                    "claimed_completion": True,
                    "acceptance_criteria_satisfied": True,
                }
            },
        )
        after_task_status, after_task_payload = self._get_json(f"/tasks/{task_id}")
        after_history_status, after_history_payload = self._get_json(f"/tasks/{task_id}/evaluations")

        self.assertEqual(initial_status, 200)
        self.assertEqual(before_task_status, 200)
        self.assertEqual(before_history_status, 200)
        self.assertEqual(invalid_status, 400)
        self.assertTrue(invalid_payload["invalid_input"])
        self.assertEqual(after_task_status, 200)
        self.assertEqual(after_history_status, 200)
        self.assertEqual(before_task_payload["task"], after_task_payload["task"])
        self.assertEqual(before_history_payload["evaluations"], after_history_payload["evaluations"])


if __name__ == "__main__":
    unittest.main()
