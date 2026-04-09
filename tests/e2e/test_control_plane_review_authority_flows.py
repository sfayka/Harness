from __future__ import annotations

from copy import deepcopy

from tests.e2e.runtime_harness import RuntimeApiTestCase
from tests.e2e.scenario_builders import (
    build_create_task_payload,
    build_review_decision_from_request,
    build_review_required_payload,
)


class ControlPlaneReviewAuthorityFlowTests(RuntimeApiTestCase):
    def _review_required_scenario(self, task_id: str):
        return self.create_evaluate_scenario(
            build_review_required_payload(
                build_create_task_payload(
                    task_id,
                    title="Review authority must be explicit and auditable",
                )["request"]["task_envelope"]
            )
        )

    def _assert_review_gate_still_active(self, step_result) -> None:
        self.assertEqual(step_result.task["status"], "in_review")
        self.assertEqual(step_result.read_model["task"]["current_status"], "in_review")
        self.assertEqual(step_result.read_model["task"]["review_summary"]["status"], "requested")
        self.assertEqual(step_result.read_model["task"]["review_summary"]["decision_count"], 0)
        self.assertFalse(
            any(event["event_type"] == "review_decided" for event in step_result.timeline["timeline"])
        )

    def test_review_decision_without_active_gate_is_rejected_without_mutating_completed_task(self) -> None:
        scenario = self.create_task_scenario(
            build_create_task_payload(
                "e2e-review-no-active-gate",
                title="Task without a review gate should reject stray review decisions",
            )
        )
        self.assertNotEqual(scenario.created.task["status"], "in_review")

        rejected = scenario.reevaluate(
            {
                "request": {
                    "review_decision": build_review_decision_from_request(
                        {
                            "review_request_id": "review-request-no-active-gate",
                            "task_id": scenario.task_id,
                            "trigger": "reconciliation",
                            "summary": "No active review gate exists.",
                            "presented_sections": ["task_state", "evidence", "reconciliation"],
                            "allowed_outcomes": ["accept_completion"],
                            "requested_at": "2026-04-01T10:03:00Z",
                            "requested_by": "verification",
                            "metadata": {},
                        },
                        outcome="accept_completion",
                    )
                }
            }
        )

        self.assertEqual(rejected.status, 400)
        self.assertTrue(rejected.response["invalid_input"])
        self.assertIn("active review", rejected.response["error"])
        self.assertEqual(rejected.task["status"], scenario.created.task["status"])
        self.assertEqual(rejected.read_model["task"]["review_summary"]["status"], "none")
        self.assertFalse(
            any(event["event_type"] == "review_decided" for event in rejected.timeline["timeline"])
        )

    def test_review_decision_with_mismatched_target_status_is_rejected_and_gate_stays_active(self) -> None:
        scenario = self._review_required_scenario("e2e-review-mismatched-target")
        review_request = scenario.created.response["enforcement_result"]["review_request"]
        tampered = build_review_decision_from_request(review_request, outcome="accept_completion")
        tampered["authorized_target_status"] = "failed"
        tampered["recommended_target_status"] = "failed"

        rejected = scenario.reevaluate({"request": {"review_decision": tampered}})

        self.assertEqual(rejected.status, 400)
        self.assertTrue(rejected.response["invalid_input"])
        self.assertIn("review_decision", rejected.response["error"])
        self._assert_review_gate_still_active(rejected)

    def test_review_decision_for_non_active_request_is_rejected_and_gate_stays_active(self) -> None:
        scenario = self._review_required_scenario("e2e-review-non-active-request")
        review_request = scenario.created.response["enforcement_result"]["review_request"]
        tampered = build_review_decision_from_request(review_request, outcome="accept_completion")
        tampered["request"]["review_request_id"] = "review-request-other"
        tampered["review_request_id"] = "review-request-other"
        tampered["record"]["review_request_id"] = "review-request-other"

        rejected = scenario.reevaluate({"request": {"review_decision": tampered}})

        self.assertEqual(rejected.status, 400)
        self.assertTrue(rejected.response["invalid_input"])
        self.assertIn("active review request", rejected.response["error"])
        self._assert_review_gate_still_active(rejected)

    def test_review_decision_with_modified_request_contract_is_rejected_and_gate_stays_active(self) -> None:
        scenario = self._review_required_scenario("e2e-review-modified-contract")
        review_request = scenario.created.response["enforcement_result"]["review_request"]
        tampered = build_review_decision_from_request(review_request, outcome="accept_completion")
        tampered["request"] = deepcopy(tampered["request"])
        tampered["request"]["summary"] = "A different review contract was presented."

        rejected = scenario.reevaluate({"request": {"review_decision": tampered}})

        self.assertEqual(rejected.status, 400)
        self.assertTrue(rejected.response["invalid_input"])
        self.assertIn("match the active review request exactly", rejected.response["error"])
        self._assert_review_gate_still_active(rejected)
