from __future__ import annotations

from tests.e2e.runtime_harness import RuntimeApiTestCase
from tests.e2e.scenario_builders import (
    build_create_task_payload,
    build_review_decision_from_request,
    build_review_required_payload,
)


class ControlPlaneTaskListExecutionFlowTests(RuntimeApiTestCase):
    def _tasks_by_id(self, payload: dict) -> dict[str, dict]:
        return {item["task_id"]: item for item in payload["tasks"]}

    def test_task_list_surfaces_automatic_and_manual_dispatch_attempts(self) -> None:
        automatic_payload = build_create_task_payload(
            "e2e-list-execution-automatic",
            title="Automatic dispatch list execution scenario",
        )
        automatic_payload["request"]["task_status"] = "dispatch_ready"
        automatic_status, automatic_response = self.post_json("/tasks", automatic_payload)

        manual = self.create_task_scenario(
            build_create_task_payload(
                "e2e-list-execution-manual",
                title="Manual dispatch list execution scenario",
            )
        )
        manual.mutate_task(
            lambda task: task.update(
                {
                    "status": "assigned",
                    "assigned_executor": {
                        "executor_type": "codex",
                        "executor_id": "executor-list-execution-1",
                        "assignment_reason": "Seed assigned state for task-list execution coverage.",
                    },
                }
            )
        )
        manual_dispatched = manual.dispatch({"request": {"executor": "codex"}})

        list_status, list_payload = self.list_tasks()
        tasks = self._tasks_by_id(list_payload)

        self.assertEqual(automatic_status, 200)
        self.assertTrue(automatic_response["automatic_dispatch"]["attempted"])
        self.assertEqual(manual_dispatched.status, 200)
        self.assertEqual(list_status, 200)

        automatic_entry = tasks["e2e-list-execution-automatic"]
        self.assertEqual(automatic_entry["execution_summary"]["attempt_count"], 1)
        self.assertEqual(automatic_entry["execution_summary"]["latest_dispatch_origin"], "automatic")
        self.assertEqual(
            automatic_entry["execution_summary"]["latest_attempt"]["metadata"]["dispatch_trigger"],
            "automatic_policy_post_ingestion",
        )
        self.assertEqual(automatic_entry["execution_summary"]["latest_attempt"]["attempt_id"], "attempt-1")

        manual_entry = tasks["e2e-list-execution-manual"]
        self.assertEqual(manual_entry["execution_summary"]["attempt_count"], 1)
        self.assertEqual(manual_entry["execution_summary"]["latest_dispatch_origin"], "manual")
        self.assertEqual(
            manual_entry["execution_summary"]["latest_attempt"]["metadata"]["dispatch_trigger"],
            "manual_api",
        )
        self.assertEqual(manual_entry["execution_summary"]["latest_attempt"]["attempt_id"], "attempt-1")
        self.assertEqual(manual_entry["failure_summary"]["failure_type"], "contract_violation")

    def test_task_list_updates_latest_attempt_after_manual_review_authorizes_redispatch(self) -> None:
        initial_payload = build_review_required_payload(
            build_create_task_payload(
                "e2e-list-execution-redispatch",
                title="Redispatch list execution scenario",
            )["request"]["task_envelope"]
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
                        "metadata": {"dispatch_trigger": "manual_api", "dispatch_mode": "manual"},
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

        list_status, list_payload = self.list_tasks()
        entry = self._tasks_by_id(list_payload)["e2e-list-execution-redispatch"]

        self.assertEqual(resolved.status, 200)
        self.assertTrue(resolved.response["automatic_dispatch"]["attempted"])
        self.assertEqual(list_status, 200)
        self.assertEqual(entry["execution_summary"]["attempt_count"], 2)
        self.assertEqual(entry["execution_summary"]["latest_dispatch_origin"], "automatic")
        self.assertEqual(entry["execution_summary"]["latest_attempt"]["attempt_id"], "attempt-2")
        self.assertEqual(
            entry["execution_summary"]["latest_attempt"]["metadata"]["dispatch_trigger"],
            "manual_review_authorize_redispatch",
        )
        self.assertEqual(entry["review_summary"]["status"], "resolved")
        self.assertEqual(entry["review_summary"]["decision_count"], 1)
