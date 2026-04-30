"""Tests for the Symphony-compatible execution substrate handoff adapter."""

from __future__ import annotations

import unittest

from modules.adapters.symphony import SymphonyExecutionSubstrateAdapter
from modules.contracts.execution_substrate import (
    ExecutionSubstrateIntent,
    ExecutionSubstrateIntentType,
    ExecutionSubstrateValidationError,
    build_execution_substrate_intent,
)


class SymphonyExecutionSubstrateAdapterTests(unittest.TestCase):
    def test_render_handoff_preserves_harness_completion_authority(self) -> None:
        intent = build_execution_substrate_intent(
            task_id="task-symphony-1",
            attention_type="retryable_failure",
            suggested_action="retry_or_redispatch",
            reason="Task is retryable.",
        )
        assert intent is not None
        adapter = SymphonyExecutionSubstrateAdapter(harness_base_url="http://127.0.0.1:8765")

        payload = adapter.render_handoff(intent).to_dict()

        self.assertEqual(payload["mode"], "render_only")
        self.assertEqual(payload["intent"]["intent_type"], "retry_execution")
        self.assertTrue(payload["intent"]["advisory_only"])
        self.assertEqual(payload["intent"]["completion_authority"], "harness_verification")
        self.assertEqual(payload["harness_boundary"]["completion_authority"], "harness_verification")
        self.assertFalse(payload["harness_boundary"]["runner_completion_is_truth"])
        self.assertTrue(payload["harness_boundary"]["artifact_verification_required"])
        self.assertEqual(
            payload["callback"]["events_url"],
            "http://127.0.0.1:8765/tasks/task-symphony-1/execution-substrate-events",
        )
        self.assertFalse(payload["metadata"]["safe_to_execute_live"])

    def test_render_handoff_carries_runner_prohibitions(self) -> None:
        intent = build_execution_substrate_intent(
            task_id="task-symphony-2",
            attention_type="stale_active_task",
            suggested_action="investigate_staleness",
            reason="Task is stale.",
        )
        assert intent is not None
        payload = SymphonyExecutionSubstrateAdapter(
            harness_base_url="http://harness.test/",
        ).render_handoff(intent).to_dict()

        self.assertEqual(payload["intent"]["intent_type"], "investigate_or_restart_execution")
        self.assertEqual(payload["runner_policy"]["substrate_kind"], "symphony-compatible")
        self.assertIn("mark_harness_complete", payload["runner_policy"]["prohibited_actions"])
        self.assertIn("move_linear_to_done_as_truth", payload["runner_policy"]["prohibited_actions"])
        self.assertIn("auto_merge_without_policy", payload["runner_policy"]["prohibited_actions"])
        self.assertEqual(
            payload["callback"]["events_url"],
            "http://harness.test/tasks/task-symphony-2/execution-substrate-events",
        )

    def test_render_handoff_rejects_intent_that_transfers_completion_authority(self) -> None:
        intent = ExecutionSubstrateIntent(
            intent_type=ExecutionSubstrateIntentType.RETRY_EXECUTION,
            substrate_kind="symphony-compatible",
            task_id="task-symphony-3",
            source="harness_supervision_queue",
            reason="Task is retryable.",
            suggested_action="retry_or_redispatch",
            events_endpoint="/tasks/task-symphony-3/execution-substrate-events",
            completion_authority="symphony",
        )

        with self.assertRaisesRegex(
            ExecutionSubstrateValidationError,
            "completion_authority=harness_verification",
        ):
            SymphonyExecutionSubstrateAdapter(
                harness_base_url="http://127.0.0.1:8765",
            ).render_handoff(intent)


if __name__ == "__main__":
    unittest.main()
