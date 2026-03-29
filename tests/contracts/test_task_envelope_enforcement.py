from __future__ import annotations

import unittest

from modules.contracts.task_envelope_enforcement import (
    EnforcementAction,
    EnforcementInput,
    enforce_task_envelope,
)
from modules.contracts.task_envelope_external_facts import (
    BranchFact,
    ChangedFilesSummary,
    CommitFact,
    GitHubArtifactFacts,
    LinearFacts,
    LinearWorkflowFact,
    PullRequestFact,
    RepositoryFact,
)
from modules.contracts.task_envelope_reconciliation import (
    ExpectedCodeContext,
    ReconciliationEvaluationInput,
)
from modules.contracts.task_envelope_review import (
    ReviewOutcome,
    ReviewRequest,
    ReviewTrigger,
    ReviewerIdentity,
    resolve_review_request,
)
from modules.contracts.task_envelope_verification import RuntimeVerificationFacts, VerificationOutcome


def _valid_artifacts() -> dict:
    return {
        "items": [
            {
                "id": "artifact-pr-1",
                "type": "pull_request",
                "title": "Implement integrated enforcement",
                "description": None,
                "location": "https://github.com/example/harness/pull/200",
                "content_type": None,
                "external_id": "PR-200",
                "commit_sha": None,
                "pull_request_number": 200,
                "review_state": "approved",
                "provenance": {
                    "source_system": "github",
                    "source_type": "api",
                    "source_id": "pull/200",
                    "captured_by": "github-sync",
                },
                "verification_status": "verified",
                "repository": {
                    "host": "github.com",
                    "owner": "sfayka",
                    "name": "Harness",
                    "external_id": "repo-123",
                },
                "branch": {
                    "name": "codex/enforcement",
                    "base_branch": "main",
                    "head_commit_sha": "abcdef1234567890",
                },
                "changed_files": [],
                "external_refs": [],
                "captured_at": "2026-03-24T16:10:00Z",
                "metadata": {},
            },
            {
                "id": "artifact-commit-1",
                "type": "commit",
                "title": None,
                "description": None,
                "location": "https://github.com/example/harness/commit/abcdef1234567890",
                "content_type": None,
                "external_id": "commit-abcdef1234567890",
                "commit_sha": "abcdef1234567890",
                "pull_request_number": None,
                "review_state": None,
                "provenance": {
                    "source_system": "github",
                    "source_type": "api",
                    "source_id": "commit/abcdef1234567890",
                    "captured_by": "github-sync",
                },
                "verification_status": "verified",
                "repository": {
                    "host": "github.com",
                    "owner": "sfayka",
                    "name": "Harness",
                    "external_id": "repo-123",
                },
                "branch": None,
                "changed_files": [],
                "external_refs": [],
                "captured_at": "2026-03-24T16:11:00Z",
                "metadata": {},
            },
        ],
        "completion_evidence": {
            "policy": "required",
            "status": "satisfied",
            "required_artifact_types": ["pull_request", "commit"],
            "validated_artifact_ids": ["artifact-pr-1", "artifact-commit-1"],
            "validation_method": "external_reconciliation",
            "validated_at": "2026-03-24T16:14:00Z",
            "validator": {
                "source_system": "harness",
                "source_type": "verification",
                "source_id": "verification-run-1",
                "captured_by": "github-sync",
            },
            "notes": "Artifacts reconciled against GitHub before completion.",
        },
    }


def _base_task(status: str = "executing") -> dict:
    assigned_executor = None
    completed_at = None
    if status in {"executing", "assigned"}:
        assigned_executor = {
            "executor_type": "codex",
            "executor_id": "executor-1",
            "assignment_reason": "Capability match.",
        }
    if status == "completed":
        completed_at = "2026-03-24T16:15:00Z"

    return {
        "id": f"task-{status}-1",
        "title": "Integrated enforcement task",
        "description": "Task used to validate integrated enforcement behavior.",
        "origin": {
            "source_system": "openclaw",
            "source_type": "ingress_request",
            "source_id": "req-enforcement-1",
            "ingress_id": None,
            "ingress_name": "OpenClaw",
            "requested_by": None,
        },
        "status": status,
        "timestamps": {
            "created_at": "2026-03-24T16:00:00Z",
            "updated_at": "2026-03-24T16:05:00Z",
            "completed_at": completed_at,
        },
        "status_history": [],
        "objective": {
            "summary": "Validate integrated enforcement outcomes.",
            "deliverable_type": "code_change",
            "success_signal": "The enforcement flow applies the correct control-plane result.",
        },
        "constraints": [],
        "acceptance_criteria": [
            {
                "id": "ac-1",
                "description": "Completion is backed by valid evidence and reconciliation.",
                "required": True,
            }
        ],
        "parent_task_id": None,
        "child_task_ids": [],
        "dependencies": [],
        "assigned_executor": assigned_executor,
        "required_capabilities": [],
        "priority": "normal",
        "artifacts": _valid_artifacts(),
        "observability": {
            "errors": [],
            "retries": {
                "attempt_count": 0,
                "max_attempts": 0,
                "last_retry_at": None,
            },
            "execution_metadata": {},
        },
    }


def _aligned_reconciliation_input(
    *,
    claimed_completion: bool = True,
    linear_state: str = "completed",
) -> ReconciliationEvaluationInput:
    return ReconciliationEvaluationInput(
        claimed_completion=claimed_completion,
        evidence_policy="required",
        evidence_status="satisfied",
        expected_code_context=ExpectedCodeContext(
            repository_host="github.com",
            repository_owner="sfayka",
            repository_name="Harness",
            branch_name="codex/enforcement",
            base_branch="main",
        ),
        github_facts=GitHubArtifactFacts(
            artifact_found=True,
            repository=RepositoryFact(host="github.com", owner="sfayka", name="Harness"),
            branch=BranchFact(name="codex/enforcement", base_branch="main"),
            commit=CommitFact(sha="abcdef1234567890"),
            pull_request=PullRequestFact(number=200, review_state="approved"),
            changed_files=ChangedFilesSummary(matches_expected_scope=True),
        ),
        linear_facts=LinearFacts(
            record_found=True,
            issue_id="lin-1",
            state=linear_state,
            workflow=LinearWorkflowFact(workflow_id="workflow-linear-1", workflow_name=linear_state),
        ),
    )


def _reviewer() -> ReviewerIdentity:
    return ReviewerIdentity(reviewer_id="operator-1", reviewer_name="Casey Reviewer", authority_role="operator")


class IntegratedEnforcementTests(unittest.TestCase):
    def test_returns_no_op_when_no_relevant_new_facts_exist(self) -> None:
        task = _base_task(status="executing")

        result = enforce_task_envelope(task, enforcement_input=EnforcementInput())

        self.assertEqual(result.action, EnforcementAction.NO_OP)
        self.assertEqual(result.verification_result.outcome, VerificationOutcome.VERIFICATION_DEFERRED)
        self.assertIsNone(result.transition_result)
        self.assertIsNone(result.error)

    def test_claimed_completion_with_valid_evidence_transitions_to_completed(self) -> None:
        task = _base_task(status="executing")

        result = enforce_task_envelope(
            task,
            enforcement_input=EnforcementInput(
                claimed_completion=True,
                acceptance_criteria_satisfied=True,
                runtime_facts=RuntimeVerificationFacts(executor_reported_success=True, attempt_count=1),
                reconciliation_input=_aligned_reconciliation_input(linear_state="in_progress"),
            ),
        )

        self.assertEqual(result.action, EnforcementAction.TRANSITION_APPLIED)
        self.assertEqual(result.target_status, "completed")
        self.assertEqual(result.task_envelope["status"], "completed")
        self.assertEqual(result.verification_result.outcome, VerificationOutcome.ACCEPTED_COMPLETION)

    def test_insufficient_evidence_moves_completed_task_back_to_blocked(self) -> None:
        task = _base_task(status="completed")
        task["artifacts"]["completion_evidence"]["required_artifact_types"].append("review_note")

        result = enforce_task_envelope(
            task,
            enforcement_input=EnforcementInput(
                claimed_completion=True,
                acceptance_criteria_satisfied=True,
                runtime_facts=RuntimeVerificationFacts(executor_reported_success=True),
                reconciliation_input=_aligned_reconciliation_input(),
            ),
        )

        self.assertEqual(result.action, EnforcementAction.TRANSITION_APPLIED)
        self.assertEqual(result.target_status, "blocked")
        self.assertEqual(result.task_envelope["status"], "blocked")
        self.assertEqual(result.verification_result.outcome, VerificationOutcome.INSUFFICIENT_EVIDENCE)

    def test_reconciliation_mismatch_moves_completed_task_back_to_blocked(self) -> None:
        task = _base_task(status="completed")
        reconciliation_input = _aligned_reconciliation_input(linear_state="in_progress")

        result = enforce_task_envelope(
            task,
            enforcement_input=EnforcementInput(
                claimed_completion=True,
                acceptance_criteria_satisfied=True,
                runtime_facts=RuntimeVerificationFacts(executor_reported_success=True),
                reconciliation_input=reconciliation_input,
            ),
        )

        self.assertEqual(result.action, EnforcementAction.TRANSITION_APPLIED)
        self.assertEqual(result.target_status, "blocked")
        self.assertEqual(result.verification_result.outcome, VerificationOutcome.EXTERNAL_MISMATCH)

    def test_task_requiring_manual_review_returns_review_required(self) -> None:
        task = _base_task(status="completed")
        review_request = ReviewRequest(
            review_request_id="review-request-1",
            task_id=task["id"],
            requested_at="2026-03-24T16:20:00Z",
            requested_by="verification",
            trigger=ReviewTrigger.VERIFICATION,
            summary="Completion requires human judgment.",
            presented_sections=("task_state", "evidence", "reconciliation"),
            allowed_outcomes=(ReviewOutcome.ACCEPT_COMPLETION, ReviewOutcome.KEEP_BLOCKED),
        )

        result = enforce_task_envelope(
            task,
            enforcement_input=EnforcementInput(
                claimed_completion=True,
                acceptance_criteria_satisfied=True,
                runtime_facts=RuntimeVerificationFacts(executor_reported_success=True),
                reconciliation_input=_aligned_reconciliation_input(),
                review_reasons=("Acceptance criteria require human judgment.",),
                review_request=review_request,
            ),
        )

        self.assertEqual(result.action, EnforcementAction.REVIEW_REQUIRED)
        self.assertEqual(result.review_request.review_request_id, "review-request-1")
        self.assertEqual(result.verification_result.outcome, VerificationOutcome.REVIEW_REQUIRED)

    def test_review_outcome_can_authorize_follow_up_action(self) -> None:
        task = _base_task(status="blocked")
        review_request = ReviewRequest(
            review_request_id="review-request-2",
            task_id=task["id"],
            requested_at="2026-03-24T16:20:00Z",
            requested_by="operator",
            trigger=ReviewTrigger.RUNTIME_ANOMALY,
            summary="Current assignment should be replaced.",
            presented_sections=("task_state", "runtime_facts"),
            allowed_outcomes=(ReviewOutcome.KEEP_BLOCKED, ReviewOutcome.AUTHORIZE_REDISPATCH),
        )
        review_decision = resolve_review_request(
            review_request,
            review_id="review-1",
            reviewer=_reviewer(),
            outcome=ReviewOutcome.AUTHORIZE_REDISPATCH,
            reasoning="Redispatch is the safest next step.",
        )

        result = enforce_task_envelope(
            task,
            enforcement_input=EnforcementInput(review_decision=review_decision),
        )

        self.assertEqual(result.action, EnforcementAction.FOLLOW_UP_AUTHORIZED)
        self.assertEqual(result.target_status, "dispatch_ready")
        self.assertEqual(result.task_envelope["status"], "dispatch_ready")

    def test_rejects_lifecycle_transition_when_review_outcome_is_not_authorized_for_actor(self) -> None:
        task = _base_task(status="blocked")
        review_request = ReviewRequest(
            review_request_id="review-request-3",
            task_id=task["id"],
            requested_at="2026-03-24T16:20:00Z",
            requested_by="operator",
            trigger=ReviewTrigger.RUNTIME_ANOMALY,
            summary="Try the task again.",
            presented_sections=("task_state", "runtime_facts"),
            allowed_outcomes=(ReviewOutcome.AUTHORIZE_RETRY,),
        )
        review_decision = resolve_review_request(
            review_request,
            review_id="review-2",
            reviewer=_reviewer(),
            outcome=ReviewOutcome.AUTHORIZE_RETRY,
            reasoning="A retry should be attempted.",
        )

        result = enforce_task_envelope(
            task,
            enforcement_input=EnforcementInput(review_decision=review_decision),
        )

        self.assertEqual(result.action, EnforcementAction.TRANSITION_REJECTED)
        self.assertIn("not authorized", result.error)
        self.assertIsNone(result.transition_result)

    def test_distinguishes_no_op_from_transition_rejected(self) -> None:
        no_op_result = enforce_task_envelope(
            _base_task(status="executing"),
            enforcement_input=EnforcementInput(),
        )

        review_request = ReviewRequest(
            review_request_id="review-request-4",
            task_id="task-blocked-1",
            requested_at="2026-03-24T16:20:00Z",
            requested_by="operator",
            trigger=ReviewTrigger.RUNTIME_ANOMALY,
            summary="Try the task again.",
            presented_sections=("task_state", "runtime_facts"),
            allowed_outcomes=(ReviewOutcome.AUTHORIZE_RETRY,),
        )
        rejected_review_decision = resolve_review_request(
            review_request,
            review_id="review-3",
            reviewer=_reviewer(),
            outcome=ReviewOutcome.AUTHORIZE_RETRY,
            reasoning="A retry should be attempted.",
        )
        rejected_result = enforce_task_envelope(
            _base_task(status="blocked"),
            enforcement_input=EnforcementInput(review_decision=rejected_review_decision),
        )

        self.assertEqual(no_op_result.action, EnforcementAction.NO_OP)
        self.assertIsNone(no_op_result.error)
        self.assertEqual(rejected_result.action, EnforcementAction.TRANSITION_REJECTED)
        self.assertIsNotNone(rejected_result.error)

    def test_invalid_evidence_returns_invalid_input(self) -> None:
        task = _base_task(status="completed")
        task["artifacts"]["completion_evidence"]["validated_artifact_ids"].append("artifact-missing")

        result = enforce_task_envelope(
            task,
            enforcement_input=EnforcementInput(
                claimed_completion=True,
                acceptance_criteria_satisfied=True,
                runtime_facts=RuntimeVerificationFacts(executor_reported_success=True),
                reconciliation_input=_aligned_reconciliation_input(),
            ),
        )

        self.assertEqual(result.action, EnforcementAction.INVALID_INPUT)
        self.assertIsNotNone(result.error)


if __name__ == "__main__":
    unittest.main()
