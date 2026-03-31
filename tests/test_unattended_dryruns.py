from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from modules.runtime_scenario_builders import CANONICAL_UNATTENDED_SCENARIOS
from modules.unattended_dryruns import (
    E2ESuiteResult,
    RequestResult,
    RunnerSessionState,
    build_task_id,
    classify_outcome,
    classify_unexpected_failure,
    execute_scenario_with_policy,
    summarize_run,
)


class UnattendedDryRunTests(unittest.TestCase):
    def test_canonical_unattended_scenarios_match_expected_names_and_outcomes(self) -> None:
        scenarios = {scenario.name: scenario.expected_outcome for scenario in CANONICAL_UNATTENDED_SCENARIOS}

        self.assertEqual(list(scenarios), ["happy_path", "mismatch", "review_required"])
        self.assertEqual(
            scenarios["happy_path"],
            {"accepted_completion": True, "final_status": "completed", "requires_review": False},
        )
        self.assertEqual(
            scenarios["mismatch"],
            {"accepted_completion": False, "final_status": "failed", "requires_review": False},
        )
        self.assertEqual(
            scenarios["review_required"],
            {"accepted_completion": False, "final_status": "in_review", "requires_review": True},
        )

    def test_build_task_id_includes_scenario_timestamp_and_suffix(self) -> None:
        task_id = build_task_id(
            "review_required",
            at=datetime(2026, 4, 1, 12, 30, tzinfo=timezone.utc),
            suffix="abc123",
        )

        self.assertEqual(task_id, "dryrun-review-required-20260401T123000Z-abc123")

    def test_classify_outcome_distinguishes_expected_success_and_semantic_failure(self) -> None:
        matched, outcome_class = classify_outcome(
            {"accepted_completion": True, "final_status": "completed", "requires_review": False},
            {"accepted_completion": True, "final_status": "completed", "requires_review": False},
        )
        self.assertTrue(matched)
        self.assertEqual(outcome_class, "expected_success")

        matched, outcome_class = classify_outcome(
            {"accepted_completion": False, "final_status": "in_review", "requires_review": True},
            {"accepted_completion": False, "final_status": "in_review", "requires_review": True},
        )
        self.assertTrue(matched)
        self.assertEqual(outcome_class, "expected_semantic_failure")

        matched, outcome_class = classify_outcome(
            {"accepted_completion": True, "final_status": "completed", "requires_review": False},
            {"accepted_completion": False, "final_status": "blocked", "requires_review": False},
        )
        self.assertFalse(matched)
        self.assertEqual(outcome_class, "unexpected_failure")

    def test_classify_unexpected_failure_detects_transient_and_regression_cases(self) -> None:
        transient = classify_unexpected_failure(
            {
                "create_http_status": None,
                "evaluate_http_status": None,
                "fetch_http_status": None,
                "error": "Connection refused",
                "expected_outcome_matched": False,
                "attempt_error_stage": None,
            }
        )
        self.assertEqual(transient.category, "transient_transport")
        self.assertTrue(transient.retryable)

        regression = classify_unexpected_failure(
            {
                "create_http_status": 200,
                "evaluate_http_status": 200,
                "fetch_http_status": 200,
                "error": None,
                "expected_outcome_matched": False,
                "attempt_error_stage": None,
            }
        )
        self.assertEqual(regression.category, "unexpected_runtime_regression")
        self.assertFalse(regression.retryable)

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

    def test_execute_scenario_with_policy_retries_transient_failure_then_succeeds(self) -> None:
        scenario = CANONICAL_UNATTENDED_SCENARIOS[0]
        transient_entry = {
            "timestamp": "2026-04-01T12:30:00Z",
            "scenario": scenario.name,
            "task_id": "task-1",
            "create_http_status": None,
            "evaluate_http_status": None,
            "fetch_http_status": None,
            "accepted_completion": None,
            "verification_passed": None,
            "reconciliation_status": None,
            "requires_review": None,
            "final_status": None,
            "action": None,
            "error": "Connection refused",
            "mismatch_categories": [],
            "duration_ms": 1000,
            "raw_files": {},
            "attempt_error_stage": None,
        }
        success_entry = {
            "timestamp": "2026-04-01T12:30:05Z",
            "scenario": scenario.name,
            "task_id": "task-1",
            "create_http_status": 200,
            "evaluate_http_status": 200,
            "fetch_http_status": 200,
            "accepted_completion": True,
            "verification_passed": True,
            "reconciliation_status": "passed",
            "requires_review": False,
            "final_status": "completed",
            "action": "transition_applied",
            "error": None,
            "mismatch_categories": [],
            "duration_ms": 900,
            "raw_files": {},
            "attempt_error_stage": None,
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("modules.unattended_dryruns.run_scenario_once", side_effect=[transient_entry, success_entry]):
                with patch("modules.unattended_dryruns.warm_backend", return_value=(True, ["runs/raw/retry-health.json"])):
                    with patch("modules.unattended_dryruns.run_e2e_suite") as run_e2e_suite:
                        result = execute_scenario_with_policy(
                            client=object(),
                            scenario=scenario,
                            output_dir=Path(temp_dir),
                            session_state=RunnerSessionState(),
                            health_retries=2,
                            health_backoff_seconds=0.01,
                            max_retries=2,
                            diagnostics_enabled=True,
                            max_e2e_suite_runs=1,
                        )

        self.assertEqual(result["outcome_class"], "expected_success")
        self.assertEqual(result["classification"], "none")
        self.assertEqual(result["retry_count"], 1)
        self.assertEqual(result["retry_result"], "succeeded_after_retry")
        self.assertFalse(result["e2e_suite_run"])
        run_e2e_suite.assert_not_called()

    def test_execute_scenario_with_policy_runs_e2e_and_report_for_runtime_regression(self) -> None:
        scenario = CANONICAL_UNATTENDED_SCENARIOS[0]
        regression_entry = {
            "timestamp": "2026-04-01T12:30:00Z",
            "scenario": scenario.name,
            "task_id": "task-1",
            "create_http_status": 200,
            "evaluate_http_status": 200,
            "fetch_http_status": 200,
            "accepted_completion": False,
            "verification_passed": False,
            "reconciliation_status": "passed",
            "requires_review": False,
            "final_status": "blocked",
            "action": "transition_applied",
            "error": None,
            "mismatch_categories": [],
            "duration_ms": 1000,
            "raw_files": {},
            "attempt_error_stage": None,
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("modules.unattended_dryruns.run_scenario_once", return_value=regression_entry):
                with patch(
                    "modules.unattended_dryruns.run_e2e_suite",
                    return_value=E2ESuiteResult(
                        ran=True,
                        passed=False,
                        exit_code=1,
                        output_path="runs/reports/e2e-suite.txt",
                    ),
                ):
                    with patch(
                        "modules.unattended_dryruns.write_diagnostic_report",
                        return_value="runs/reports/happy-path-report.json",
                    ):
                        result = execute_scenario_with_policy(
                            client=object(),
                            scenario=scenario,
                            output_dir=Path(temp_dir),
                            session_state=RunnerSessionState(),
                            health_retries=2,
                            health_backoff_seconds=0.01,
                            max_retries=2,
                            diagnostics_enabled=True,
                            max_e2e_suite_runs=1,
                        )

        self.assertEqual(result["outcome_class"], "unexpected_failure")
        self.assertEqual(result["classification"], "unexpected_runtime_regression")
        self.assertEqual(result["retry_count"], 0)
        self.assertEqual(result["retry_result"], "not_retryable")
        self.assertTrue(result["e2e_suite_run"])
        self.assertFalse(result["e2e_suite_passed"])
        self.assertEqual(result["report_path"], "runs/reports/happy-path-report.json")


if __name__ == "__main__":
    unittest.main()
