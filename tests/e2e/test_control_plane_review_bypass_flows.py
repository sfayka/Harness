from __future__ import annotations

from copy import deepcopy

from tests.e2e.runtime_harness import RuntimeApiTestCase
from tests.e2e.scenario_builders import (
    build_create_task_payload,
    build_happy_path_overlays,
    build_review_required_payload,
)


class ControlPlaneReviewBypassFlowTests(RuntimeApiTestCase):
    def _review_required_scenario(self, task_id: str):
        return self.create_evaluate_scenario(
            build_review_required_payload(
                build_create_task_payload(
                    task_id,
                    title="Active review gates must resist alternate control-plane paths",
                )["request"]["task_envelope"]
            )
        )

    def _assert_gate_still_active(self, step_result) -> None:
        self.assertEqual(step_result.task["status"], "in_review")
        self.assertEqual(step_result.read_model["task"]["current_status"], "in_review")
        self.assertEqual(step_result.read_model["task"]["review_summary"]["status"], "requested")
        self.assertEqual(step_result.read_model["task"]["review_summary"]["decision_count"], 0)
        self.assertFalse(
            any(event["event_type"] == "review_decided" for event in step_result.timeline["timeline"])
        )

    def test_reevaluate_cannot_complete_in_review_task_without_manual_decision(self) -> None:
        scenario = self._review_required_scenario("e2e-review-bypass-reevaluate")
        happy_overlays = build_happy_path_overlays()

        reevaluated = scenario.reevaluate(
            {
                "request": {
                    "external_facts": deepcopy(happy_overlays["external_facts"]),
                    "claimed_completion": True,
                    "acceptance_criteria_satisfied": True,
                    "runtime_facts": deepcopy(happy_overlays["runtime_facts"]),
                }
            }
        )

        self.assertEqual(reevaluated.status, 200)
        self.assertEqual(reevaluated.response["action"], "review_required")
        self.assertTrue(reevaluated.response["requires_review"])
        self._assert_gate_still_active(reevaluated)

    def test_evaluate_upsert_cannot_bypass_active_review_gate(self) -> None:
        scenario = self._review_required_scenario("e2e-review-bypass-evaluate")
        overwrite_payload = build_review_required_payload(
            build_create_task_payload(
                scenario.task_id,
                title="Upsert path must not overwrite an active review gate",
            )["request"]["task_envelope"]
        )
        happy_overlays = build_happy_path_overlays()
        overwrite_payload["request"]["task_envelope"]["id"] = scenario.task_id
        overwrite_payload["request"]["task_envelope"]["status"] = "completed"
        overwrite_payload["request"]["task_envelope"]["timestamps"]["completed_at"] = "2026-03-24T18:00:00Z"
        overwrite_payload["request"]["external_facts"] = deepcopy(happy_overlays["external_facts"])
        overwrite_payload["request"]["runtime_facts"] = deepcopy(happy_overlays["runtime_facts"])
        overwrite_payload["request"]["claimed_completion"] = True
        overwrite_payload["request"]["acceptance_criteria_satisfied"] = True
        overwrite_payload["request"].pop("review_request", None)

        status, response = self.post_json("/evaluate", overwrite_payload)
        after = self.snapshot_task(scenario.task_id)

        self.assertEqual(status, 400)
        self.assertTrue(response["invalid_input"])
        self.assertIn(f"/tasks/{scenario.task_id}/reevaluate", response["error"])
        self.assertEqual(after.task_fetch_response["task"]["status"], "in_review")
        self.assertEqual(after.read_model_response["task"]["current_status"], "in_review")
        self.assertEqual(after.read_model_response["task"]["review_summary"]["status"], "requested")
        self.assertEqual(after.read_model_response["task"]["review_summary"]["decision_count"], 0)
        self.assertFalse(any(event["event_type"] == "review_decided" for event in after.timeline_response["timeline"]))
