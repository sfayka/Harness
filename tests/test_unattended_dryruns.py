from __future__ import annotations

from datetime import datetime, timezone
import unittest

from modules.runtime_scenario_builders import CANONICAL_UNATTENDED_SCENARIOS
from modules.unattended_dryruns import RequestResult, build_task_id, summarize_run


class UnattendedDryRunTests(unittest.TestCase):
    def test_canonical_unattended_scenarios_match_expected_names(self) -> None:
        self.assertEqual(
            [scenario.name for scenario in CANONICAL_UNATTENDED_SCENARIOS],
            ["happy_path", "mismatch", "review_required"],
        )

    def test_build_task_id_includes_scenario_timestamp_and_suffix(self) -> None:
        task_id = build_task_id(
            "review_required",
            at=datetime(2026, 4, 1, 12, 30, tzinfo=timezone.utc),
            suffix="abc123",
        )

        self.assertEqual(task_id, "dryrun-review-required-20260401T123000Z-abc123")

    def test_summarize_run_extracts_required_log_fields(self) -> None:
        summary = summarize_run(
            timestamp="2026-04-01T12:30:00Z",
            scenario="happy_path",
            task_id="dryrun-happy-path-20260401T123000Z-abc123",
            create_result=RequestResult(status=200, payload={"task_envelope": {"id": "task-1"}}),
            evaluate_result=RequestResult(
                status=200,
                payload={
                    "accepted_completion": True,
                    "requires_review": False,
                    "action": "transition_applied",
                    "enforcement_result": {
                        "verification_result": {
                            "verification_passed": True,
                            "reconciliation_status": "passed",
                        },
                        "reconciliation_result": {
                            "status": "passed",
                            "mismatch_categories": [],
                        },
                    },
                },
            ),
            fetch_result=RequestResult(status=200, payload={"task": {"status": "completed"}}),
            duration_ms=1420,
            raw_files={"create_response": "runs/raw/create.json"},
        )

        self.assertEqual(summary["scenario"], "happy_path")
        self.assertEqual(summary["create_http_status"], 200)
        self.assertEqual(summary["evaluate_http_status"], 200)
        self.assertEqual(summary["fetch_http_status"], 200)
        self.assertTrue(summary["accepted_completion"])
        self.assertTrue(summary["verification_passed"])
        self.assertEqual(summary["reconciliation_status"], "passed")
        self.assertFalse(summary["requires_review"])
        self.assertEqual(summary["final_status"], "completed")
        self.assertEqual(summary["action"], "transition_applied")
        self.assertEqual(summary["mismatch_categories"], [])
        self.assertEqual(summary["duration_ms"], 1420)
        self.assertEqual(summary["raw_files"], {"create_response": "runs/raw/create.json"})


if __name__ == "__main__":
    unittest.main()
