"""Tests for the deterministic Symphony-like substrate dry run."""

from __future__ import annotations

import contextlib
import io
import json
import unittest

from modules.execution_substrate_dryrun import (
    main,
    run_symphony_intent_consumer_dry_run,
    run_symphony_substrate_dry_run,
)


class ExecutionSubstrateDryRunTests(unittest.TestCase):
    def test_symphony_substrate_dry_run_records_events_without_accepting_completion(self) -> None:
        result = run_symphony_substrate_dry_run(task_id="symphony-substrate-dryrun-test-1")

        self.assertEqual(result.event_statuses, (200, 200, 200, 200, 200))
        self.assertEqual(result.final_task_status, "intake_ready")
        self.assertFalse(result.accepted_completion)
        self.assertEqual(result.substrate_event_count, 5)
        self.assertEqual(result.latest_event_type, "run_completed_by_executor")
        self.assertEqual(result.latest_runner_session_id, "symphony-dryrun-session-1")
        self.assertEqual(result.latest_workspace_id, "disposable/symphony-substrate-dryrun-test-1")
        self.assertEqual(result.timeline_event_count, 5)

    def test_symphony_intent_consumer_dry_run_polls_intents_and_records_events(self) -> None:
        result = run_symphony_intent_consumer_dry_run(task_id="symphony-intent-consumer-test-1")

        self.assertEqual(result.initial_task_status, "blocked")
        self.assertEqual(result.intent_status, 200)
        self.assertEqual(result.intent_count, 1)
        self.assertEqual(result.consumed_intent_type, "retry_execution")
        self.assertEqual(result.event_statuses, (200, 200))
        self.assertEqual(result.final_task_status, "blocked")
        self.assertFalse(result.accepted_completion)
        self.assertEqual(result.substrate_event_count, 2)
        self.assertEqual(result.latest_event_type, "runner_session_started")

    def test_event_stream_cli_outputs_json_summary(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(["event-stream", "--task-id", "symphony-event-stream-cli-test-1"])
        payload = json.loads(stdout.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["task_id"], "symphony-event-stream-cli-test-1")
        self.assertEqual(payload["event_statuses"], [200, 200, 200, 200, 200])
        self.assertEqual(payload["final_task_status"], "intake_ready")
        self.assertFalse(payload["accepted_completion"])
        self.assertEqual(payload["latest_event_type"], "run_completed_by_executor")

    def test_intent_consumer_cli_outputs_json_summary(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(["intent-consumer", "--task-id", "symphony-intent-cli-test-1"])
        payload = json.loads(stdout.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["task_id"], "symphony-intent-cli-test-1")
        self.assertEqual(payload["intent_status"], 200)
        self.assertEqual(payload["intent_count"], 1)
        self.assertEqual(payload["consumed_intent_type"], "retry_execution")
        self.assertEqual(payload["event_statuses"], [200, 200])
        self.assertEqual(payload["final_task_status"], "blocked")
        self.assertFalse(payload["accepted_completion"])


if __name__ == "__main__":
    unittest.main()
