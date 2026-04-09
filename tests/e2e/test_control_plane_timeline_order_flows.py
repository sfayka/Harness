from __future__ import annotations

from tests.e2e.runtime_harness import RuntimeApiTestCase
from tests.e2e.scenario_builders import (
    build_create_task_payload,
    build_manual_ingress_payload,
)


class ControlPlaneTimelineOrderFlowTests(RuntimeApiTestCase):
    def _event_index(self, timeline: list[dict], event_type: str) -> int:
        for index, event in enumerate(timeline):
            if event["event_type"] == event_type:
                return index
        raise AssertionError(f"Missing timeline event {event_type!r}")

    def _event_indexes(self, timeline: list[dict], event_type: str) -> list[int]:
        return [
            index
            for index, event in enumerate(timeline)
            if event["event_type"] == event_type
        ]

    def test_dispatch_timeline_orders_dispatch_before_execution_attempt_and_status_transitions(self) -> None:
        payload = build_create_task_payload(
            "e2e-timeline-order-dispatch",
            title="Timeline dispatch ordering scenario",
        )
        payload["request"]["task_status"] = "dispatch_ready"

        status, response = self.post_json("/tasks", payload)
        timeline = self.snapshot_task("e2e-timeline-order-dispatch").timeline_response["timeline"]

        self.assertEqual(status, 200)
        self.assertTrue(response["automatic_dispatch"]["attempted"])
        self.assertLess(self._event_index(timeline, "evaluation_recorded"), self._event_index(timeline, "task_dispatched"))
        self.assertLess(self._event_index(timeline, "task_dispatched"), self._event_index(timeline, "execution_event_recorded"))
        self.assertLess(
            self._event_index(timeline, "execution_event_recorded"),
            self._event_index(timeline, "execution_attempt_recorded"),
        )
        self.assertLess(
            self._event_index(timeline, "execution_attempt_recorded"),
            self._event_index(timeline, "status_transition"),
        )

    def test_clarification_timeline_orders_resolution_before_follow_up_dispatch(self) -> None:
        scenario = self.create_manual_ingress_scenario(
            build_manual_ingress_payload(
                task_id="e2e-timeline-order-clarification",
                task_status="dispatch_ready",
                unresolved_conditions=["Need repository clarification before dispatch can begin."],
            )
        )

        resolved = scenario.reevaluate(
            {"request": {"claimed_completion": False, "acceptance_criteria_satisfied": False}}
        )
        timeline = resolved.timeline["timeline"]

        self.assertEqual(resolved.status, 200)
        self.assertTrue(resolved.response["automatic_dispatch"]["attempted"])
        evaluation_indexes = self._event_indexes(timeline, "evaluation_recorded")
        self.assertEqual(len(evaluation_indexes), 3)
        self.assertLess(
            evaluation_indexes[0],
            self._event_index(timeline, "clarification_resolved"),
        )
        self.assertLess(
            self._event_index(timeline, "clarification_resolved"),
            evaluation_indexes[1],
        )
        self.assertLess(
            evaluation_indexes[1],
            self._event_index(timeline, "task_dispatched"),
        )
        self.assertLess(
            self._event_index(timeline, "task_dispatched"),
            self._event_index(timeline, "execution_attempt_recorded"),
        )
        self.assertLess(
            self._event_index(timeline, "execution_attempt_recorded"),
            evaluation_indexes[2],
        )
