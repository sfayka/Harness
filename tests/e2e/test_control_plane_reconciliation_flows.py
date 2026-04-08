from __future__ import annotations

from copy import deepcopy

from tests.e2e.runtime_harness import RuntimeApiTestCase
from tests.e2e.scenario_builders import (
    build_completion_claim_request,
    build_completion_evidence,
    build_create_task_payload,
    build_execution_attempt_payload,
    build_expected_code_context,
    build_github_facts,
    build_linked_artifacts,
)
from tests.test_completion_claim_reconciliation import (
    _FakeGitHubGateway,
    _pull_request,
    _registry_with_gateway,
)


class ControlPlaneReconciliationFlowTests(RuntimeApiTestCase):
    def _mark_task_assigned(self, task_id: str, *, executor_id: str) -> None:
        self.service.store.update_task(
            {
                **deepcopy(self.service.store.get_task(task_id)),
                "status": "assigned",
                "assigned_executor": {
                    "executor_type": "codex",
                    "executor_id": executor_id,
                    "assignment_reason": "Seed assigned state for reconciliation-flow coverage.",
                },
            }
        )

    def test_missing_pr_reconciliation_escalates_to_review_when_created_pr_cannot_be_revalidated(self) -> None:
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
                "e2e-control-reconciliation-review",
                title="Missing PR reconciliation should stay visible when revalidation fails",
            )
        )
        self._mark_task_assigned(scenario.task_id, executor_id="executor-reconcile-review-1")

        claimed = scenario.completion_claim(
            build_completion_claim_request(
                claim_id="claim-no-pr-review-1",
                attempt_id="attempt-no-pr-review-1",
                external_facts={
                    "expected_code_context": build_expected_code_context(),
                    "github_facts": build_github_facts(),
                },
            )
        )

        self.assertEqual(claimed.response["action"], "reconciliation_failed")
        self.assertTrue(claimed.response["requires_review"])
        self.assertEqual(claimed.task["status"], "in_review")
        self.assertEqual(claimed.task["reconciliation"]["active_failure_type"], "missing_pr_after_execution")
        self.assertEqual(claimed.read_model["task"]["current_status"], "in_review")
        self.assertEqual(claimed.read_model["task"]["review_summary"]["status"], "none")
        self.assertEqual(claimed.response["reconciliation_attempt"]["details"]["error_disposition"], "review_required")
        self.assertTrue(
            any(event["event_type"] == "reconciliation_attempt_recorded" for event in claimed.timeline["timeline"])
        )
        self.assertTrue(
            any(
                event["event_type"] == "status_transition" and event["details"]["to_status"] == "in_review"
                for event in claimed.timeline["timeline"]
            )
        )

    def test_self_certified_pr_and_commit_are_reconciled_sequentially_before_completion(self) -> None:
        self.set_reconciliation_registry(
            _registry_with_gateway(
                _FakeGitHubGateway(
                    created_pr=_pull_request(number=401),
                    persisted_created_pr=_pull_request(number=401),
                )
            )
        )
        scenario = self.create_task_scenario(
            build_create_task_payload(
                "e2e-control-reconciliation-chain",
                title="Self-certified execution proof should be replaced by governed reconciliation",
            )
        )
        self._mark_task_assigned(scenario.task_id, executor_id="executor-reconcile-chain-1")

        claimed = scenario.completion_claim(
            build_completion_claim_request(
                claim_id="claim-reconcile-chain-1",
                attempt_id="attempt-reconcile-chain-1",
                execution_attempt=build_execution_attempt_payload(attempt_id="attempt-reconcile-chain-1"),
                new_artifacts=build_linked_artifacts(
                    pr_verification_status="verified",
                    commit_verification_status="verified",
                ),
                completion_evidence=build_completion_evidence(),
                external_facts={
                    "expected_code_context": build_expected_code_context(),
                    "github_facts": build_github_facts(),
                },
                runtime_facts={"executor_reported_success": True, "attempt_count": 1},
            )
        )

        self.assertEqual(claimed.response["action"], "transition_applied")
        self.assertTrue(claimed.response["accepted_completion"])
        self.assertEqual(claimed.task["status"], "completed")
        self.assertEqual(
            [attempt["failure_type"] for attempt in claimed.task["reconciliation"]["attempts"][-2:]],
            ["missing_pr_after_execution", "missing_commit_after_execution"],
        )
        self.assertEqual(claimed.read_model["task"]["current_status"], "completed")
        self.assertEqual(claimed.task["artifacts"]["completion_evidence"]["status"], "satisfied")
        self.assertEqual(
            claimed.task["artifacts"]["completion_evidence"]["validation_method"],
            "external_reconciliation",
        )
        artifact_facts = [
            (artifact["type"], artifact.get("verification_status"), artifact.get("metadata", {}).get("attached_by"))
            for artifact in claimed.task["artifacts"]["items"]
        ]
        self.assertIn(("pull_request", "verified", "missing_pr_after_execution"), artifact_facts)
        self.assertIn(("commit", "verified", "missing_commit_after_execution"), artifact_facts)
        self.assertTrue(
            any(event["event_type"] == "reconciliation_attempt_recorded" for event in claimed.timeline["timeline"])
        )
        self.assertTrue(
            any(
                event["event_type"] == "status_transition" and event["details"]["to_status"] == "completed"
                for event in claimed.timeline["timeline"]
            )
        )

    def test_missing_commit_is_attached_after_verified_pr_proof_exists(self) -> None:
        self.set_reconciliation_registry(
            _registry_with_gateway(
                _FakeGitHubGateway(
                    existing_branch_prs=(),
                    existing_commit_prs=(),
                )
            )
        )
        scenario = self.create_task_scenario(
            build_create_task_payload(
                "e2e-control-reconciliation-missing-commit",
                title="Verified PR proof should allow missing commit reconciliation",
            )
        )
        self._mark_task_assigned(scenario.task_id, executor_id="executor-reconcile-missing-commit-1")

        pr_only = [build_linked_artifacts()[0]]
        claimed = scenario.completion_claim(
            build_completion_claim_request(
                claim_id="claim-missing-commit-1",
                attempt_id="attempt-missing-commit-1",
                execution_attempt=build_execution_attempt_payload(attempt_id="attempt-missing-commit-1"),
                new_artifacts=pr_only,
                completion_evidence={
                    "policy": "required",
                    "status": "satisfied",
                    "required_artifact_types": ["pull_request", "commit"],
                    "validated_artifact_ids": [pr_only[0]["id"]],
                    "validation_method": "external_reconciliation",
                    "validated_at": "2026-04-01T10:02:00Z",
                    "validator": {
                        "source_system": "harness",
                        "source_type": "verification",
                        "source_id": "verification-e2e-1",
                        "captured_by": "harness-api",
                    },
                },
                external_facts={
                    "expected_code_context": build_expected_code_context(),
                    "github_facts": build_github_facts(),
                },
                runtime_facts={"executor_reported_success": True, "attempt_count": 1},
            )
        )

        self.assertEqual(claimed.response["action"], "transition_applied")
        self.assertTrue(claimed.response["accepted_completion"])
        self.assertEqual(claimed.task["status"], "completed")
        self.assertEqual(
            [attempt["failure_type"] for attempt in claimed.task["reconciliation"]["attempts"][-2:]],
            ["missing_pr_after_execution", "missing_commit_after_execution"],
        )
        self.assertEqual(claimed.task["artifacts"]["completion_evidence"]["status"], "satisfied")
        self.assertIn(
            "artifact-commit-8a32c6f29d34",
            claimed.task["artifacts"]["completion_evidence"]["validated_artifact_ids"],
        )
        self.assertTrue(
            any(
                artifact["type"] == "commit"
                and artifact.get("verification_status") == "verified"
                and artifact.get("metadata", {}).get("attached_by") == "missing_commit_after_execution"
                for artifact in claimed.task["artifacts"]["items"]
            )
        )
