from __future__ import annotations

from copy import deepcopy

from modules.demo_cases import build_demo_request
from tests.e2e.runtime_harness import RuntimeApiTestCase
from tests.e2e.scenario_builders import to_jsonable


class ControlPlaneAuditHistoryFlowTests(RuntimeApiTestCase):
    def test_evaluate_upsert_keeps_append_only_history_when_later_evaluation_changes_outcome(self) -> None:
        payload = {"request": to_jsonable(build_demo_request("accepted_completion"))}
        task_id = payload["request"]["task_envelope"]["id"]

        first_status, first_response = self.post_json("/evaluate", deepcopy(payload))
        second_status, second_response = self.post_json("/evaluate", deepcopy(payload))
        snapshot = self.snapshot_task(task_id)

        history = snapshot.history_response["evaluations"]
        history_ids = [item["evaluation_id"] for item in history]

        self.assertEqual(first_status, 200)
        self.assertEqual(second_status, 200)
        self.assertEqual(first_response["task_envelope"]["status"], "completed")
        self.assertEqual(second_response["task_envelope"]["status"], "blocked")
        self.assertEqual(snapshot.task_fetch_response["task"]["status"], "blocked")
        self.assertEqual(len(history), 2)
        self.assertEqual([item["result"]["task_envelope"]["status"] for item in history], ["completed", "blocked"])
        self.assertEqual(len(set(history_ids)), 2)
        timeline_evaluations = [
            event["details"]["evaluation_id"]
            for event in snapshot.timeline_response["timeline"]
            if event["event_type"] == "evaluation_recorded"
        ]
        self.assertEqual(timeline_evaluations, history_ids)

    def test_blocked_then_completed_path_preserves_ordered_history_and_timeline_ids(self) -> None:
        initial_request = {"request": to_jsonable(build_demo_request("accepted_completion"))}
        initial_request["request"]["external_facts"] = None
        scenario = self.create_evaluate_scenario(initial_request)

        reevaluated = scenario.reevaluate(
            {
                "request": {
                    "external_facts": deepcopy(
                        to_jsonable(build_demo_request("accepted_completion"))["external_facts"]
                    ),
                    "claimed_completion": True,
                    "acceptance_criteria_satisfied": True,
                    "runtime_facts": deepcopy(initial_request["request"]["runtime_facts"]),
                }
            }
        )

        history = reevaluated.history["evaluations"]
        history_ids = [item["evaluation_id"] for item in history]

        self.assertEqual(scenario.created.task["status"], "blocked")
        self.assertEqual(reevaluated.task["status"], "completed")
        self.assertEqual([item["result"]["task_envelope"]["status"] for item in history], ["blocked", "completed"])
        self.assertEqual(len(set(history_ids)), 2)
        timeline_evaluations = [
            event["details"]["evaluation_id"]
            for event in reevaluated.timeline["timeline"]
            if event["event_type"] == "evaluation_recorded"
        ]
        self.assertEqual(timeline_evaluations, history_ids)
