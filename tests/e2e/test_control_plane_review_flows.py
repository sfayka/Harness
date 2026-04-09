from __future__ import annotations

from tests.e2e.runtime_harness import RuntimeApiTestCase
from tests.e2e.scenario_builders import (
    build_create_task_payload,
    build_happy_path_overlays,
    build_review_decision_from_request,
    build_review_required_payload,
    build_reevaluate_payload,
)


class ControlPlaneReviewFlowTests(RuntimeApiTestCase):
    def test_review_required_evaluation_creates_active_review_gate_visible_across_surfaces(self) -> None:
        scenario = self.create_evaluate_scenario(
            build_review_required_payload(
                build_create_task_payload(
                    "e2e-control-review-requested",
                    title="Review gate should be visible across inspection surfaces",
                )["request"]["task_envelope"]
            )
        )

        self.assertEqual(scenario.created.response["action"], "review_required")
        self.assertTrue(scenario.created.response["requires_review"])
        self.assertEqual(scenario.created.task["status"], "in_review")
        self.assertEqual(scenario.created.read_model["task"]["current_status"], "in_review")
        self.assertEqual(scenario.created.read_model["task"]["review_summary"]["status"], "requested")
        self.assertEqual(scenario.created.read_model["task"]["review_summary"]["request_count"], 1)
        self.assertEqual(scenario.created.read_model["task"]["review_summary"]["decision_count"], 0)
        self.assertEqual(
            scenario.created.read_model["task"]["review_summary"]["latest_request"]["review_request_id"],
            scenario.created.response["enforcement_result"]["review_request"]["review_request_id"],
        )
        self.assertTrue(
            any(event["event_type"] == "review_requested" for event in scenario.created.timeline["timeline"])
        )

    def test_automatic_reevaluation_cannot_clear_active_review_gate(self) -> None:
        scenario = self.create_evaluate_scenario(
            build_review_required_payload(
                build_create_task_payload(
                    "e2e-control-review-sticky",
                    title="Automatic reevaluation must not clear a review gate",
                )["request"]["task_envelope"]
            )
        )
        happy_overlays = build_happy_path_overlays()

        reevaluated = scenario.reevaluate(
            build_reevaluate_payload(
                external_facts=happy_overlays["external_facts"],
                runtime_facts=happy_overlays["runtime_facts"],
            )
        )

        self.assertEqual(reevaluated.response["action"], "review_required")
        self.assertTrue(reevaluated.response["requires_review"])
        self.assertEqual(reevaluated.task["status"], "in_review")
        self.assertEqual(reevaluated.read_model["task"]["current_status"], "in_review")
        self.assertEqual(reevaluated.read_model["task"]["review_summary"]["status"], "requested")
        self.assertEqual(reevaluated.read_model["task"]["review_summary"]["request_count"], 1)
        self.assertEqual(reevaluated.read_model["task"]["review_summary"]["decision_count"], 0)
        self.assertFalse(
            any(event["event_type"] == "review_decided" for event in reevaluated.timeline["timeline"])
        )

    def test_manual_review_accept_completion_resolves_gate_and_completes_task(self) -> None:
        scenario = self.create_evaluate_scenario(
            build_review_required_payload(
                build_create_task_payload(
                    "e2e-control-review-resolved",
                    title="Manual review resolution should be auditable",
                )["request"]["task_envelope"]
            )
        )

        resolved = scenario.reevaluate(
            {
                "request": {
                    "review_decision": build_review_decision_from_request(
                        scenario.created.response["enforcement_result"]["review_request"],
                        outcome="accept_completion",
                    )
                }
            }
        )

        self.assertEqual(resolved.response["action"], "transition_applied")
        self.assertEqual(resolved.task["status"], "completed")
        self.assertEqual(resolved.read_model["task"]["current_status"], "completed")
        self.assertEqual(resolved.read_model["task"]["review_summary"]["status"], "resolved")
        self.assertEqual(resolved.read_model["task"]["review_summary"]["decision_count"], 1)
        self.assertEqual(resolved.read_model["task"]["verification_summary"]["outcome"], "review_resolved")
        self.assertFalse(resolved.read_model["task"]["verification_summary"]["requires_review"])
        self.assertTrue(resolved.read_model["task"]["verification_summary"]["accepted_completion"])
        self.assertEqual(
            resolved.read_model["task"]["review_summary"]["latest_decision"]["outcome"],
            "accept_completion",
        )
        self.assertTrue(any(event["event_type"] == "review_decided" for event in resolved.timeline["timeline"]))
        self.assertTrue(
            any(
                event["event_type"] == "status_transition" and event["details"]["to_status"] == "completed"
                for event in resolved.timeline["timeline"]
            )
        )

    def test_manual_review_keep_blocked_resolves_gate_without_projecting_automatic_acceptance(self) -> None:
        scenario = self.create_evaluate_scenario(
            build_review_required_payload(
                build_create_task_payload(
                    "e2e-control-review-keep-blocked",
                    title="Manual review can keep work blocked without projecting safe completion",
                )["request"]["task_envelope"]
            )
        )

        resolved = scenario.reevaluate(
            {
                "request": {
                    "review_decision": build_review_decision_from_request(
                        scenario.created.response["enforcement_result"]["review_request"],
                        outcome="keep_blocked",
                    )
                }
            }
        )

        self.assertEqual(resolved.response["action"], "transition_applied")
        self.assertEqual(resolved.task["status"], "blocked")
        self.assertEqual(resolved.read_model["task"]["current_status"], "blocked")
        self.assertEqual(resolved.read_model["task"]["review_summary"]["status"], "resolved")
        self.assertEqual(resolved.read_model["task"]["verification_summary"]["outcome"], "review_resolved")
        self.assertFalse(resolved.read_model["task"]["verification_summary"]["accepted_completion"])
        self.assertFalse(
            resolved.read_model["task"]["verification_summary"]["acceptance_criteria_assessment"][
                "automatic_completion_safe"
            ]
        )
