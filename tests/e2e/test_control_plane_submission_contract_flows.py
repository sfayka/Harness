from __future__ import annotations

from copy import deepcopy

from tests.e2e.runtime_harness import RuntimeApiTestCase
from tests.e2e.scenario_builders import build_create_task_payload, build_happy_path_overlays


class ControlPlaneSubmissionContractFlowTests(RuntimeApiTestCase):
    def _assert_task_absent(self, task_id: str) -> None:
        task_status, task_payload = self.get_json(f"/tasks/{task_id}")
        history_status, history_payload = self.get_json(f"/tasks/{task_id}/evaluations")
        list_status, list_payload = self.get_json("/tasks")

        self.assertEqual(task_status, 404)
        self.assertIn("not found", task_payload["error"].lower())
        self.assertEqual(history_status, 404)
        self.assertIn("not found", history_payload["error"].lower())
        self.assertEqual(list_status, 200)
        self.assertFalse(any(task["task_id"] == task_id for task in list_payload["tasks"]))

    def test_submit_rejects_completion_shaped_new_task_without_persisting_state(self) -> None:
        task_id = "e2e-submit-completion-shaped"
        payload = build_create_task_payload(task_id)
        overlays = build_happy_path_overlays()
        payload["request"].update(
            {
                "linked_artifacts": deepcopy(overlays["linked_artifacts"]),
                "completion_evidence": deepcopy(overlays["completion_evidence"]),
                "external_facts": deepcopy(overlays["external_facts"]),
                "runtime_facts": deepcopy(overlays["runtime_facts"]),
                "claimed_completion": True,
                "acceptance_criteria_satisfied": True,
            }
        )

        status, response = self.post_json("/tasks", payload)

        self.assertEqual(status, 400)
        self.assertTrue(response["invalid_input"])
        self.assertIn("cannot claim completion", response["error"].lower())
        self.assertTrue(response["submission_contract_violations"])
        self._assert_task_absent(task_id)

    def test_submit_rejects_nested_execution_history_without_persisting_state(self) -> None:
        task_id = "e2e-submit-execution-history"
        payload = build_create_task_payload(task_id)
        payload["request"]["task_envelope"]["observability"]["execution_metadata"]["execution_attempts"] = [
            {"attempt_id": "attempt-1", "status": "completed"}
        ]

        status, response = self.post_json("/tasks", payload)

        self.assertEqual(status, 400)
        self.assertTrue(response["invalid_input"])
        self.assertEqual(
            response["submission_contract_violations"][0]["rule"],
            "initial_execution_attempt_history_not_allowed",
        )
        self._assert_task_absent(task_id)

    def test_submit_rejects_validated_completion_evidence_without_persisting_state(self) -> None:
        task_id = "e2e-submit-validated-evidence"
        payload = build_create_task_payload(task_id)
        evidence = payload["request"]["task_envelope"]["artifacts"]["completion_evidence"]
        evidence["status"] = "satisfied"
        evidence["validated_artifact_ids"] = ["artifact-pr-1"]
        evidence["validated_at"] = "2026-04-07T00:00:00Z"

        status, response = self.post_json("/tasks", payload)

        self.assertEqual(status, 400)
        self.assertTrue(response["invalid_input"])
        self.assertTrue(
            any(
                violation["rule"] == "initial_validated_completion_evidence_not_allowed"
                for violation in response["submission_contract_violations"]
            )
        )
        self._assert_task_absent(task_id)

    def test_submit_rejects_assigned_status_without_persisting_state(self) -> None:
        task_id = "e2e-submit-assigned-status"
        payload = build_create_task_payload(task_id)
        payload["request"]["task_status"] = "assigned"

        status, response = self.post_json("/tasks", payload)

        self.assertEqual(status, 400)
        self.assertTrue(response["invalid_input"])
        self.assertTrue(
            any(
                violation["rule"] == "initial_task_status_invalid"
                for violation in response["submission_contract_violations"]
            )
        )
        self._assert_task_absent(task_id)

    def test_submit_rejects_assigned_executor_without_persisting_state(self) -> None:
        task_id = "e2e-submit-assigned-executor"
        payload = build_create_task_payload(task_id)
        payload["request"]["assigned_executor"] = {
            "executor_type": "codex",
            "executor_id": "executor-submit-e2e-1",
            "assignment_reason": "Fresh submission should not assign executors.",
        }

        status, response = self.post_json("/tasks", payload)

        self.assertEqual(status, 400)
        self.assertTrue(response["invalid_input"])
        self.assertTrue(
            any(
                violation["rule"] == "initial_assigned_executor_not_allowed"
                for violation in response["submission_contract_violations"]
            )
        )
        self._assert_task_absent(task_id)

    def test_submit_rejects_missing_task_id_with_structured_error_and_no_persisted_tasks(self) -> None:
        status, payload = self.post_json("/tasks", {"request": {"task_envelope": {"title": "Missing id"}}})
        list_status, list_payload = self.get_json("/tasks")

        self.assertEqual(status, 400)
        self.assertTrue(payload["invalid_input"])
        self.assertIn("task_envelope.id is required", payload["error"])
        self.assertEqual(list_status, 200)
        self.assertEqual(list_payload["tasks"], [])

    def test_submit_rejects_schema_invalid_task_envelope_with_no_persisted_tasks(self) -> None:
        task_id = "e2e-submit-schema-invalid"
        payload = build_create_task_payload(task_id)
        evidence = payload["request"]["task_envelope"]["artifacts"]["completion_evidence"]
        del evidence["validated_at"]
        del evidence["validation_method"]
        del evidence["validator"]

        status, response = self.post_json("/tasks", payload)

        self.assertEqual(status, 400)
        self.assertTrue(response["invalid_input"])
        self.assertIn("Invalid TaskEnvelope:", response["error"])
        self._assert_task_absent(task_id)
