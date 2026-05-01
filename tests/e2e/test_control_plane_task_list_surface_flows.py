from __future__ import annotations

from copy import deepcopy

from modules.demo_cases import build_demo_request
from tests.e2e.runtime_harness import RuntimeApiTestCase
from tests.e2e.scenario_builders import build_manual_ingress_payload, to_jsonable


class ControlPlaneTaskListSurfaceFlowTests(RuntimeApiTestCase):
    def _tasks_by_id(self, payload: dict) -> dict[str, dict]:
        return {item["task_id"]: item for item in payload["tasks"]}

    def test_task_list_surfaces_mixed_statuses_with_canonical_summaries(self) -> None:
        completed = self.create_evaluate_scenario({"request": to_jsonable(build_demo_request("accepted_completion"))})
        blocked = self.create_manual_ingress_scenario(
            build_manual_ingress_payload(
                task_id="e2e-list-blocked-clarification",
                task_status="dispatch_ready",
                unresolved_conditions=["Need repository clarification before execution can begin."],
            )
        )

        list_status, list_payload = self.list_tasks()
        tasks = self._tasks_by_id(list_payload)

        self.assertEqual(completed.created.status, 200)
        self.assertEqual(blocked.created.status, 200)
        self.assertEqual(list_status, 200)
        self.assertEqual(len(tasks), 2)

        completed_entry = tasks[completed.task_id]
        self.assertEqual(completed_entry["current_status"], "completed")
        self.assertEqual(completed_entry["verification_summary"]["outcome"], "accepted_completion")
        self.assertEqual(completed_entry["completion_validation_summary"]["status"], "accepted")
        self.assertTrue(completed_entry["completion_validation_summary"]["completion_accepted"])
        self.assertEqual(completed_entry["review_summary"]["status"], "none")
        self.assertIn("timeline", completed_entry)

        blocked_entry = tasks[blocked.task_id]
        self.assertEqual(blocked_entry["current_status"], "blocked")
        self.assertEqual(blocked_entry["completion_validation_summary"]["status"], "pending")
        self.assertFalse(blocked_entry["completion_validation_summary"]["completion_accepted"])
        self.assertEqual(blocked_entry["clarification_summary"]["status"], "required")
        self.assertEqual(blocked_entry["clarification_summary"]["resume_target_status"], "dispatch_ready")
        self.assertEqual(blocked_entry["origin"]["source_system"], "manual")
        self.assertIn("timeline", blocked_entry)

    def test_task_list_reflects_blocked_task_progressing_to_completed(self) -> None:
        initial_request = to_jsonable(build_demo_request("accepted_completion"))
        initial_request["external_facts"] = None
        scenario = self.create_evaluate_scenario({"request": initial_request})

        before_status, before_payload = self.list_tasks()
        reevaluated = scenario.reevaluate(
            {
                "request": {
                    "external_facts": deepcopy(
                        to_jsonable(build_demo_request("accepted_completion"))["external_facts"]
                    ),
                    "claimed_completion": True,
                    "acceptance_criteria_satisfied": True,
                    "runtime_facts": deepcopy(initial_request["runtime_facts"]),
                }
            }
        )
        after_status, after_payload = self.list_tasks()

        self.assertEqual(before_status, 200)
        before_entry = self._tasks_by_id(before_payload)[scenario.task_id]
        self.assertEqual(before_entry["current_status"], "blocked")
        self.assertEqual(before_entry["verification_summary"]["outcome"], "blocked_unresolved_conditions")

        self.assertEqual(reevaluated.status, 200)
        self.assertEqual(reevaluated.task["status"], "completed")

        self.assertEqual(after_status, 200)
        after_entry = self._tasks_by_id(after_payload)[scenario.task_id]
        self.assertEqual(after_entry["current_status"], "completed")
        self.assertEqual(after_entry["verification_summary"]["outcome"], "accepted_completion")
        self.assertEqual(
            after_entry["coordination_summary"]["linear"]["provenance"]["source"],
            "reevaluation_request.external_facts",
        )
