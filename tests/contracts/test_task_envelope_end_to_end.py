from __future__ import annotations

import unittest

from modules.contracts.task_envelope_end_to_end import (
    CanonicalCaseInput,
    build_canonical_fact_bundle,
    build_expected_code_context,
    build_github_completion_facts,
    build_linear_completion_facts,
    enforce_canonical_task_case,
)
from modules.contracts.task_envelope_enforcement import EnforcementAction
from modules.contracts.task_envelope_review import (
    ReviewOutcome,
    ReviewRequest,
    ReviewTrigger,
)
from modules.contracts.task_envelope_verification import RuntimeVerificationFacts, VerificationOutcome


def _valid_artifacts() -> dict:
    return {
        "items": [
            {
                "id": "artifact-pr-1",
                "type": "pull_request",
                "title": "Implement end-to-end enforcement",
                "description": None,
                "location": "https://github.com/example/harness/pull/250",
                "content_type": None,
                "external_id": "PR-250",
                "commit_sha": None,
                "pull_request_number": 250,
                "review_state": "approved",
                "provenance": {
                    "source_system": "github",
                    "source_type": "api",
                    "source_id": "pull/250",
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
                    "name": "codex/end-to-end",
                    "base_branch": "main",
                    "head_commit_sha": "abcdef1234567890",
                },
                "changed_files": [],
                "external_refs": [],
                "captured_at": "2026-03-24T18:10:00Z",
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
                "captured_at": "2026-03-24T18:11:00Z",
                "metadata": {},
            },
        ],
        "completion_evidence": {
            "policy": "required",
            "status": "satisfied",
            "required_artifact_types": ["pull_request", "commit"],
            "validated_artifact_ids": ["artifact-pr-1", "artifact-commit-1"],
            "validation_method": "external_reconciliation",
            "validated_at": "2026-03-24T18:14:00Z",
            "validator": {
                "source_system": "harness",
                "source_type": "verification",
                "source_id": "verification-run-e2e-1",
                "captured_by": "github-sync",
            },
            "notes": "Artifacts reconciled before completion.",
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
        completed_at = "2026-03-24T18:15:00Z"

    return {
        "id": f"task-e2e-{status}-1",
        "title": "End-to-end enforcement task",
        "description": "Task used to validate end-to-end reconciliation and enforcement.",
        "origin": {
            "source_system": "openclaw",
            "source_type": "ingress_request",
            "source_id": "req-e2e-1",
            "ingress_id": None,
            "ingress_name": "OpenClaw",
            "requested_by": None,
        },
        "status": status,
        "timestamps": {
            "created_at": "2026-03-24T18:00:00Z",
            "updated_at": "2026-03-24T18:05:00Z",
            "completed_at": completed_at,
        },
        "status_history": [],
        "objective": {
            "summary": "Validate canonical end-to-end enforcement outcomes.",
            "deliverable_type": "code_change",
            "success_signal": "The control-plane path applies the correct lifecycle outcome.",
        },
        "constraints": [],
        "acceptance_criteria": [
            {
                "id": "ac-1",
                "description": "Completion is backed by valid evidence and normalized external facts.",
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


def _aligned_bundle(*, linear_state: str = "in_progress"):
    return build_canonical_fact_bundle(
        expected_code_context=build_expected_code_context(
            repository_owner="sfayka",
            repository_name="Harness",
            branch_name="codex/end-to-end",
            base_branch="main",
        ),
        github_facts=build_github_completion_facts(
            repository_owner="sfayka",
            repository_name="Harness",
            branch_name="codex/end-to-end",
            base_branch="main",
            pull_request_number=250,
            review_state="approved",
        ),
        linear_facts=build_linear_completion_facts(
            issue_id="lin-e2e-1",
            issue_key="HAR-250",
            state=linear_state,
        ),
    )


class EndToEndEnforcementTests(unittest.TestCase):
    def test_accepts_completion_when_evidence_and_normalized_facts_align(self) -> None:
        task = _base_task(status="executing")

        result = enforce_canonical_task_case(
            task,
            case_input=CanonicalCaseInput(
                claimed_completion=True,
                acceptance_criteria_satisfied=True,
                runtime_facts=RuntimeVerificationFacts(executor_reported_success=True, attempt_count=1),
                external_facts=_aligned_bundle(linear_state="in_progress"),
            ),
        )

        self.assertEqual(result.action, EnforcementAction.TRANSITION_APPLIED)
        self.assertEqual(result.task_envelope["status"], "completed")
        self.assertEqual(result.verification_result.outcome, VerificationOutcome.ACCEPTED_COMPLETION)

    def test_rolls_completed_task_back_to_blocked_for_insufficient_evidence(self) -> None:
        task = _base_task(status="completed")
        task["artifacts"]["completion_evidence"]["required_artifact_types"].append("review_note")

        result = enforce_canonical_task_case(
            task,
            case_input=CanonicalCaseInput(
                claimed_completion=True,
                acceptance_criteria_satisfied=True,
                runtime_facts=RuntimeVerificationFacts(executor_reported_success=True),
                external_facts=_aligned_bundle(linear_state="completed"),
            ),
        )

        self.assertEqual(result.action, EnforcementAction.TRANSITION_APPLIED)
        self.assertEqual(result.task_envelope["status"], "blocked")
        self.assertEqual(result.verification_result.outcome, VerificationOutcome.INSUFFICIENT_EVIDENCE)

    def test_rolls_completed_task_back_to_blocked_for_reconciliation_mismatch(self) -> None:
        task = _base_task(status="completed")

        result = enforce_canonical_task_case(
            task,
            case_input=CanonicalCaseInput(
                claimed_completion=True,
                acceptance_criteria_satisfied=True,
                runtime_facts=RuntimeVerificationFacts(executor_reported_success=True),
                external_facts=_aligned_bundle(linear_state="in_progress"),
            ),
        )

        self.assertEqual(result.action, EnforcementAction.TRANSITION_APPLIED)
        self.assertEqual(result.task_envelope["status"], "blocked")
        self.assertEqual(result.verification_result.outcome, VerificationOutcome.EXTERNAL_MISMATCH)

    def test_returns_review_required_when_normalized_facts_require_human_review(self) -> None:
        task = _base_task(status="completed")
        review_request = ReviewRequest(
            review_request_id="review-request-e2e-1",
            task_id=task["id"],
            requested_at="2026-03-24T18:20:00Z",
            requested_by="verification",
            trigger=ReviewTrigger.RECONCILIATION,
            summary="Linear record requires manual review.",
            presented_sections=("task_state", "evidence", "reconciliation"),
            allowed_outcomes=(ReviewOutcome.ACCEPT_COMPLETION, ReviewOutcome.KEEP_BLOCKED),
        )

        result = enforce_canonical_task_case(
            task,
            case_input=CanonicalCaseInput(
                claimed_completion=True,
                acceptance_criteria_satisfied=True,
                runtime_facts=RuntimeVerificationFacts(executor_reported_success=True),
                external_facts=build_canonical_fact_bundle(
                    expected_code_context=build_expected_code_context(branch_name="codex/end-to-end"),
                    github_facts=build_github_completion_facts(branch_name="codex/end-to-end", pull_request_number=250),
                    linear_facts=build_linear_completion_facts(record_found=False, reasons=("Linear sync has not resolved record identity.",)),
                ),
                review_request=review_request,
            ),
        )

        self.assertEqual(result.action, EnforcementAction.REVIEW_REQUIRED)
        self.assertEqual(result.verification_result.outcome, VerificationOutcome.REVIEW_REQUIRED)
        self.assertEqual(result.review_request.review_request_id, "review-request-e2e-1")
        self.assertEqual(result.task_envelope["status"], "in_review")
        self.assertEqual(result.target_status, "in_review")

    def test_wrong_target_execution_fails_when_normalized_github_facts_point_to_other_branch(self) -> None:
        task = _base_task(status="executing")

        result = enforce_canonical_task_case(
            task,
            case_input=CanonicalCaseInput(
                claimed_completion=True,
                acceptance_criteria_satisfied=True,
                runtime_facts=RuntimeVerificationFacts(executor_reported_success=True),
                external_facts=build_canonical_fact_bundle(
                    expected_code_context=build_expected_code_context(branch_name="codex/end-to-end"),
                    github_facts=build_github_completion_facts(
                        repository_owner="sfayka",
                        repository_name="Harness",
                        branch_name="codex/wrong-branch",
                        pull_request_number=250,
                    ),
                    linear_facts=build_linear_completion_facts(issue_id="lin-e2e-2", state="in_progress"),
                ),
            ),
        )

        self.assertEqual(result.action, EnforcementAction.TRANSITION_APPLIED)
        self.assertEqual(result.task_envelope["status"], "failed")
        self.assertEqual(result.verification_result.outcome, VerificationOutcome.TERMINAL_INVALID)


if __name__ == "__main__":
    unittest.main()
