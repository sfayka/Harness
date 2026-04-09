from __future__ import annotations

from copy import deepcopy

from modules.demo_cases import build_demo_request
from tests.e2e.runtime_harness import RuntimeApiTestCase, RuntimeTaskSnapshot
from tests.e2e.scenario_builders import (
    build_review_decision_from_request,
    build_review_note_artifact,
    to_jsonable,
)


class ControlPlaneStoreIntegrityFlowTests(RuntimeApiTestCase):
    def _assert_snapshot_unchanged(self, before: RuntimeTaskSnapshot, after: RuntimeTaskSnapshot) -> None:
        self.assertEqual(after.task_fetch_status, before.task_fetch_status)
        self.assertEqual(after.task_fetch_response["task"], before.task_fetch_response["task"])
        self.assertEqual(after.read_model_status, before.read_model_status)
        self.assertEqual(after.read_model_response, before.read_model_response)
        self.assertEqual(after.timeline_status, before.timeline_status)
        self.assertEqual(after.timeline_response, before.timeline_response)
        self.assertEqual(after.history_status, before.history_status)
        self.assertEqual(after.history_response, before.history_response)

    def _assert_task_list_unchanged(self, before: dict, after: dict, *, task_id: str) -> None:
        before_items = {item["task_id"]: item for item in before["tasks"]}
        after_items = {item["task_id"]: item for item in after["tasks"]}
        self.assertEqual(after_items, before_items)
        self.assertIn(task_id, after_items)

    def test_invalid_reevaluation_does_not_corrupt_completed_task_truth(self) -> None:
        scenario = self.create_evaluate_scenario({"request": to_jsonable(build_demo_request("accepted_completion"))})
        before_list_status, before_list = self.list_tasks()

        rejected = scenario.reevaluate(
            {
                "request": {
                    "new_artifacts": [build_review_note_artifact("artifact-pr-1")],
                    "claimed_completion": True,
                    "acceptance_criteria_satisfied": True,
                }
            }
        )
        after_list_status, after_list = self.list_tasks()

        self.assertEqual(scenario.created.status, 200)
        self.assertEqual(before_list_status, 200)
        self.assertEqual(rejected.status, 400)
        self.assertTrue(rejected.response["invalid_input"])
        self.assertEqual(after_list_status, 200)
        self._assert_snapshot_unchanged(scenario.created.snapshot, rejected.snapshot)
        self._assert_task_list_unchanged(before_list, after_list, task_id=scenario.task_id)

    def test_invalid_reevaluation_does_not_corrupt_blocked_task_truth(self) -> None:
        scenario = self.create_evaluate_scenario(
            {"request": to_jsonable(build_demo_request("blocked_insufficient_evidence"))}
        )
        before_list_status, before_list = self.list_tasks()

        rejected = scenario.reevaluate(
            {
                "request": {
                    "new_artifacts": [build_review_note_artifact("artifact-pr-1")],
                    "claimed_completion": True,
                    "acceptance_criteria_satisfied": True,
                }
            }
        )
        after_list_status, after_list = self.list_tasks()

        self.assertEqual(scenario.created.status, 200)
        self.assertEqual(before_list_status, 200)
        self.assertEqual(rejected.status, 400)
        self.assertTrue(rejected.response["invalid_input"])
        self.assertEqual(after_list_status, 200)
        self._assert_snapshot_unchanged(scenario.created.snapshot, rejected.snapshot)
        self._assert_task_list_unchanged(before_list, after_list, task_id=scenario.task_id)

    def test_rejected_reevaluation_keeps_canceled_task_projection_stable_while_recording_new_facts(self) -> None:
        payload = {"request": to_jsonable(build_demo_request("review_required"))}
        payload["request"]["review_request"]["allowed_outcomes"] = [
            "accept_completion",
            "cancel_task",
        ]
        scenario = self.create_evaluate_scenario(payload)
        scenario.reevaluate(
            {
                "request": {
                    "review_decision": build_review_decision_from_request(
                        scenario.created.response["enforcement_result"]["review_request"],
                        outcome="cancel_task",
                    )
                }
            }
        )
        before = scenario.refresh()
        before_list_status, before_list = self.list_tasks()

        rejected = scenario.reevaluate(
            {
                "request": {
                    "external_facts": to_jsonable(build_demo_request("accepted_completion").external_facts),
                    "runtime_facts": to_jsonable(build_demo_request("accepted_completion").runtime_facts),
                    "claimed_completion": True,
                    "acceptance_criteria_satisfied": True,
                }
            }
        )
        after_list_status, after_list = self.list_tasks()

        self.assertEqual(before_list_status, 200)
        self.assertEqual(rejected.status, 200)
        self.assertEqual(rejected.response["action"], "transition_rejected")
        self.assertIn("canceled -> blocked", rejected.response["error"])
        self.assertEqual(after_list_status, 200)
        self.assertEqual(rejected.task["status"], "canceled")
        self.assertTrue(rejected.task["coordination"]["linear"]["record_found"])
        self.assertEqual(
            rejected.task["coordination"]["linear"]["provenance"]["source"],
            "reevaluation_request.external_facts",
        )
        self.assertEqual(rejected.read_model["task"]["current_status"], "canceled")
        self.assertEqual(
            rejected.read_model["task"]["failure_summary"],
            before.read_model_response["task"]["failure_summary"],
        )
        self.assertEqual(
            rejected.read_model["task"]["verification_summary"],
            before.read_model_response["task"]["verification_summary"],
        )
        before_entry = {item["task_id"]: item for item in before_list["tasks"]}[scenario.task_id]
        after_entry = {item["task_id"]: item for item in after_list["tasks"]}[scenario.task_id]
        self.assertEqual(after_entry["current_status"], before_entry["current_status"])
        self.assertEqual(after_entry["failure_summary"], before_entry["failure_summary"])
        self.assertEqual(after_entry["verification_summary"], before_entry["verification_summary"])
