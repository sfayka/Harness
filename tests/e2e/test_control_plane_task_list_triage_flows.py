from __future__ import annotations

import os
from unittest.mock import patch

from modules.demo_cases import build_demo_request
from tests.e2e.runtime_harness import RuntimeApiTestCase
from tests.e2e.scenario_builders import build_review_decision_from_request, to_jsonable


class ControlPlaneTaskListTriageFlowTests(RuntimeApiTestCase):
    def _tasks_by_id(self, payload: dict) -> dict[str, dict]:
        return {item["task_id"]: item for item in payload["tasks"]}

    def test_task_list_surfaces_review_requested_and_retryable_tasks_for_triage(self) -> None:
        review = self.create_evaluate_scenario({"request": to_jsonable(build_demo_request("review_required"))})

        retry_payload = {"request": to_jsonable(build_demo_request("blocked_insufficient_evidence"))}
        retry_payload["request"]["runtime_facts"] = {
            "executor_reported_failure": True,
            "attempt_count": 1,
            "latest_attempt_outcome": "failed",
        }
        with patch.dict(os.environ, {"HARNESS_CLASSIFIED_RETRY_BUDGET": "2"}):
            retryable = self.create_evaluate_scenario(retry_payload)

        list_status, list_payload = self.list_tasks()
        tasks = self._tasks_by_id(list_payload)

        self.assertEqual(list_status, 200)
        self.assertEqual(len(tasks), 2)

        review_entry = tasks[review.task_id]
        self.assertEqual(review_entry["current_status"], "in_review")
        self.assertEqual(review_entry["review_summary"]["status"], "requested")
        self.assertEqual(review_entry["review_summary"]["decision_count"], 0)
        self.assertEqual(review_entry["evaluation_summary"]["latest_action"], "review_required")

        retry_entry = tasks[retryable.task_id]
        self.assertEqual(retry_entry["current_status"], "blocked")
        self.assertEqual(retry_entry["failure_summary"]["state"], "retryable")
        self.assertEqual(retry_entry["execution_summary"]["retry_count"], 2)
        self.assertTrue(retry_entry["execution_summary"]["retry_eligible"])
        self.assertEqual(retry_entry["execution_summary"]["failure_state"], "retryable")
        self.assertEqual(retry_entry["review_summary"]["status"], "none")

    def test_task_list_updates_when_review_gate_is_resolved_to_completed(self) -> None:
        review = self.create_evaluate_scenario({"request": to_jsonable(build_demo_request("review_required"))})

        before_status, before_payload = self.list_tasks()
        before_entry = self._tasks_by_id(before_payload)[review.task_id]

        resolved = review.reevaluate(
            {
                "request": {
                    "review_decision": build_review_decision_from_request(
                        review.created.response["enforcement_result"]["review_request"],
                        outcome="accept_completion",
                    )
                }
            }
        )

        after_status, after_payload = self.list_tasks()
        after_entry = self._tasks_by_id(after_payload)[review.task_id]

        self.assertEqual(before_status, 200)
        self.assertEqual(before_entry["current_status"], "in_review")
        self.assertEqual(before_entry["review_summary"]["status"], "requested")
        self.assertEqual(before_entry["review_summary"]["decision_count"], 0)

        self.assertEqual(resolved.status, 200)
        self.assertEqual(resolved.task["status"], "completed")

        self.assertEqual(after_status, 200)
        self.assertEqual(after_entry["current_status"], "completed")
        self.assertEqual(after_entry["review_summary"]["status"], "resolved")
        self.assertEqual(after_entry["review_summary"]["decision_count"], 1)
        self.assertEqual(after_entry["verification_summary"]["outcome"], "review_resolved")
        self.assertFalse(after_entry["verification_summary"]["requires_review"])
        self.assertTrue(after_entry["verification_summary"]["accepted_completion"])
        self.assertEqual(after_entry["failure_summary"]["state"], "clear")
        self.assertEqual(after_entry["failure_summary"]["failure_type"], "none")
        self.assertEqual(after_entry["execution_summary"]["failure_state"], "clear")
        self.assertFalse(after_entry["execution_summary"]["retry_eligible"])
        self.assertEqual(after_entry["evaluation_summary"]["latest_action"], "transition_applied")

    def test_task_list_disables_automatic_completion_safe_after_manual_keep_blocked(self) -> None:
        review = self.create_evaluate_scenario({"request": to_jsonable(build_demo_request("review_required"))})

        review.reevaluate(
            {
                "request": {
                    "review_decision": build_review_decision_from_request(
                        review.created.response["enforcement_result"]["review_request"],
                        outcome="keep_blocked",
                    )
                }
            }
        )

        list_status, list_payload = self.list_tasks()
        entry = self._tasks_by_id(list_payload)[review.task_id]

        self.assertEqual(list_status, 200)
        self.assertEqual(entry["current_status"], "blocked")
        self.assertEqual(entry["review_summary"]["status"], "resolved")
        self.assertEqual(entry["verification_summary"]["outcome"], "review_resolved")
        self.assertFalse(entry["verification_summary"]["accepted_completion"])
        self.assertFalse(entry["verification_summary"]["acceptance_criteria_assessment"]["automatic_completion_safe"])
