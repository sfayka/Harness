from __future__ import annotations

from copy import deepcopy

from tests.e2e.runtime_harness import RuntimeApiTestCase
from tests.e2e.scenario_builders import build_create_task_payload


class ControlPlaneRelationshipSurfaceFlowTests(RuntimeApiTestCase):
    def _listed_task(self, task_id: str) -> dict:
        status, payload = self.list_tasks()
        self.assertEqual(status, 200)
        return next(task for task in payload["tasks"] if task["task_id"] == task_id)

    def _mark_task_completed(self, task_id: str) -> None:
        task = deepcopy(self.service.store.get_task(task_id))
        task["status"] = "completed"
        self.service.store.update_task(task)

    def test_explicit_parent_child_and_dependency_links_are_visible_across_surfaces(self) -> None:
        parent_payload = build_create_task_payload(
            "e2e-control-parent-relationship",
            title="Parent relationship scenario",
        )
        parent_payload["request"]["task_envelope"]["child_task_ids"] = ["e2e-control-child-relationship"]

        child_payload = build_create_task_payload(
            "e2e-control-child-relationship",
            title="Child relationship scenario",
        )
        child_payload["request"]["task_envelope"]["parent_task_id"] = "e2e-control-parent-relationship"
        child_payload["request"]["task_envelope"]["dependencies"] = [
            {
                "task_id": "e2e-control-parent-relationship",
                "dependency_type": "blocks",
                "required_status": "completed",
                "description": "Parent task must complete before downstream work can run.",
            }
        ]

        parent = self.create_task_scenario(parent_payload)
        child = self.create_task_scenario(child_payload)

        listed_parent = self._listed_task(parent.task_id)
        listed_child = self._listed_task(child.task_id)

        self.assertEqual(parent.created.task["child_task_ids"], ["e2e-control-child-relationship"])
        self.assertEqual(
            parent.created.read_model["task"]["relationships"]["child_task_ids"],
            ["e2e-control-child-relationship"],
        )
        self.assertEqual(
            listed_parent["relationships"]["child_task_ids"],
            ["e2e-control-child-relationship"],
        )

        self.assertEqual(child.created.task["parent_task_id"], "e2e-control-parent-relationship")
        self.assertEqual(
            child.created.read_model["task"]["relationships"]["parent_task_id"],
            "e2e-control-parent-relationship",
        )
        self.assertEqual(
            child.created.read_model["task"]["relationships"]["dependencies"][0]["task_id"],
            "e2e-control-parent-relationship",
        )
        self.assertEqual(
            listed_child["relationships"]["parent_task_id"],
            "e2e-control-parent-relationship",
        )
        self.assertEqual(
            listed_child["relationships"]["dependencies"][0]["required_status"],
            "completed",
        )
        self.assertEqual(child.created.read_model["task"]["execution_summary"]["attempt_count"], 0)
        self.assertEqual(len(parent.created.history["evaluations"]), 1)
        self.assertEqual(len(child.created.history["evaluations"]), 1)

    def test_relationship_links_remain_stable_when_downstream_work_progresses(self) -> None:
        parent_payload = build_create_task_payload(
            "e2e-control-parent-progress",
            title="Parent progress scenario",
        )
        parent_payload["request"]["task_envelope"]["child_task_ids"] = ["e2e-control-child-progress"]

        child_payload = build_create_task_payload(
            "e2e-control-child-progress",
            title="Child progress scenario",
        )
        child_payload["request"]["task_envelope"]["parent_task_id"] = "e2e-control-parent-progress"
        child_payload["request"]["task_envelope"]["dependencies"] = [
            {
                "task_id": "e2e-control-parent-progress",
                "dependency_type": "blocks",
                "required_status": "completed",
            }
        ]

        self.create_task_scenario(parent_payload)
        child = self.create_task_scenario(child_payload)
        self._mark_task_completed("e2e-control-parent-progress")

        child.mutate_task(
            lambda task: task.update(
                {
                    "status": "assigned",
                    "assigned_executor": {
                        "executor_type": "codex",
                        "executor_id": "executor-relationship-progress-1",
                        "assignment_reason": "Seed assigned state for relationship progress coverage.",
                    },
                }
            )
        )
        dispatched = child.dispatch({"request": {"executor": "codex"}})

        listed_child = self._listed_task(child.task_id)
        parent_fetch = self.snapshot_task("e2e-control-parent-progress")

        self.assertEqual(
            dispatched.task["parent_task_id"],
            "e2e-control-parent-progress",
        )
        self.assertEqual(
            dispatched.read_model["task"]["relationships"]["parent_task_id"],
            "e2e-control-parent-progress",
        )
        self.assertEqual(
            dispatched.read_model["task"]["relationships"]["dependencies"][0]["task_id"],
            "e2e-control-parent-progress",
        )
        self.assertEqual(
            listed_child["relationships"]["parent_task_id"],
            "e2e-control-parent-progress",
        )
        self.assertEqual(
            listed_child["relationships"]["dependencies"][0]["task_id"],
            "e2e-control-parent-progress",
        )
        self.assertEqual(listed_child["execution_summary"]["attempt_count"], 1)
        self.assertEqual(
            parent_fetch.read_model_response["task"]["relationships"]["child_task_ids"],
            ["e2e-control-child-progress"],
        )
        self.assertTrue(
            any(event["event_type"] == "task_dispatched" for event in dispatched.timeline["timeline"])
        )
