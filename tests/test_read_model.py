from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from modules.api import HarnessApiService, run_server
from modules.intake.task_envelope import create_task_envelope
from modules.demo_cases import build_demo_request
from modules.goal_to_work import GoalToWorkRequest, run_goal_to_work_flow
from modules.store import FileBackedHarnessStore, PostgresHarnessStore
from modules.contracts.task_envelope_review import (
    ReviewOutcome,
    ReviewRequest,
    ReviewTrigger,
    ReviewerIdentity,
    resolve_review_request,
)


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


POSTGRES_TEST_DATABASE_URL = os.environ.get("HARNESS_TEST_DATABASE_URL")
POSTGRES_SCHEMA_SQL = (
    Path(__file__).resolve().parents[1] / "sql" / "postgres" / "001_harness_store.sql"
).read_text(encoding="utf-8")


def _request_payload(case_name: str) -> dict:
    return {"request": _to_jsonable(build_demo_request(case_name))}


def _goal_request() -> GoalToWorkRequest:
    return GoalToWorkRequest(
        goal_id="goal-read-model-demo",
        title="Harness dashboard read model",
        product_goal="Show control-plane task state in a dashboard-friendly read surface.",
        target_user="Operators and reviewers inspecting AI-driven work.",
        problem_statement="Current state, evidence, verification, and review context should be easy to inspect.",
        scope=(
            {
                "id": "read-model",
                "title": "Task read model",
                "description": "Build a presentation-friendly detail view contract.",
                "category": "inspection",
            },
        ),
        constraints=(
            "Use canonical Harness ingress and persistence boundaries.",
            "Keep the result auditable and deterministic.",
        ),
        success_criteria=(
            "Operators can inspect current status and history for an ingested task.",
        ),
        priority="high",
    )


def _review_decision_payload(task_id: str) -> dict:
    review_request_payload = deepcopy(_request_payload("review_required")["request"]["review_request"])
    review_request_payload["task_id"] = task_id
    review_request = ReviewRequest(
        review_request_id=review_request_payload["review_request_id"],
        task_id=review_request_payload["task_id"],
        requested_at=review_request_payload["requested_at"],
        requested_by=review_request_payload["requested_by"],
        trigger=ReviewTrigger(review_request_payload["trigger"]),
        summary=review_request_payload["summary"],
        presented_sections=tuple(review_request_payload.get("presented_sections", [])),
        allowed_outcomes=tuple(ReviewOutcome(item) for item in review_request_payload.get("allowed_outcomes", [])),
        prior_review_ids=tuple(review_request_payload.get("prior_review_ids", [])),
        metadata=dict(review_request_payload.get("metadata", {})),
    )
    review_decision = resolve_review_request(
        review_request,
        review_id="review-read-model-1",
        reviewer=ReviewerIdentity(
            reviewer_id="operator-1",
            reviewer_name="Casey Reviewer",
            authority_role="operator",
        ),
        outcome=ReviewOutcome.ACCEPT_COMPLETION,
        reasoning="Manual review confirms the completion claim should be accepted.",
    )
    return _to_jsonable(review_decision)


class HarnessReadModelServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = FileBackedHarnessStore(self.temp_dir.name)
        self.service = HarnessApiService(store=self.store)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_builds_read_model_for_accepted_completion_task(self) -> None:
        submit_status, submit_payload = self.service.evaluate(_request_payload("accepted_completion"))

        status, payload = self.service.get_task_read_model(submit_payload["task_envelope"]["id"])

        self.assertEqual(submit_status, 200)
        self.assertEqual(status, 200)
        self.assertEqual(payload["task"]["current_status"], "completed")
        self.assertEqual(payload["task"]["verification_summary"]["outcome"], "accepted_completion")
        self.assertEqual(payload["task"]["reconciliation_summary"]["outcome"], "no_mismatch")
        self.assertEqual(payload["task"]["evidence_summary"]["artifact_count"], 2)
        self.assertTrue(payload["task"]["coordination_summary"]["linear"]["record_found"])
        self.assertEqual(payload["task"]["evaluation_summary"]["count"], 1)

    def test_builds_read_model_for_blocked_insufficient_evidence(self) -> None:
        submit_status, submit_payload = self.service.evaluate(_request_payload("blocked_insufficient_evidence"))

        status, payload = self.service.get_task_read_model(submit_payload["task_envelope"]["id"])

        self.assertEqual(submit_status, 200)
        self.assertEqual(status, 200)
        self.assertEqual(payload["task"]["current_status"], "blocked")
        self.assertEqual(payload["task"]["verification_summary"]["outcome"], "insufficient_evidence")
        self.assertEqual(payload["task"]["failure_summary"]["failure_type"], "evidence_insufficient")
        self.assertEqual(payload["task"]["failure_summary"]["failure_source"], "evaluation")

    def test_read_model_surfaces_review_required_as_non_terminal_triage_state(self) -> None:
        submit_status, submit_payload = self.service.evaluate(_request_payload("review_required"))

        status, payload = self.service.get_task_read_model(submit_payload["task_envelope"]["id"])

        self.assertEqual(submit_status, 200)
        self.assertEqual(status, 200)
        self.assertEqual(payload["task"]["current_status"], "in_review")
        self.assertEqual(payload["task"]["review_summary"]["status"], "requested")
        self.assertEqual(payload["task"]["failure_summary"]["failure_type"], "review_required")
        self.assertEqual(payload["task"]["failure_summary"]["state"], "review_required")
        self.assertFalse(payload["task"]["failure_summary"]["terminal"])
        self.assertFalse(payload["task"]["failure_summary"]["recoverable"])
        self.assertEqual(payload["task"]["execution_summary"]["failure_state"], "review_required")

    def test_read_model_clears_review_required_failure_projection_after_manual_resolution(self) -> None:
        submit_status, submit_payload = self.service.evaluate(_request_payload("review_required"))
        task_id = submit_payload["task_envelope"]["id"]

        reevaluate_status, _ = self.service.reevaluate(
            task_id,
            {"request": {"review_decision": _review_decision_payload(task_id)}},
        )
        status, payload = self.service.get_task_read_model(task_id)

        self.assertEqual(submit_status, 200)
        self.assertEqual(reevaluate_status, 200)
        self.assertEqual(status, 200)
        self.assertEqual(payload["task"]["current_status"], "completed")
        self.assertEqual(payload["task"]["review_summary"]["status"], "resolved")
        self.assertEqual(payload["task"]["failure_summary"]["failure_type"], "none")
        self.assertEqual(payload["task"]["failure_summary"]["state"], "clear")
        self.assertEqual(payload["task"]["execution_summary"]["failure_state"], "clear")
        self.assertFalse(payload["task"]["execution_summary"]["retry_eligible"])
        self.assertEqual(payload["task"]["verification_summary"]["outcome"], "review_resolved")
        self.assertFalse(payload["task"]["verification_summary"]["requires_review"])
        self.assertTrue(payload["task"]["verification_summary"]["accepted_completion"])
        self.assertEqual(payload["task"]["verification_summary"]["target_status"], "completed")
        self.assertEqual(payload["task"]["verification_summary"]["reconciliation_status"], "resolved")

    def test_read_model_and_timeline_expose_clarification_state(self) -> None:
        task_envelope = create_task_envelope(
            {
                "id": "task-read-model-clarification-1",
                "title": "Clarification state",
                "description": "Expose clarification through read-model and timeline surfaces.",
                "origin": {
                    "source_system": "manual",
                    "source_type": "manual",
                    "source_id": "task-read-model-clarification-1",
                },
                "acceptance_criteria": [
                    {
                        "id": "ac-1",
                        "description": "Clarification is captured canonically.",
                        "required": True,
                    }
                ],
            },
            now="2026-04-07T00:00:00Z",
        )

        submit_status, submit_payload = self.service.submit(
            {
                "request": {
                    "task_envelope": task_envelope,
                    "unresolved_conditions": ["Need target repository clarification before proceeding."],
                }
            }
        )
        task_id = submit_payload["task_envelope"]["id"]

        read_status, read_payload = self.service.get_task_read_model(task_id)
        timeline_status, timeline_payload = self.service.get_task_timeline(task_id)

        self.assertEqual(submit_status, 200)
        self.assertEqual(read_status, 200)
        self.assertEqual(read_payload["task"]["current_status"], "blocked")
        self.assertEqual(read_payload["task"]["clarification_summary"]["status"], "required")
        self.assertEqual(read_payload["task"]["clarification_summary"]["open_required_input_count"], 1)
        self.assertEqual(read_payload["task"]["clarification_summary"]["resume_target_status"], "intake_ready")
        self.assertEqual(timeline_status, 200)
        clarification_events = [
            event for event in timeline_payload["timeline"] if event["event_type"] == "clarification_required"
        ]
        self.assertTrue(clarification_events)
        self.assertEqual(
            clarification_events[-1]["details"]["required_inputs"][0]["description"],
            "Need target repository clarification before proceeding.",
        )

    def test_read_model_and_timeline_expose_resolved_clarification_state(self) -> None:
        submit_payload = {
            "request": {
                "task_envelope": create_task_envelope(
                    {
                        "id": "task-read-model-clarification-resolved-1",
                        "title": "Clarification resolved",
                        "description": "Expose clarification resolution through read-model and timeline.",
                        "origin": {
                            "source_system": "openclaw",
                            "source_type": "ingress_request",
                            "source_id": "task-read-model-clarification-resolved-1",
                        },
                        "acceptance_criteria": [
                            {
                                "id": "ac-1",
                                "description": "Task becomes routable after clarification is cleared.",
                                "required": True,
                            }
                        ],
                    },
                    now="2026-04-01T10:00:00Z",
                )
            }
        }

        submit_status, submit_response = self.service.submit(submit_payload)
        task_id = submit_response["task_envelope"]["id"]
        self.service.reevaluate(
            task_id,
            {"request": {"unresolved_conditions": ["Need repository clarification before planning can proceed."]}},
        )
        self.service.reevaluate(
            task_id,
            {"request": {"claimed_completion": False, "acceptance_criteria_satisfied": False}},
        )

        read_status, read_payload = self.service.get_task_read_model(task_id)
        timeline_status, timeline_payload = self.service.get_task_timeline(task_id)

        self.assertEqual(submit_status, 200)
        self.assertEqual(read_status, 200)
        self.assertEqual(timeline_status, 200)
        self.assertEqual(read_payload["task"]["clarification_summary"]["status"], "resolved")
        self.assertIsNotNone(read_payload["task"]["clarification_summary"]["resolved_at"])
        clarification_events = [
            event for event in timeline_payload["timeline"] if event["event_type"] == "clarification_resolved"
        ]
        self.assertEqual(len(clarification_events), 1)
        self.assertEqual(
            clarification_events[0]["details"]["status"],
            "resolved",
        )

    def test_timeline_shows_completed_to_blocked_rollback(self) -> None:
        initial_status, initial_payload = self.service.evaluate(_request_payload("accepted_completion"))
        task_id = initial_payload["task_envelope"]["id"]

        reevaluation_payload = {
            "request": {
                "external_facts": deepcopy(_request_payload("blocked_reconciliation_mismatch")["request"]["external_facts"]),
                "claimed_completion": True,
                "acceptance_criteria_satisfied": True,
                "runtime_facts": deepcopy(_request_payload("accepted_completion")["request"]["runtime_facts"]),
            }
        }
        reevaluation_status, _ = self.service.reevaluate(task_id, reevaluation_payload)
        status, payload = self.service.get_task_timeline(task_id)

        transition_targets = [
            event["details"]["to_status"]
            for event in payload["timeline"]
            if event["event_type"] == "status_transition"
        ]

        self.assertEqual(initial_status, 200)
        self.assertEqual(reevaluation_status, 200)
        self.assertEqual(status, 200)
        self.assertEqual(transition_targets[-2:], ["completed", "blocked"])
        self.assertTrue(any(event["event_type"] == "linear_linkage_recorded" for event in payload["timeline"]))
        self.assertTrue(any(event["event_type"] == "failure_recorded" for event in payload["timeline"]))

    def test_review_summary_shows_request_then_resolution(self) -> None:
        accepted_payload = _request_payload("accepted_completion")
        initial_payload = {"request": deepcopy(accepted_payload["request"])}
        initial_payload["request"]["task_envelope"]["status"] = "blocked"
        initial_payload["request"]["task_envelope"]["timestamps"]["completed_at"] = None
        initial_payload["request"]["review_request"] = deepcopy(_request_payload("review_required")["request"]["review_request"])
        initial_payload["request"]["review_request"]["task_id"] = initial_payload["request"]["task_envelope"]["id"]
        initial_payload["request"]["external_facts"] = deepcopy(_request_payload("review_required")["request"]["external_facts"])

        initial_status, initial_response = self.service.evaluate(initial_payload)
        task_id = initial_response["task_envelope"]["id"]
        self.assertEqual(initial_response["task_envelope"]["status"], "in_review")

        reevaluation_status, _ = self.service.reevaluate(
            task_id,
            {"request": {"review_decision": _review_decision_payload(task_id)}},
        )
        read_status, read_payload = self.service.get_task_read_model(task_id)

        self.assertEqual(initial_status, 200)
        self.assertEqual(reevaluation_status, 200)
        self.assertEqual(read_status, 200)
        self.assertEqual(read_payload["task"]["current_status"], "completed")
        self.assertEqual(read_payload["task"]["review_summary"]["status"], "resolved")
        self.assertEqual(read_payload["task"]["review_summary"]["request_count"], 1)
        self.assertEqual(read_payload["task"]["review_summary"]["decision_count"], 1)

    def test_read_model_keeps_review_requested_tasks_in_review_until_manual_resolution(self) -> None:
        initial_status, initial_response = self.service.evaluate(_request_payload("review_required"))
        task_id = initial_response["task_envelope"]["id"]

        reevaluation_status, reevaluation_response = self.service.reevaluate(
            task_id,
            {
                "request": {
                    "external_facts": deepcopy(_request_payload("accepted_completion")["request"]["external_facts"]),
                    "claimed_completion": True,
                    "acceptance_criteria_satisfied": True,
                    "runtime_facts": deepcopy(_request_payload("accepted_completion")["request"]["runtime_facts"]),
                }
            },
        )
        read_status, read_payload = self.service.get_task_read_model(task_id)

        self.assertEqual(initial_status, 200)
        self.assertEqual(initial_response["task_envelope"]["status"], "in_review")
        self.assertEqual(reevaluation_status, 200)
        self.assertEqual(reevaluation_response["task_envelope"]["status"], "in_review")
        self.assertEqual(read_status, 200)
        self.assertEqual(read_payload["task"]["current_status"], "in_review")
        self.assertEqual(read_payload["task"]["review_summary"]["status"], "requested")
        self.assertEqual(read_payload["task"]["review_summary"]["request_count"], 1)
        self.assertEqual(read_payload["task"]["review_summary"]["decision_count"], 0)

    def test_read_model_ignores_caller_supplied_review_request_without_review_required_outcome(self) -> None:
        task_envelope = create_task_envelope(
            {
                "id": "task-read-model-ghost-review-1",
                "title": "Ignore caller review request",
                "description": "Caller-supplied review_request should not create a canonical review gate.",
                "origin": {
                    "source_system": "manual",
                    "source_type": "manual",
                    "source_id": "task-read-model-ghost-review-1",
                },
                "acceptance_criteria": [
                    {
                        "id": "ac-1",
                        "description": "Task remains routable unless enforcement explicitly requests review.",
                        "required": True,
                    }
                ],
            },
            now="2026-04-07T10:00:00Z",
        )
        submit_status, submit_response = self.service.submit({"request": {"task_envelope": task_envelope}})
        task_id = submit_response["task_envelope"]["id"]

        reevaluate_status, reevaluate_response = self.service.reevaluate(
            task_id,
            {
                "request": {
                    "review_request": {
                        **deepcopy(_request_payload("review_required")["request"]["review_request"]),
                        "task_id": task_id,
                    },
                    "external_facts": deepcopy(_request_payload("accepted_completion")["request"]["external_facts"]),
                    "runtime_facts": deepcopy(_request_payload("accepted_completion")["request"]["runtime_facts"]),
                }
            },
        )
        read_status, read_payload = self.service.get_task_read_model(task_id)
        timeline_status, timeline_payload = self.service.get_task_timeline(task_id)

        self.assertEqual(submit_status, 200)
        self.assertEqual(reevaluate_status, 200)
        self.assertNotEqual(reevaluate_response["task_envelope"]["status"], "in_review")
        self.assertEqual(read_status, 200)
        self.assertEqual(read_payload["task"]["review_summary"]["status"], "none")
        self.assertEqual(read_payload["task"]["review_summary"]["request_count"], 0)
        self.assertEqual(timeline_status, 200)
        self.assertFalse(
            any(event["event_type"] == "review_requested" for event in timeline_payload["timeline"])
        )

    def test_read_model_handles_goal_to_work_ingested_task(self) -> None:
        flow_result = run_goal_to_work_flow(_goal_request(), auto_approve=True, service=self.service)
        ingested_task_id = next(
            item.task_id for item in flow_result.ingestion_result.item_results if item.ingested and item.task_id
        )

        status, payload = self.service.get_task_read_model(ingested_task_id)

        self.assertEqual(status, 200)
        self.assertEqual(payload["task"]["origin"]["source_system"], "linear")
        self.assertIn("linear", payload["task"]["extensions"])
        self.assertGreaterEqual(payload["task"]["evaluation_summary"]["count"], 1)

    def test_read_model_includes_execution_summary_after_dispatch(self) -> None:
        submit_status, submit_payload = self.service.evaluate(_request_payload("blocked_insufficient_evidence"))
        task_id = submit_payload["task_envelope"]["id"]
        dispatch_status, _ = self.service.dispatch_task(task_id, {"request": {"executor": "codex"}})

        read_status, read_payload = self.service.get_task_read_model(task_id)

        self.assertEqual(submit_status, 200)
        self.assertEqual(dispatch_status, 200)
        self.assertEqual(read_status, 200)
        self.assertEqual(read_payload["task"]["execution_summary"]["attempt_count"], 1)
        self.assertIsNotNone(read_payload["task"]["execution_summary"]["latest_attempt"])

    def test_read_model_exposes_clarification_summary_and_timeline_event(self) -> None:
        task_envelope = create_task_envelope(
            {
                "id": "task-read-model-clarification-1",
                "title": "Clarification in read model",
                "description": "Expose clarification in canonical inspection surfaces.",
                "origin": {
                    "source_system": "manual",
                    "source_type": "manual",
                    "source_id": "task-read-model-clarification-1",
                },
                "acceptance_criteria": [
                    {
                        "id": "ac-1",
                        "description": "Task becomes routable after clarification.",
                        "required": True,
                    }
                ],
            },
            now="2026-04-06T00:00:00Z",
        )
        submit_status, _ = self.service.submit(
            {
                "request": {
                    "task_envelope": task_envelope,
                    "task_status": "planned",
                    "unresolved_conditions": ["Need repository clarification before planning can proceed."],
                }
            }
        )

        read_status, read_payload = self.service.get_task_read_model("task-read-model-clarification-1")
        timeline_status, timeline_payload = self.service.get_task_timeline("task-read-model-clarification-1")

        self.assertEqual(submit_status, 200)
        self.assertEqual(read_status, 200)
        self.assertEqual(read_payload["task"]["current_status"], "blocked")
        self.assertEqual(read_payload["task"]["clarification_summary"]["status"], "required")
        self.assertEqual(read_payload["task"]["clarification_summary"]["resume_target_status"], "planned")
        self.assertEqual(read_payload["task"]["clarification_summary"]["open_required_input_count"], 1)
        self.assertEqual(timeline_status, 200)
        clarification_events = [
            event for event in timeline_payload["timeline"] if event["event_type"] == "clarification_updated"
        ]
        self.assertEqual(len(clarification_events), 1)
        self.assertEqual(clarification_events[0]["details"]["resume_target_status"], "planned")
 
    def test_read_model_exposes_retry_fields_for_retryable_failures(self) -> None:
        payload = _request_payload("blocked_insufficient_evidence")
        payload["request"]["runtime_facts"] = {
            "executor_reported_failure": True,
            "attempt_count": 1,
            "latest_attempt_outcome": "failed",
        }
        submit_status, submit_payload = self.service.evaluate(payload)
        task_id = submit_payload["task_envelope"]["id"]
        read_status, read_payload = self.service.get_task_read_model(task_id)

        self.assertEqual(submit_status, 200)
        self.assertEqual(read_status, 200)
        self.assertEqual(read_payload["task"]["execution_summary"]["retry_count"], 2)
        self.assertEqual(read_payload["task"]["execution_summary"]["total_attempts"], 3)
        self.assertEqual(read_payload["task"]["execution_summary"]["last_failure_type"], "evidence_insufficient")
        self.assertTrue(read_payload["task"]["execution_summary"]["retry_eligible"])
        self.assertEqual(read_payload["task"]["execution_summary"]["failure_state"], "retryable")
        self.assertEqual(read_payload["task"]["failure_summary"]["state"], "retryable")


class HarnessReadModelHttpApiTests(unittest.TestCase):
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

    def test_api_exposes_task_read_model_endpoint(self) -> None:
        submit_status, submit_payload = self._post_json("/evaluate", _request_payload("accepted_completion"))
        task_id = submit_payload["task_envelope"]["id"]

        status, payload = self._get_json(f"/tasks/{task_id}/read-model")

        self.assertEqual(submit_status, 200)
        self.assertEqual(status, 200)
        self.assertEqual(payload["task"]["task_id"], task_id)
        self.assertEqual(payload["task"]["current_status"], "completed")
        self.assertEqual(payload["task"]["verification_summary"]["outcome"], "accepted_completion")

    def test_api_exposes_task_timeline_endpoint(self) -> None:
        payload = _request_payload("blocked_insufficient_evidence")
        payload["request"]["runtime_facts"] = {
            "executor_reported_failure": True,
            "attempt_count": 1,
            "latest_attempt_outcome": "failed",
        }
        submit_status, submit_payload = self._post_json("/evaluate", payload)
        task_id = submit_payload["task_envelope"]["id"]

        status, payload = self._get_json(f"/tasks/{task_id}/timeline")

        event_types = {event["event_type"] for event in payload["timeline"]}

        self.assertEqual(submit_status, 200)
        self.assertEqual(status, 200)
        self.assertEqual(payload["task_id"], task_id)
        self.assertIn("task_created", event_types)
        self.assertIn("evaluation_recorded", event_types)
        self.assertIn("status_transition", event_types)
        self.assertIn("retry_scheduled", event_types)
        self.assertIn("retry_attempt_started", event_types)
        self.assertIn("retry_attempt_completed", event_types)


@unittest.skipUnless(POSTGRES_TEST_DATABASE_URL, "HARNESS_TEST_DATABASE_URL is required for Postgres read-model tests")
class PostgresBackedReadModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = PostgresHarnessStore(POSTGRES_TEST_DATABASE_URL or "")
        with self.store._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(POSTGRES_SCHEMA_SQL)
                cursor.execute("DELETE FROM evaluation_records")
                cursor.execute("DELETE FROM tasks")
        self.service = HarnessApiService(store=self.store)

    def tearDown(self) -> None:
        with self.store._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM evaluation_records")
                cursor.execute("DELETE FROM tasks")

    def test_postgres_store_preserves_read_model_and_timeline_surfaces(self) -> None:
        submit_status, submit_payload = self.service.evaluate(_request_payload("accepted_completion"))
        task_id = submit_payload["task_envelope"]["id"]

        read_status, read_payload = self.service.get_task_read_model(task_id)
        timeline_status, timeline_payload = self.service.get_task_timeline(task_id)

        self.assertEqual(submit_status, 200)
        self.assertEqual(read_status, 200)
        self.assertEqual(timeline_status, 200)
        self.assertEqual(read_payload["task"]["current_status"], "completed")
        self.assertEqual(read_payload["task"]["evaluation_summary"]["count"], 1)
        self.assertGreaterEqual(timeline_payload["event_count"], 1)


if __name__ == "__main__":
    unittest.main()
