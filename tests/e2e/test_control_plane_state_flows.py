from __future__ import annotations

from tests.e2e.runtime_harness import RuntimeApiTestCase
from tests.e2e.scenario_builders import (
    build_create_task_payload,
    build_manual_ingress_payload,
    build_review_decision,
    build_review_decision_from_request,
    build_review_required_payload,
)


class ControlPlaneStateFlowTests(RuntimeApiTestCase):
    def test_dispatch_ready_clarification_resolution_creates_real_dispatch_attempt(self) -> None:
        scenario = self.create_manual_ingress_scenario(
            build_manual_ingress_payload(
                task_id="e2e-control-clarification-dispatch",
                task_status="dispatch_ready",
                unresolved_conditions=["Need repository clarification before dispatch can begin."],
            )
        )

        self.assertEqual(scenario.created.task["status"], "blocked")
        self.assertEqual(scenario.created.task["clarification"]["resume_target_status"], "dispatch_ready")
        self.assertEqual(scenario.created.read_model["task"]["execution_summary"]["attempt_count"], 0)

        resolved = scenario.reevaluate(
            {"request": {"claimed_completion": False, "acceptance_criteria_satisfied": False}}
        )

        self.assertNotIn(resolved.task["status"], {"blocked", "dispatch_ready"})
        self.assertEqual(resolved.task["clarification"]["status"], "resolved")
        self.assertTrue(resolved.response["automatic_dispatch"]["attempted"])
        self.assertEqual(resolved.response["automatic_dispatch"]["status"], 200)
        self.assertEqual(resolved.response["automatic_dispatch"]["dispatch"]["attempt_id"], "attempt-1")
        self.assertEqual(resolved.read_model["task"]["execution_summary"]["attempt_count"], 1)
        self.assertTrue(
            any(
                event["event_type"] == "task_dispatched"
                and event["details"]["dispatch_trigger"] == "automatic_policy_post_reevaluation"
                for event in resolved.timeline["timeline"]
            )
        )

    def test_assigned_clarification_resolution_restores_active_assignment(self) -> None:
        scenario = self.create_task_scenario(
            build_create_task_payload(
                "e2e-control-clarification-assigned",
                title="Assigned clarification resume scenario",
            )
        )

        scenario.mutate_task(
            lambda task: (
                task.__setitem__("status", "assigned"),
                task.__setitem__(
                    "assigned_executor",
                    {
                        "executor_type": "codex",
                        "executor_id": "executor-flow-assigned-1",
                        "assignment_reason": "Seed assigned state for clarification-resume scenario.",
                    },
                ),
            )
        )

        blocked = scenario.reevaluate(
            {"request": {"unresolved_conditions": ["Need clarification before the assigned work can continue."]}}
        )
        self.assertEqual(blocked.task["status"], "blocked")
        self.assertEqual(blocked.task["clarification"]["resume_target_status"], "assigned")

        resolved = scenario.reevaluate(
            {"request": {"claimed_completion": False, "acceptance_criteria_satisfied": False}}
        )

        self.assertEqual(resolved.task["status"], "assigned")
        self.assertEqual(resolved.task["clarification"]["status"], "resolved")
        self.assertEqual(resolved.task["assigned_executor"]["executor_id"], "executor-flow-assigned-1")
        self.assertEqual(resolved.read_model["task"]["current_status"], "assigned")
        self.assertNotIn("automatic_dispatch", resolved.response)

    def test_manual_review_authorize_redispatch_records_second_attempt(self) -> None:
        initial_payload = build_review_required_payload(
            build_create_task_payload("e2e-control-redispatch")["request"]["task_envelope"]
        )
        initial_payload["request"]["review_request"]["allowed_outcomes"] = [
            "accept_completion",
            "authorize_redispatch",
        ]
        scenario = self.create_evaluate_scenario(initial_payload)

        scenario.mutate_task(
            lambda task: task["observability"]["execution_metadata"].__setitem__(
                "execution_attempts",
                [
                    {
                        "attempt_id": "attempt-1",
                        "recorded_at": "2026-03-24T17:05:00Z",
                        "status": "completed",
                        "reported_by": "codex",
                        "completion_claim_id": "claim-prior-1",
                        "artifact_references": [],
                        "metadata": {"dispatch_trigger": "manual_api"},
                        "reevaluation": {
                            "evaluation_id": "evaluation-prior-1",
                            "linked_at": "2026-03-24T17:06:00Z",
                            "action": "review_required",
                        },
                    }
                ],
            )
        )

        resolved = scenario.reevaluate(
            {
                "request": {
                    "review_decision": build_review_decision_from_request(
                        scenario.created.response["enforcement_result"]["review_request"],
                        outcome="authorize_redispatch",
                    )
                }
            }
        )

        self.assertEqual(resolved.response["target_status"], "failed")
        self.assertTrue(resolved.response["automatic_dispatch"]["attempted"])
        self.assertEqual(resolved.response["automatic_dispatch"]["status"], 200)
        self.assertEqual(resolved.response["automatic_dispatch"]["dispatch"]["attempt_id"], "attempt-2")
        self.assertEqual(resolved.read_model["task"]["execution_summary"]["attempt_count"], 2)
        self.assertEqual(resolved.task["status"], "failed")
        self.assertTrue(
            any(
                event["event_type"] == "task_dispatched"
                and event["details"]["dispatch_trigger"] == "manual_review_authorize_redispatch"
                for event in resolved.timeline["timeline"]
            )
        )
