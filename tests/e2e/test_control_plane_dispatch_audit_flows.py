from __future__ import annotations

from tests.e2e.runtime_harness import RuntimeApiTestCase
from tests.e2e.scenario_builders import (
    build_create_task_payload,
    build_review_decision_from_request,
    build_review_required_payload,
)


class ControlPlaneDispatchAuditFlowTests(RuntimeApiTestCase):
    def _timeline_events(self, scenario, event_type: str) -> list[dict]:
        return [
            event
            for event in scenario.timeline["timeline"]
            if event["event_type"] == event_type
        ]

    def test_automatic_post_ingestion_dispatch_records_durable_attempt_and_trigger(self) -> None:
        payload = build_create_task_payload(
            "e2e-control-automatic-dispatch-audit",
            title="Automatic dispatch audit scenario",
        )
        payload["request"]["task_status"] = "dispatch_ready"

        status, response = self.post_json("/tasks", payload)
        snapshot = self.snapshot_task("e2e-control-automatic-dispatch-audit")

        execution_summary = snapshot.read_model_response["task"]["execution_summary"]
        dispatch_events = [
            event
            for event in snapshot.timeline_response["timeline"]
            if event["event_type"] == "task_dispatched"
        ]
        execution_attempt_events = [
            event
            for event in snapshot.timeline_response["timeline"]
            if event["event_type"] == "execution_attempt_recorded"
        ]
        execution_event_events = [
            event
            for event in snapshot.timeline_response["timeline"]
            if event["event_type"] == "execution_event_recorded"
        ]

        self.assertEqual(status, 200)
        self.assertTrue(response["automatic_dispatch"]["attempted"])
        self.assertEqual(response["automatic_dispatch"]["status"], 200)
        self.assertEqual(response["automatic_dispatch"]["dispatch"]["attempt_id"], "attempt-1")
        self.assertEqual(execution_summary["attempt_count"], 1)
        self.assertEqual(execution_summary["latest_dispatch_origin"], "automatic")
        self.assertEqual(execution_summary["latest_attempt"]["attempt_id"], "attempt-1")
        self.assertEqual(
            execution_summary["latest_attempt"]["metadata"]["dispatch_trigger"],
            "automatic_policy_post_ingestion",
        )
        self.assertEqual(len(dispatch_events), 1)
        self.assertEqual(dispatch_events[0]["details"]["dispatch_trigger"], "automatic_policy_post_ingestion")
        self.assertEqual(dispatch_events[0]["details"]["dispatch_mode"], "automatic")
        self.assertEqual(len(execution_attempt_events), 1)
        self.assertEqual(execution_attempt_events[0]["details"]["attempt_id"], "attempt-1")
        self.assertGreaterEqual(len(execution_event_events), 1)
        self.assertGreaterEqual(len(snapshot.history_response["evaluations"]), 1)

    def test_manual_dispatch_records_durable_attempt_and_trigger(self) -> None:
        scenario = self.create_task_scenario(
            build_create_task_payload(
                "e2e-control-manual-dispatch-audit",
                title="Manual dispatch audit scenario",
            )
        )

        scenario.mutate_task(
            lambda task: task.update(
                {
                    "status": "assigned",
                    "assigned_executor": {
                        "executor_type": "codex",
                        "executor_id": "executor-dispatch-audit-1",
                        "assignment_reason": "Seed assigned state for manual dispatch audit.",
                    },
                }
            )
        )

        dispatched = scenario.dispatch({"request": {"executor": "codex"}})

        dispatch_events = self._timeline_events(dispatched, "task_dispatched")
        execution_attempt_events = self._timeline_events(dispatched, "execution_attempt_recorded")
        execution_event_events = self._timeline_events(dispatched, "execution_event_recorded")
        execution_summary = dispatched.read_model["task"]["execution_summary"]

        self.assertEqual(dispatched.status, 200)
        self.assertEqual(dispatched.response["dispatch"]["attempt_id"], "attempt-1")
        self.assertEqual(execution_summary["attempt_count"], 1)
        self.assertEqual(execution_summary["latest_dispatch_origin"], "manual")
        self.assertEqual(execution_summary["latest_attempt"]["attempt_id"], "attempt-1")
        self.assertEqual(execution_summary["latest_attempt"]["metadata"]["dispatch_trigger"], "manual_api")
        self.assertEqual(len(dispatch_events), 1)
        self.assertEqual(dispatch_events[0]["details"]["dispatch_trigger"], "manual_api")
        self.assertEqual(dispatch_events[0]["details"]["dispatch_mode"], "manual")
        self.assertEqual(len(execution_attempt_events), 1)
        self.assertEqual(execution_attempt_events[0]["details"]["attempt_id"], "attempt-1")
        self.assertGreaterEqual(len(execution_event_events), 1)
        self.assertGreaterEqual(len(dispatched.history["evaluations"]), 1)

    def test_manual_review_authorized_redispatch_updates_latest_attempt_and_trigger(self) -> None:
        initial_payload = build_review_required_payload(
            build_create_task_payload(
                "e2e-control-redispatch-audit",
                title="Manual review redispatch audit scenario",
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

        dispatch_events = self._timeline_events(resolved, "task_dispatched")
        execution_attempt_events = self._timeline_events(resolved, "execution_attempt_recorded")
        execution_summary = resolved.read_model["task"]["execution_summary"]

        self.assertEqual(resolved.status, 200)
        self.assertTrue(resolved.response["automatic_dispatch"]["attempted"])
        self.assertEqual(resolved.response["automatic_dispatch"]["status"], 200)
        self.assertEqual(resolved.response["automatic_dispatch"]["dispatch"]["attempt_id"], "attempt-2")
        self.assertEqual(execution_summary["attempt_count"], 2)
        self.assertEqual(execution_summary["latest_dispatch_origin"], "automatic")
        self.assertEqual(execution_summary["latest_attempt"]["attempt_id"], "attempt-2")
        self.assertEqual(
            execution_summary["latest_attempt"]["metadata"]["dispatch_trigger"],
            "manual_review_authorize_redispatch",
        )
        self.assertTrue(
            any(event["details"]["dispatch_trigger"] == "manual_review_authorize_redispatch" for event in dispatch_events)
        )
        self.assertTrue(
            any(event["details"]["attempt_id"] == "attempt-2" for event in execution_attempt_events)
        )
        self.assertGreaterEqual(len(resolved.history["evaluations"]), 2)
