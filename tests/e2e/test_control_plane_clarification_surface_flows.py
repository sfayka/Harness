from __future__ import annotations

from tests.e2e.runtime_harness import RuntimeApiTestCase
from tests.e2e.scenario_builders import build_create_task_payload, build_manual_ingress_payload


class ControlPlaneClarificationSurfaceFlowTests(RuntimeApiTestCase):
    def _listed_task(self, task_id: str) -> dict:
        status, payload = self.list_tasks()
        self.assertEqual(status, 200)
        return next(task for task in payload["tasks"] if task["task_id"] == task_id)

    def test_required_clarification_is_visible_across_task_read_model_list_and_timeline(self) -> None:
        scenario = self.create_manual_ingress_scenario(
            build_manual_ingress_payload(
                task_id="e2e-control-clarification-visible",
                task_status="dispatch_ready",
                unresolved_conditions=["Need repository clarification before dispatch can begin."],
            )
        )

        listed = self._listed_task(scenario.task_id)
        clarification = scenario.created.read_model["task"]["clarification_summary"]
        timeline_events = [event["event_type"] for event in scenario.created.timeline["timeline"]]

        self.assertEqual(scenario.created.task["status"], "blocked")
        self.assertEqual(scenario.created.task["clarification"]["status"], "required")
        self.assertEqual(scenario.created.task["clarification"]["resume_target_status"], "dispatch_ready")
        self.assertEqual(clarification["status"], "required")
        self.assertEqual(clarification["resume_target_status"], "dispatch_ready")
        self.assertEqual(clarification["open_required_input_count"], 1)
        self.assertEqual(listed["current_status"], "blocked")
        self.assertEqual(listed["clarification_summary"]["status"], "required")
        self.assertEqual(listed["clarification_summary"]["resume_target_status"], "dispatch_ready")
        self.assertEqual(listed["execution_summary"]["attempt_count"], 0)
        self.assertIn("clarification_required", timeline_events)
        self.assertIn("clarification_updated", timeline_events)
        self.assertNotIn("task_dispatched", timeline_events)

    def test_clearing_dispatch_ready_clarification_updates_surfaces_and_records_real_dispatch(self) -> None:
        scenario = self.create_manual_ingress_scenario(
            build_manual_ingress_payload(
                task_id="e2e-control-clarification-dispatch-surface",
                task_status="dispatch_ready",
                unresolved_conditions=["Need repository clarification before dispatch can begin."],
            )
        )

        resolved = scenario.reevaluate(
            {"request": {"claimed_completion": False, "acceptance_criteria_satisfied": False}}
        )
        listed = self._listed_task(scenario.task_id)
        dispatch_events = [
            event
            for event in resolved.timeline["timeline"]
            if event["event_type"] == "task_dispatched"
        ]

        self.assertEqual(resolved.task["clarification"]["status"], "resolved")
        self.assertEqual(
            resolved.task["clarification"]["resolution_summary"],
            "Clarification requirements were cleared by the reevaluation input.",
        )
        self.assertTrue(resolved.response["automatic_dispatch"]["attempted"])
        self.assertEqual(resolved.response["automatic_dispatch"]["dispatch"]["attempt_id"], "attempt-1")
        self.assertEqual(resolved.read_model["task"]["clarification_summary"]["status"], "resolved")
        self.assertEqual(resolved.read_model["task"]["execution_summary"]["attempt_count"], 1)
        self.assertEqual(listed["clarification_summary"]["status"], "resolved")
        self.assertEqual(listed["execution_summary"]["attempt_count"], 1)
        self.assertTrue(
            any(event["event_type"] == "clarification_resolved" for event in resolved.timeline["timeline"])
        )
        self.assertTrue(
            any(event["details"]["dispatch_trigger"] == "automatic_policy_post_reevaluation" for event in dispatch_events)
        )

    def test_clearing_assigned_clarification_restores_assignment_without_dispatching(self) -> None:
        scenario = self.create_task_scenario(
            build_create_task_payload(
                "e2e-control-clarification-assignment-surface",
                title="Clarification-assignment surface scenario",
            )
        )

        scenario.mutate_task(
            lambda task: task.update(
                {
                    "status": "assigned",
                    "assigned_executor": {
                        "executor_type": "codex",
                        "executor_id": "executor-clarification-surface-1",
                        "assignment_reason": "Seed assigned state for clarification-surface coverage.",
                    },
                }
            )
        )

        blocked = scenario.reevaluate(
            {"request": {"unresolved_conditions": ["Need clarification before the assigned work can continue."]}}
        )
        resolved = scenario.reevaluate(
            {"request": {"claimed_completion": False, "acceptance_criteria_satisfied": False}}
        )
        listed = self._listed_task(scenario.task_id)

        self.assertEqual(blocked.task["clarification"]["status"], "required")
        self.assertEqual(blocked.task["clarification"]["resume_target_status"], "assigned")
        self.assertEqual(resolved.task["status"], "assigned")
        self.assertEqual(resolved.task["assigned_executor"]["executor_id"], "executor-clarification-surface-1")
        self.assertEqual(resolved.task["clarification"]["status"], "resolved")
        self.assertEqual(resolved.read_model["task"]["current_status"], "assigned")
        self.assertEqual(resolved.read_model["task"]["assigned_executor"]["executor_id"], "executor-clarification-surface-1")
        self.assertEqual(resolved.read_model["task"]["execution_summary"]["attempt_count"], 0)
        self.assertEqual(listed["current_status"], "assigned")
        self.assertEqual(listed["assigned_executor"]["executor_id"], "executor-clarification-surface-1")
        self.assertEqual(listed["clarification_summary"]["status"], "resolved")
        self.assertFalse(
            any(event["event_type"] == "task_dispatched" for event in resolved.timeline["timeline"])
        )
        self.assertTrue(
            any(event["event_type"] == "clarification_resolved" for event in resolved.timeline["timeline"])
        )
