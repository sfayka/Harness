from __future__ import annotations

import os
from unittest.mock import patch

from modules.demo_cases import build_demo_request
from tests.e2e.runtime_harness import RuntimeApiTestCase
from tests.e2e.scenario_builders import build_review_decision_from_request, to_jsonable


class ControlPlaneSupervisionQueueFlowTests(RuntimeApiTestCase):
    def _queue_by_task_id(self, payload: dict) -> dict[str, dict]:
        return {item["task_id"]: item for item in payload["queue"]}

    def test_supervision_queue_surfaces_review_and_retry_attention(self) -> None:
        review = self.create_evaluate_scenario({"request": to_jsonable(build_demo_request("review_required"))})

        retry_payload = {"request": to_jsonable(build_demo_request("blocked_insufficient_evidence"))}
        retry_payload["request"]["runtime_facts"] = {
            "executor_reported_failure": True,
            "attempt_count": 1,
            "latest_attempt_outcome": "failed",
        }
        with patch.dict(os.environ, {"HARNESS_CLASSIFIED_RETRY_BUDGET": "2"}):
            retryable = self.create_evaluate_scenario(retry_payload)

        status, payload = self.supervision_queue()
        queue = payload["queue"]
        entries = self._queue_by_task_id(payload)

        self.assertEqual(status, 200)
        self.assertEqual(queue[0]["task_id"], review.task_id)
        self.assertEqual(entries[review.task_id]["attention_type"], "review_required")
        self.assertEqual(entries[review.task_id]["suggested_action"], "resolve_review_gate")
        self.assertFalse(entries[review.task_id]["stale"])
        self.assertEqual(entries[retryable.task_id]["attention_type"], "retryable_failure")
        self.assertEqual(entries[retryable.task_id]["suggested_action"], "retry_or_redispatch")
        self.assertTrue(entries[retryable.task_id]["retry_eligible"])
        self.assertEqual(entries[retryable.task_id]["failure_state"], "retryable")

    def test_supervision_queue_clears_review_attention_after_manual_resolution(self) -> None:
        review = self.create_evaluate_scenario({"request": to_jsonable(build_demo_request("review_required"))})

        before_status, before_payload = self.supervision_queue()
        self.assertEqual(before_status, 200)
        self.assertEqual(self._queue_by_task_id(before_payload)[review.task_id]["attention_type"], "review_required")

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
        after_status, after_payload = self.supervision_queue()

        self.assertEqual(resolved.status, 200)
        self.assertEqual(resolved.task["status"], "completed")
        self.assertEqual(after_status, 200)
        self.assertNotIn(review.task_id, self._queue_by_task_id(after_payload))
