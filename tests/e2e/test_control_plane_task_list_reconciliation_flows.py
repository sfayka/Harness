from __future__ import annotations

from copy import deepcopy

from modules.reconciliation_runtime import RetryableReconciliationRuntimeError
from modules.runtime_scenario_builders import (
    build_create_task_payload,
    build_review_decision_from_request,
)
from tests.e2e.runtime_harness import RuntimeApiTestCase
from tests.e2e.scenario_builders import (
    build_completion_claim_request,
    build_expected_code_context,
    build_github_facts,
)
from tests.e2e.test_control_plane_failure_flows import (
    _FakeGitHubGateway as FailureGateway,
    _registry_with_gateway as failure_registry,
)
from tests.test_completion_claim_reconciliation import (
    _FakeGitHubGateway,
    _registry_with_gateway,
)


class ControlPlaneTaskListReconciliationFlowTests(RuntimeApiTestCase):
    def _tasks_by_id(self, payload: dict) -> dict[str, dict]:
        return {item["task_id"]: item for item in payload["tasks"]}

    def _mark_task_assigned(self, task_id: str, *, executor_id: str) -> None:
        self.service.store.update_task(
            {
                **deepcopy(self.service.store.get_task(task_id)),
                "status": "assigned",
                "assigned_executor": {
                    "executor_type": "codex",
                    "executor_id": executor_id,
                    "assignment_reason": "Seed assigned state for task-list reconciliation coverage.",
                },
            }
        )

    def _claim_with_standard_external_facts(self, scenario, *, claim_id: str, attempt_id: str):
        return scenario.completion_claim(
            build_completion_claim_request(
                claim_id=claim_id,
                attempt_id=attempt_id,
                external_facts={
                    "expected_code_context": build_expected_code_context(),
                    "github_facts": build_github_facts(),
                },
            )
        )

    def test_task_list_surfaces_reconciliation_review_gate_as_requested_review_not_failed(self) -> None:
        self.set_reconciliation_registry(
            _registry_with_gateway(
                _FakeGitHubGateway(
                    branch_exists=True,
                    existing_branch_prs=(),
                    existing_commit_prs=(),
                    persisted_created_pr=None,
                )
            )
        )
        scenario = self.create_task_scenario(
            build_create_task_payload(
                "e2e-list-reconciliation-review",
                title="Task list should show reconciliation review gates honestly",
            )
        )
        self._mark_task_assigned(scenario.task_id, executor_id="executor-list-reconciliation-review-1")

        claimed = self._claim_with_standard_external_facts(
            scenario,
            claim_id="claim-list-reconciliation-review-1",
            attempt_id="attempt-list-reconciliation-review-1",
        )
        list_status, list_payload = self.list_tasks()
        entry = self._tasks_by_id(list_payload)[scenario.task_id]

        self.assertEqual(claimed.status, 200)
        self.assertEqual(list_status, 200)
        self.assertEqual(entry["current_status"], "in_review")
        self.assertEqual(entry["review_summary"]["status"], "requested")
        self.assertEqual(entry["review_summary"]["request_count"], 1)
        self.assertEqual(entry["reconciliation_summary"]["status"], "review_required")
        self.assertEqual(entry["reconciliation_summary"]["outcome"], "review_required")
        self.assertEqual(entry["failure_summary"]["failure_type"], "review_required")
        self.assertEqual(entry["failure_summary"]["state"], "review_required")
        self.assertEqual(entry["execution_summary"]["failure_state"], "review_required")
        self.assertEqual(entry["evaluation_summary"]["latest_action"], "review_required")

    def test_task_list_surfaces_retryable_and_terminal_reconciliation_outcomes_distinctly(self) -> None:
        self.set_reconciliation_registry(
            failure_registry(
                FailureGateway(
                    branch_exists_error=RetryableReconciliationRuntimeError(
                        "GitHub API request failed for /repos/KnoxAnalytics/HARNESS-DRYRUN/branches/codex%2Fe2e-test: HTTP 502 bad gateway"
                    )
                )
            )
        )
        blocked = self.create_task_scenario(
            build_create_task_payload(
                "e2e-list-reconciliation-blocked",
                title="Task list should show retryable reconciliation blocks honestly",
            )
        )
        self._mark_task_assigned(blocked.task_id, executor_id="executor-list-reconciliation-blocked-1")
        self._claim_with_standard_external_facts(
            blocked,
            claim_id="claim-list-reconciliation-blocked-1",
            attempt_id="attempt-list-reconciliation-blocked-1",
        )

        self.set_reconciliation_registry(failure_registry(FailureGateway(branch_exists=False)))
        failed = self.create_task_scenario(
            build_create_task_payload(
                "e2e-list-reconciliation-failed",
                title="Task list should show terminal reconciliation failures honestly",
            )
        )
        self._mark_task_assigned(failed.task_id, executor_id="executor-list-reconciliation-failed-1")
        self._claim_with_standard_external_facts(
            failed,
            claim_id="claim-list-reconciliation-failed-1",
            attempt_id="attempt-list-reconciliation-failed-1",
        )

        list_status, list_payload = self.list_tasks()
        tasks = self._tasks_by_id(list_payload)
        blocked_entry = tasks[blocked.task_id]
        failed_entry = tasks[failed.task_id]

        self.assertEqual(list_status, 200)

        self.assertEqual(blocked_entry["current_status"], "blocked")
        self.assertEqual(blocked_entry["reconciliation_summary"]["status"], "pending")
        self.assertEqual(blocked_entry["reconciliation_summary"]["outcome"], "reconciliation_pending")
        self.assertEqual(blocked_entry["failure_summary"]["failure_type"], "reconciliation_mismatch")
        self.assertEqual(blocked_entry["failure_summary"]["state"], "retryable")
        self.assertEqual(blocked_entry["execution_summary"]["failure_state"], "retryable")
        self.assertEqual(blocked_entry["review_summary"]["status"], "none")

        self.assertEqual(failed_entry["current_status"], "failed")
        self.assertEqual(failed_entry["reconciliation_summary"]["status"], "mismatch")
        self.assertEqual(failed_entry["reconciliation_summary"]["outcome"], "terminal_invalid")
        self.assertEqual(failed_entry["failure_summary"]["failure_type"], "reconciliation_mismatch")
        self.assertEqual(failed_entry["failure_summary"]["state"], "terminal")
        self.assertEqual(failed_entry["execution_summary"]["failure_state"], "terminal")
        self.assertEqual(failed_entry["review_summary"]["status"], "none")

    def test_task_list_surfaces_resolved_reconciliation_review_gate_as_resolved_not_active(self) -> None:
        self.set_reconciliation_registry(
            _registry_with_gateway(
                _FakeGitHubGateway(
                    branch_exists=True,
                    existing_branch_prs=(),
                    existing_commit_prs=(),
                    persisted_created_pr=None,
                )
            )
        )
        scenario = self.create_task_scenario(
            build_create_task_payload(
                "e2e-list-reconciliation-review-resolved",
                title="Task list should clear active reconciliation review after manual resolution",
            )
        )
        self._mark_task_assigned(scenario.task_id, executor_id="executor-list-reconciliation-review-resolved-1")

        claimed = self._claim_with_standard_external_facts(
            scenario,
            claim_id="claim-list-reconciliation-review-resolved-1",
            attempt_id="attempt-list-reconciliation-review-resolved-1",
        )
        review_request = claimed.response["evaluation_record"]["result"]["enforcement_result"]["review_request"]
        scenario.reevaluate(
            {
                "request": {
                    "review_decision": build_review_decision_from_request(
                        review_request,
                        outcome="accept_completion",
                    )
                }
            }
        )

        list_status, list_payload = self.list_tasks()
        entry = self._tasks_by_id(list_payload)[scenario.task_id]

        self.assertEqual(list_status, 200)
        self.assertEqual(entry["current_status"], "completed")
        self.assertEqual(entry["review_summary"]["status"], "resolved")
        self.assertEqual(entry["verification_summary"]["outcome"], "review_resolved")
        self.assertFalse(entry["verification_summary"]["requires_review"])
        self.assertTrue(entry["verification_summary"]["accepted_completion"])
        self.assertEqual(entry["reconciliation_summary"]["status"], "resolved")
        self.assertEqual(entry["reconciliation_summary"]["outcome"], "review_resolved")
        self.assertFalse(entry["reconciliation_summary"]["blocking"])
        self.assertEqual(entry["reconciliation_summary"]["resolved_by"], "manual_review")

    def test_task_list_surfaces_reconciliation_redispatch_failure_as_resolved_not_pending(self) -> None:
        self.set_reconciliation_registry(
            _registry_with_gateway(
                _FakeGitHubGateway(
                    branch_exists=True,
                    existing_branch_prs=(),
                    existing_commit_prs=(),
                    persisted_created_pr=None,
                )
            )
        )
        scenario = self.create_task_scenario(
            build_create_task_payload(
                "e2e-list-reconciliation-review-redispatch-failed",
                title="Task list should not project resolved reconciliation redispatch failures as pending review",
            )
        )
        self._mark_task_assigned(scenario.task_id, executor_id="executor-list-reconciliation-review-redispatch-1")

        claimed = self._claim_with_standard_external_facts(
            scenario,
            claim_id="claim-list-reconciliation-review-redispatch-1",
            attempt_id="attempt-list-reconciliation-review-redispatch-1",
        )
        review_request = claimed.response["evaluation_record"]["result"]["enforcement_result"]["review_request"]
        scenario.reevaluate(
            {
                "request": {
                    "review_decision": build_review_decision_from_request(
                        review_request,
                        outcome="authorize_redispatch",
                    )
                }
            }
        )

        list_status, list_payload = self.list_tasks()
        entry = self._tasks_by_id(list_payload)[scenario.task_id]

        self.assertEqual(list_status, 200)
        self.assertEqual(entry["current_status"], "failed")
        self.assertEqual(entry["review_summary"]["status"], "resolved")
        self.assertEqual(entry["verification_summary"]["outcome"], "review_resolved")
        self.assertFalse(entry["verification_summary"]["requires_review"])
        self.assertEqual(entry["verification_summary"]["reconciliation_status"], "resolved")
        self.assertEqual(
            entry["verification_summary"]["failure_classification"]["failure_type"],
            "contract_violation",
        )
        self.assertTrue(entry["verification_summary"]["is_terminal"])
        self.assertEqual(entry["failure_summary"]["failure_type"], "contract_violation")
        self.assertEqual(entry["failure_summary"]["state"], "terminal")
        self.assertEqual(entry["reconciliation_summary"]["status"], "resolved")
        self.assertEqual(entry["reconciliation_summary"]["outcome"], "review_resolved")

    def test_task_list_surfaces_manual_review_mark_failed_as_terminal_failure(self) -> None:
        self.set_reconciliation_registry(
            _registry_with_gateway(
                _FakeGitHubGateway(
                    branch_exists=True,
                    existing_branch_prs=(),
                    existing_commit_prs=(),
                    persisted_created_pr=None,
                )
            )
        )
        scenario = self.create_task_scenario(
            build_create_task_payload(
                "e2e-list-reconciliation-review-mark-failed",
                title="Task list should project manual review failure honestly",
            )
        )
        self._mark_task_assigned(scenario.task_id, executor_id="executor-list-reconciliation-review-failed-1")

        claimed = self._claim_with_standard_external_facts(
            scenario,
            claim_id="claim-list-reconciliation-review-failed-1",
            attempt_id="attempt-list-reconciliation-review-failed-1",
        )
        review_request = claimed.response["evaluation_record"]["result"]["enforcement_result"]["review_request"]
        scenario.reevaluate(
            {
                "request": {
                    "review_decision": build_review_decision_from_request(
                        review_request,
                        outcome="mark_failed",
                    )
                }
            }
        )

        list_status, list_payload = self.list_tasks()
        entry = self._tasks_by_id(list_payload)[scenario.task_id]

        self.assertEqual(list_status, 200)
        self.assertEqual(entry["current_status"], "failed")
        self.assertEqual(entry["review_summary"]["status"], "resolved")
        self.assertEqual(entry["verification_summary"]["outcome"], "review_resolved")
        self.assertEqual(entry["failure_summary"]["state"], "terminal")
        self.assertEqual(entry["failure_summary"]["failure_type"], "manual_review_failed")
        self.assertEqual(entry["failure_summary"]["failure_source"], "manual_review")
        self.assertEqual(entry["execution_summary"]["failure_state"], "terminal")
