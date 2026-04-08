from __future__ import annotations

from copy import deepcopy

from tests.e2e.runtime_harness import RuntimeApiTestCase
from tests.e2e.scenario_builders import build_create_task_payload


class ControlPlaneDependencyFlowTests(RuntimeApiTestCase):
    def _set_task_status(self, task_id: str, status: str) -> None:
        task = deepcopy(self.service.store.get_task(task_id))
        task["status"] = status
        self.service.store.update_task(task)

    def _set_dependencies(self, task_id: str, dependencies: list[dict]) -> None:
        task = deepcopy(self.service.store.get_task(task_id))
        task["dependencies"] = deepcopy(dependencies)
        self.service.store.update_task(task)

    def test_dispatch_ready_submission_does_not_auto_dispatch_when_blocked_on_dependency(self) -> None:
        upstream = self.create_task_scenario(
            build_create_task_payload(
                "e2e-control-upstream-planned",
                title="Upstream dependency task",
            )
        )
        self._set_task_status(upstream.task_id, "planned")

        downstream_payload = build_create_task_payload(
            "e2e-control-downstream-blocked",
            title="Downstream task blocked on upstream dependency",
        )
        downstream_payload["request"]["task_envelope"]["dependencies"] = [
            {
                "task_id": upstream.task_id,
                "dependency_type": "blocks",
                "required_status": "completed",
                "description": "Upstream task must complete first.",
            }
        ]
        downstream_payload["request"]["task_status"] = "dispatch_ready"

        status, response = self.post_json("/tasks", downstream_payload)
        self.assertEqual(status, 200)
        self.assertEqual(response["action"], "no_op")
        self.assertFalse(response["automatic_dispatch"]["attempted"])
        self.assertFalse(response["automatic_dispatch"]["dispatchable"])
        self.assertIn("blocked on dependency", response["automatic_dispatch"]["reason"])

        snapshot = self.snapshot_task("e2e-control-downstream-blocked")
        self.assertEqual(snapshot.task_fetch_response["task"]["status"], "dispatch_ready")
        self.assertEqual(snapshot.read_model_response["task"]["current_status"], "dispatch_ready")
        self.assertEqual(snapshot.read_model_response["task"]["execution_summary"]["attempt_count"], 0)
        self.assertFalse(
            any(event["event_type"] == "task_dispatched" for event in snapshot.timeline_response["timeline"])
        )

    def test_manual_dispatch_rejects_unmet_blocking_dependency_without_recording_attempt(self) -> None:
        upstream = self.create_task_scenario(
            build_create_task_payload(
                "e2e-control-upstream-unmet",
                title="Unmet upstream dependency task",
            )
        )
        self._set_task_status(upstream.task_id, "planned")

        downstream = self.create_task_scenario(
            build_create_task_payload(
                "e2e-control-downstream-manual-blocked",
                title="Assigned downstream task blocked on dependency",
            )
        )
        self._set_dependencies(
            downstream.task_id,
            [
                {
                    "task_id": upstream.task_id,
                    "dependency_type": "blocks",
                    "required_status": "completed",
                }
            ],
        )
        downstream.mutate_task(
            lambda task: task.update(
                {
                    "status": "assigned",
                    "assigned_executor": {
                        "executor_type": "codex",
                        "executor_id": "executor-dependency-blocked-1",
                        "assignment_reason": "Seed assigned state for dependency dispatch rejection.",
                    },
                }
            )
        )

        blocked = downstream.dispatch({"request": {"executor": "codex"}})

        self.assertEqual(blocked.status, 409)
        self.assertIn("blocked on dependency", blocked.response["error"])
        self.assertEqual(blocked.task["status"], "assigned")
        self.assertEqual(blocked.read_model["task"]["current_status"], "assigned")
        self.assertEqual(blocked.read_model["task"]["execution_summary"]["attempt_count"], 0)
        self.assertFalse(
            any(event["event_type"] == "task_dispatched" for event in blocked.timeline["timeline"])
        )

    def test_manual_dispatch_records_real_attempt_once_dependency_is_satisfied(self) -> None:
        upstream = self.create_task_scenario(
            build_create_task_payload(
                "e2e-control-upstream-complete",
                title="Completed upstream dependency task",
            )
        )
        self._set_task_status(upstream.task_id, "completed")

        downstream = self.create_task_scenario(
            build_create_task_payload(
                "e2e-control-downstream-dispatchable",
                title="Dispatchable downstream task after dependency completion",
            )
        )
        self._set_dependencies(
            downstream.task_id,
            [
                {
                    "task_id": upstream.task_id,
                    "dependency_type": "blocks",
                    "required_status": "completed",
                }
            ],
        )
        downstream.mutate_task(
            lambda task: task.update(
                {
                    "status": "assigned",
                    "assigned_executor": {
                        "executor_type": "codex",
                        "executor_id": "executor-dependency-dispatch-1",
                        "assignment_reason": "Seed assigned state for dependency dispatch success.",
                    },
                }
            )
        )

        dispatched = downstream.dispatch({"request": {"executor": "codex"}})

        self.assertEqual(dispatched.status, 200)
        self.assertEqual(dispatched.response["dispatch"]["task_id"], downstream.task_id)
        self.assertEqual(dispatched.response["dispatch"]["attempt_id"], "attempt-1")
        self.assertEqual(dispatched.read_model["task"]["execution_summary"]["attempt_count"], 1)
        self.assertEqual(dispatched.read_model["task"]["execution_summary"]["latest_dispatch_origin"], "manual")
        self.assertTrue(
            any(
                event["event_type"] == "task_dispatched"
                and event["details"]["dispatch_trigger"] == "manual_api"
                for event in dispatched.timeline["timeline"]
            )
        )
