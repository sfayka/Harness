"""Tests for the deterministic Symphony-like substrate dry run."""

from __future__ import annotations

import unittest

from modules.execution_substrate_dryrun import run_symphony_substrate_dry_run


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


if __name__ == "__main__":
    unittest.main()
