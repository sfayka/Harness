from __future__ import annotations

from tests.e2e.runtime_harness import RuntimeApiTestCase
from tests.e2e.scenario_builders import (
    build_linear_ingress_payload,
    build_manual_ingress_payload,
    build_openclaw_ingress_payload,
)


class ControlPlaneIngressBoundaryFlowTests(RuntimeApiTestCase):
    def _assert_task_absent(self, task_id: str) -> None:
        task_status, task_payload = self.get_json(f"/tasks/{task_id}")
        self.assertEqual(task_status, 404)
        self.assertIn("not found", task_payload["error"].lower())

    def test_manual_ingress_rejects_completion_and_execution_shaped_handoffs(self) -> None:
        completion_task_id = "e2e-manual-invalid-completion"
        payload = build_manual_ingress_payload(task_id=completion_task_id)
        payload["acceptance_criteria_satisfied"] = True

        status, response = self.post_json("/ingress/manual", payload)

        self.assertEqual(status, 400)
        self.assertTrue(response["invalid_input"])
        self.assertIn("cannot assert acceptance_criteria_satisfied", response["error"].lower())
        self._assert_task_absent(completion_task_id)

        runtime_task_id = "e2e-manual-invalid-runtime"
        payload = build_manual_ingress_payload(task_id=runtime_task_id)
        payload["runtime_facts"] = {"attempt_count": 1}

        status, response = self.post_json("/ingress/manual", payload)

        self.assertEqual(status, 400)
        self.assertTrue(response["invalid_input"])
        self.assertIn("cannot submit runtime_facts", response["error"].lower())
        self._assert_task_absent(runtime_task_id)

        artifact_task_id = "e2e-manual-invalid-artifact"
        payload = build_manual_ingress_payload(task_id=artifact_task_id)
        payload["linked_artifacts"] = [{"id": "artifact-pr-1", "type": "pull_request"}]

        status, response = self.post_json("/ingress/manual", payload)

        self.assertEqual(status, 400)
        self.assertTrue(response["invalid_input"])
        self.assertIn("cannot attach repository execution artifacts", response["error"].lower())
        self._assert_task_absent(artifact_task_id)

    def test_manual_ingress_rejects_assignment_truth_without_creating_task(self) -> None:
        assigned_task_id = "e2e-manual-invalid-assigned"
        payload = build_manual_ingress_payload(task_id=assigned_task_id)
        payload["task_status"] = "assigned"

        status, response = self.post_json("/ingress/manual", payload)

        self.assertEqual(status, 400)
        self.assertTrue(response["invalid_input"])
        self.assertIn("task_status must be one of", response["error"].lower())
        self._assert_task_absent(assigned_task_id)

        assignee_task_id = "e2e-manual-invalid-assignee"
        payload = build_manual_ingress_payload(task_id=assignee_task_id)
        payload["assigned_executor"] = {
            "executor_type": "codex",
            "executor_id": "executor-manual-ingress-1",
            "assignment_reason": "Ingress should not assign executors.",
        }

        status, response = self.post_json("/ingress/manual", payload)

        self.assertEqual(status, 400)
        self.assertTrue(response["invalid_input"])
        self.assertIn("cannot pre-assign an executor", response["error"].lower())
        self._assert_task_absent(assignee_task_id)

    def test_linear_ingress_rejects_completion_and_execution_shaped_handoffs(self) -> None:
        completion_task_id = "e2e-linear-invalid-completion"
        payload = build_linear_ingress_payload(task_id=completion_task_id)
        payload["claimed_completion"] = True

        status, response = self.post_json("/ingress/linear", payload)

        self.assertEqual(status, 400)
        self.assertTrue(response["invalid_input"])
        self.assertIn("cannot claim completion", response["error"].lower())
        self._assert_task_absent(completion_task_id)

        runtime_task_id = "e2e-linear-invalid-runtime"
        payload = build_linear_ingress_payload(task_id=runtime_task_id)
        payload["runtime_facts"] = {"attempt_count": 1}

        status, response = self.post_json("/ingress/linear", payload)

        self.assertEqual(status, 400)
        self.assertTrue(response["invalid_input"])
        self.assertIn("cannot submit runtime_facts", response["error"].lower())
        self._assert_task_absent(runtime_task_id)

        artifact_task_id = "e2e-linear-invalid-artifact"
        payload = build_linear_ingress_payload(task_id=artifact_task_id)
        payload["linked_artifacts"] = [{"id": "artifact-pr-1", "type": "pull_request"}]

        status, response = self.post_json("/ingress/linear", payload)

        self.assertEqual(status, 400)
        self.assertTrue(response["invalid_input"])
        self.assertIn("cannot attach repository execution artifacts", response["error"].lower())
        self._assert_task_absent(artifact_task_id)

    def test_linear_ingress_rejects_assignment_truth_without_creating_task(self) -> None:
        assigned_task_id = "e2e-linear-invalid-assigned"
        payload = build_linear_ingress_payload(task_id=assigned_task_id)
        payload["task_status"] = "assigned"

        status, response = self.post_json("/ingress/linear", payload)

        self.assertEqual(status, 400)
        self.assertTrue(response["invalid_input"])
        self.assertIn("task_status must be one of", response["error"].lower())
        self._assert_task_absent(assigned_task_id)

        assignee_task_id = "e2e-linear-invalid-assignee"
        payload = build_linear_ingress_payload(task_id=assignee_task_id)
        payload["assigned_executor"] = {
            "executor_type": "codex",
            "executor_id": "executor-linear-ingress-1",
            "assignment_reason": "Ingress should not assign executors.",
        }

        status, response = self.post_json("/ingress/linear", payload)

        self.assertEqual(status, 400)
        self.assertTrue(response["invalid_input"])
        self.assertIn("cannot pre-assign an executor", response["error"].lower())
        self._assert_task_absent(assignee_task_id)

    def test_openclaw_ingress_rejects_completion_shaped_handoff_without_creating_task(self) -> None:
        task_id = "e2e-openclaw-invalid-completion"
        payload = build_openclaw_ingress_payload(task_id=task_id)
        payload["acceptance_criteria_satisfied"] = True

        status, response = self.post_json("/ingress/openclaw", payload)

        self.assertEqual(status, 400)
        self.assertTrue(response["invalid_input"])
        self.assertIn("cannot assert acceptance_criteria_satisfied", response["error"].lower())
        self._assert_task_absent(task_id)

    def test_openclaw_ingress_rejects_planned_handoff_with_unresolved_conditions(self) -> None:
        task_id = "e2e-openclaw-invalid-planned"
        payload = build_openclaw_ingress_payload(task_id=task_id)
        payload["task"]["status"] = "planned"
        payload["task"]["objective_summary"] = "Produce a routing-ready implementation task."
        payload["task"]["objective_deliverable_type"] = "code_change"
        payload["task"]["objective_success_signal"] = (
            "The task is defined enough to route without clarification."
        )
        payload["metadata"]["plan_summary"] = (
            "Single-task implementation handoff is ready for dispatcher review."
        )
        payload["unresolved_conditions"] = ["Need repo confirmation"]

        status, response = self.post_json("/ingress/openclaw", payload)

        self.assertEqual(status, 400)
        self.assertTrue(response["invalid_input"])
        self.assertIn("cannot include unresolved_conditions", response["error"].lower())
        self._assert_task_absent(task_id)

    def test_openclaw_ingress_rejects_invalid_payload_without_persisting_state(self) -> None:
        task_id = "e2e-openclaw-invalid-payload"
        payload = build_openclaw_ingress_payload(task_id=task_id)
        payload["context"] = "invalid"

        status, response = self.post_json("/ingress/openclaw", payload)

        self.assertEqual(status, 400)
        self.assertTrue(response["invalid_input"])
        self._assert_task_absent(task_id)
