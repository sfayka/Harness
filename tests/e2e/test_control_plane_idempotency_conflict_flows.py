from __future__ import annotations

from tests.e2e.runtime_harness import RuntimeApiTestCase
from tests.e2e.scenario_builders import (
    build_create_task_payload,
    build_linear_ingress_payload,
    build_manual_ingress_payload,
    build_openclaw_ingress_payload,
)


class ControlPlaneIdempotencyConflictFlowTests(RuntimeApiTestCase):
    def _assert_single_persisted_task(self, task_id: str) -> None:
        task_status, task_payload = self.get_json(f"/tasks/{task_id}")
        history_status, history_payload = self.get_json(f"/tasks/{task_id}/evaluations")
        list_status, list_payload = self.get_json("/tasks")

        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["id"], task_id)
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 1)
        self.assertEqual(list_status, 200)
        matching = [task for task in list_payload["tasks"] if task["task_id"] == task_id]
        self.assertEqual(len(matching), 1)

    def test_duplicate_submit_returns_conflict_without_creating_second_task(self) -> None:
        task_id = "e2e-duplicate-submit"
        payload = build_create_task_payload(task_id)

        initial_status, initial_payload = self.post_json("/tasks", payload)
        duplicate_status, duplicate_payload = self.post_json("/tasks", payload)

        self.assertEqual(initial_status, 200)
        self.assertEqual(initial_payload["task_envelope"]["id"], task_id)
        self.assertEqual(duplicate_status, 409)
        self.assertTrue(duplicate_payload["duplicate_task_id"])
        self._assert_single_persisted_task(task_id)

    def test_duplicate_manual_ingress_returns_conflict_without_creating_second_task(self) -> None:
        task_id = "e2e-duplicate-manual-ingress"
        payload = build_manual_ingress_payload(task_id=task_id)

        initial_status, initial_payload = self.post_json("/ingress/manual", payload)
        duplicate_status, duplicate_payload = self.post_json("/ingress/manual", payload)

        self.assertEqual(initial_status, 200)
        self.assertEqual(initial_payload["task_envelope"]["id"], task_id)
        self.assertEqual(duplicate_status, 409)
        self.assertTrue(duplicate_payload["duplicate_task_id"])
        self._assert_single_persisted_task(task_id)

    def test_duplicate_linear_ingress_returns_conflict_without_creating_second_task(self) -> None:
        task_id = "e2e-duplicate-linear-ingress"
        payload = build_linear_ingress_payload(task_id=task_id)

        initial_status, initial_payload = self.post_json("/ingress/linear", payload)
        duplicate_status, duplicate_payload = self.post_json("/ingress/linear", payload)

        self.assertEqual(initial_status, 200)
        self.assertEqual(initial_payload["task_envelope"]["id"], task_id)
        self.assertEqual(duplicate_status, 409)
        self.assertTrue(duplicate_payload["duplicate_task_id"])
        self._assert_single_persisted_task(task_id)

    def test_duplicate_openclaw_ingress_returns_conflict_without_creating_second_task(self) -> None:
        task_id = "e2e-duplicate-openclaw-ingress"
        payload = build_openclaw_ingress_payload(task_id=task_id)

        initial_status, initial_payload = self.post_json("/ingress/openclaw", payload)
        duplicate_status, duplicate_payload = self.post_json("/ingress/openclaw", payload)

        self.assertEqual(initial_status, 200)
        self.assertEqual(initial_payload["task_envelope"]["id"], task_id)
        self.assertEqual(duplicate_status, 409)
        self.assertTrue(duplicate_payload["duplicate_task_id"])
        self._assert_single_persisted_task(task_id)
