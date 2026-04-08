from __future__ import annotations

from copy import deepcopy
from unittest.mock import patch

from modules.reconciliation_runtime import (
    ReconciliationFailureType,
    ReconciliationHandlerRegistry,
    RetryableReconciliationRuntimeError,
    build_default_reconciliation_registry,
)
from tests.e2e.runtime_harness import RuntimeApiTestCase
from tests.e2e.scenario_builders import (
    build_completion_claim_request,
    build_completion_evidence,
    build_create_task_payload,
    build_execution_attempt_payload,
    build_expected_code_context,
    build_github_facts,
    build_happy_path_overlays,
)


class _FakeGitHubGateway:
    def __init__(
        self,
        *,
        branch_exists: bool = True,
        branch_head_commit_sha: str | None = "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
        branch_exists_error: Exception | None = None,
        default_branch: str = "main",
    ) -> None:
        self._branch_exists = branch_exists
        self._branch_head_commit_sha = branch_head_commit_sha
        self._branch_exists_error = branch_exists_error
        self._default_branch = default_branch

    def branch_exists(self, *, owner: str, repo: str, branch_name: str) -> bool:
        del owner, repo, branch_name
        if self._branch_exists_error is not None:
            raise self._branch_exists_error
        return self._branch_exists

    def branch_head_commit_sha(self, *, owner: str, repo: str, branch_name: str) -> str | None:
        del owner, repo, branch_name
        if self._branch_exists_error is not None:
            raise self._branch_exists_error
        return self._branch_head_commit_sha

    def commit_exists(self, *, owner: str, repo: str, commit_sha: str) -> bool:
        del owner, repo, commit_sha
        return True

    def default_branch(self, *, owner: str, repo: str) -> str | None:
        del owner, repo
        return self._default_branch

    def find_pull_requests_by_branch(
        self,
        *,
        owner: str,
        repo: str,
        branch_name: str,
    ) -> tuple:
        del owner, repo, branch_name
        return ()

    def find_pull_requests_by_commit(
        self,
        *,
        owner: str,
        repo: str,
        commit_sha: str,
    ) -> tuple:
        del owner, repo, commit_sha
        return ()

    def create_pull_request(
        self,
        *,
        owner: str,
        repo: str,
        title: str,
        body: str,
        head: str,
        base: str,
    ):
        del owner, repo, title, body, head, base
        raise AssertionError("create_pull_request should not be called in failure-flow tests")

    def get_pull_request(
        self,
        *,
        owner: str,
        repo: str,
        number: int,
    ):
        del owner, repo, number
        return None


def _registry_with_gateway(gateway: _FakeGitHubGateway) -> ReconciliationHandlerRegistry:
    registry = build_default_reconciliation_registry()
    missing_pr_handler = registry.get(ReconciliationFailureType.MISSING_PR_AFTER_EXECUTION)
    missing_commit_handler = registry.get(ReconciliationFailureType.MISSING_COMMIT_AFTER_EXECUTION)
    registry.register(
        ReconciliationFailureType.MISSING_PR_AFTER_EXECUTION,
        missing_pr_handler.__class__(github=gateway),
    )
    registry.register(
        ReconciliationFailureType.MISSING_COMMIT_AFTER_EXECUTION,
        missing_commit_handler.__class__(github=gateway),
    )
    return registry


class ControlPlaneFailureFlowTests(RuntimeApiTestCase):
    def _mark_task_assigned(self, task_id: str, *, executor_id: str) -> None:
        self.service.store.update_task(
            {
                **deepcopy(self.service.store.get_task(task_id)),
                "status": "assigned",
                "assigned_executor": {
                    "executor_type": "codex",
                    "executor_id": executor_id,
                    "assignment_reason": "Seed assigned state for control-plane failure flow coverage.",
                },
            }
        )

    def test_invalid_execution_attempt_contract_violation_is_auditable_end_to_end(self) -> None:
        scenario = self.create_task_scenario(
            build_create_task_payload(
                "e2e-failure-invalid-execution",
                title="Invalid execution attempt remains auditable",
            )
        )
        self._mark_task_assigned(scenario.task_id, executor_id="executor-invalid-attempt-1")

        overlays = build_happy_path_overlays()
        invalid_attempt = build_execution_attempt_payload(
            attempt_id="attempt-work-branch-1",
            branch_name="work",
            artifact_references=[
                {
                    "reference_id": "attempt-work-branch-1:commit",
                    "artifact_type": "commit",
                    "location": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/commit/8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                    "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                    "metadata": {
                        "repository_host": "github.com",
                        "repository_owner": "KnoxAnalytics",
                        "repository_name": "HARNESS-DRYRUN",
                        "branch_name": "work",
                        "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                    },
                }
            ],
        )
        new_artifacts = deepcopy(overlays["linked_artifacts"])
        new_artifacts[0]["branch"]["name"] = "work"
        external_facts = deepcopy(overlays["external_facts"])
        external_facts["expected_code_context"]["branch_name"] = "work"
        external_facts["github_facts"]["branch"]["name"] = "work"

        with patch.dict("os.environ", {"HARNESS_INVALID_EXECUTION_RETRY_BUDGET": "1"}):
            claimed = scenario.completion_claim(
                build_completion_claim_request(
                    claim_id="claim-work-branch-1",
                    attempt_id="attempt-work-branch-1",
                    execution_attempt=invalid_attempt,
                    new_artifacts=new_artifacts,
                    completion_evidence=overlays["completion_evidence"],
                    external_facts=external_facts,
                    runtime_facts=overlays["runtime_facts"],
                )
            )

        self.assertEqual(claimed.response["action"], "contract_violation_failed")
        self.assertEqual(claimed.task["status"], "failed")
        self.assertEqual(claimed.read_model["task"]["current_status"], "failed")
        self.assertEqual(claimed.read_model["task"]["failure_summary"]["failure_type"], "contract_violation")
        self.assertEqual(
            claimed.response["contract_violation"]["validation"]["rule_failures"][0]["rule"],
            "reserved_shared_branch",
        )
        self.assertEqual(
            claimed.read_model["task"]["execution_summary"]["latest_attempt_validation"]["rule_failures"][0]["rule"],
            "reserved_shared_branch",
        )
        self.assertEqual(
            claimed.response["task_envelope"]["observability"]["execution_metadata"]["execution_attempts"][-1]["metadata"][
                "attempt_validation"
            ]["failure_type"],
            "contract_violation",
        )
        execution_attempt_events = [
            event for event in claimed.timeline["timeline"] if event["event_type"] == "execution_attempt_recorded"
        ]
        self.assertTrue(execution_attempt_events)
        self.assertEqual(
            execution_attempt_events[-1]["details"]["attempt_validation"]["rule_failures"][0]["rule"],
            "reserved_shared_branch",
        )

    def test_missing_pr_reconciliation_terminal_failure_is_visible_across_surfaces(self) -> None:
        self.set_reconciliation_registry(_registry_with_gateway(_FakeGitHubGateway(branch_exists=False)))
        scenario = self.create_task_scenario(
            build_create_task_payload(
                "e2e-failure-missing-pr-terminal",
                title="Missing PR reconciliation terminal failure remains visible",
            )
        )
        self._mark_task_assigned(scenario.task_id, executor_id="executor-reconcile-terminal-1")

        claimed = scenario.completion_claim(
            build_completion_claim_request(
                claim_id="claim-valid-no-pr-terminal-1",
                attempt_id="attempt-valid-no-pr-terminal-1",
                external_facts={
                    "expected_code_context": build_expected_code_context(),
                    "github_facts": build_github_facts(),
                },
            )
        )

        self.assertEqual(claimed.response["action"], "reconciliation_terminal_failed")
        self.assertEqual(claimed.task["status"], "failed")
        self.assertEqual(claimed.task["reconciliation"]["status"], "failed")
        self.assertEqual(claimed.response["reconciliation_attempt"]["failure_type"], "missing_pr_after_execution")
        self.assertEqual(claimed.read_model["task"]["current_status"], "failed")
        status_changes = [event for event in claimed.timeline["timeline"] if event["event_type"] == "status_transition"]
        self.assertTrue(any(event["details"]["to_status"] == "reconciling" for event in status_changes))
        self.assertTrue(any(event["details"]["to_status"] == "failed" for event in status_changes))

    def test_missing_pr_reconciliation_retryable_block_is_visible_across_surfaces(self) -> None:
        self.set_reconciliation_registry(
            _registry_with_gateway(
                _FakeGitHubGateway(
                    branch_exists_error=RetryableReconciliationRuntimeError(
                        "GitHub API request failed for /repos/KnoxAnalytics/HARNESS-DRYRUN/branches/codex%2Fe2e-test: HTTP 502 bad gateway"
                    )
                )
            )
        )
        scenario = self.create_task_scenario(
            build_create_task_payload(
                "e2e-failure-missing-pr-blocked",
                title="Missing PR reconciliation retryable block remains visible",
            )
        )
        self._mark_task_assigned(scenario.task_id, executor_id="executor-reconcile-blocked-1")

        claimed = scenario.completion_claim(
            build_completion_claim_request(
                claim_id="claim-valid-no-pr-blocked-1",
                attempt_id="attempt-valid-no-pr-blocked-1",
                external_facts={
                    "expected_code_context": build_expected_code_context(),
                    "github_facts": build_github_facts(),
                },
            )
        )

        self.assertEqual(claimed.response["action"], "reconciliation_blocked")
        self.assertEqual(claimed.task["status"], "blocked")
        self.assertEqual(claimed.response["target_status"], "blocked")
        self.assertEqual(
            claimed.response["reconciliation_attempt"]["details"]["error_disposition"],
            "blocked_retryable",
        )
        self.assertEqual(claimed.read_model["task"]["current_status"], "blocked")
        status_changes = [event for event in claimed.timeline["timeline"] if event["event_type"] == "status_transition"]
        self.assertTrue(any(event["details"]["to_status"] == "reconciling" for event in status_changes))
        self.assertTrue(any(event["details"]["to_status"] == "blocked" for event in status_changes))
