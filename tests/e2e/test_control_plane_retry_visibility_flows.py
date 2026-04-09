from __future__ import annotations

import os
from unittest.mock import patch

from modules.demo_cases import build_demo_request
from tests.e2e.runtime_harness import RuntimeApiTestCase
from tests.e2e.scenario_builders import to_jsonable


class ControlPlaneRetryVisibilityFlowTests(RuntimeApiTestCase):
    def test_retryable_failure_surfaces_bounded_retry_state_across_inspection_surfaces(self) -> None:
        payload = {"request": to_jsonable(build_demo_request("blocked_insufficient_evidence"))}
        payload["request"]["runtime_facts"] = {
            "executor_reported_failure": True,
            "attempt_count": 1,
            "latest_attempt_outcome": "failed",
        }

        with patch.dict(os.environ, {"HARNESS_CLASSIFIED_RETRY_BUDGET": "2"}):
            scenario = self.create_evaluate_scenario(payload)

        event_types = {event["event_type"] for event in scenario.created.timeline["timeline"]}

        self.assertEqual(scenario.created.status, 200)
        self.assertEqual(scenario.created.response["failure_classification"]["category"], "evidence_insufficient")
        self.assertEqual(scenario.created.task["status"], "blocked")
        self.assertEqual(scenario.created.read_model["task"]["current_status"], "blocked")
        self.assertEqual(scenario.created.read_model["task"]["execution_summary"]["retry_count"], 2)
        self.assertEqual(scenario.created.read_model["task"]["execution_summary"]["total_attempts"], 3)
        self.assertEqual(
            scenario.created.read_model["task"]["execution_summary"]["last_failure_type"],
            "evidence_insufficient",
        )
        self.assertTrue(scenario.created.read_model["task"]["execution_summary"]["retry_eligible"])
        self.assertEqual(scenario.created.read_model["task"]["execution_summary"]["failure_state"], "retryable")
        self.assertEqual(len(scenario.created.history["evaluations"]), 3)
        self.assertIn("retry_scheduled", event_types)
        self.assertIn("retry_attempt_started", event_types)
        self.assertIn("retry_attempt_completed", event_types)

    def test_non_retryable_failure_does_not_emit_retry_state_or_retry_events(self) -> None:
        payload = {"request": to_jsonable(build_demo_request("blocked_reconciliation_mismatch"))}

        with patch.dict(os.environ, {"HARNESS_CLASSIFIED_RETRY_BUDGET": "2"}):
            scenario = self.create_evaluate_scenario(payload)

        event_types = {event["event_type"] for event in scenario.created.timeline["timeline"]}

        self.assertEqual(scenario.created.status, 200)
        self.assertEqual(scenario.created.response["failure_classification"]["category"], "reconciliation_mismatch")
        self.assertEqual(scenario.created.task["status"], "blocked")
        self.assertEqual(scenario.created.read_model["task"]["current_status"], "blocked")
        self.assertEqual(scenario.created.read_model["task"]["execution_summary"]["retry_count"], 0)
        self.assertEqual(scenario.created.read_model["task"]["execution_summary"]["total_attempts"], 1)
        self.assertEqual(
            scenario.created.read_model["task"]["execution_summary"]["last_failure_type"],
            "reconciliation_mismatch",
        )
        self.assertFalse(scenario.created.read_model["task"]["execution_summary"]["retry_eligible"])
        self.assertEqual(scenario.created.read_model["task"]["execution_summary"]["failure_state"], "terminal")
        self.assertEqual(len(scenario.created.history["evaluations"]), 1)
        self.assertNotIn("retry_scheduled", event_types)
        self.assertNotIn("retry_attempt_started", event_types)
        self.assertNotIn("retry_attempt_completed", event_types)
