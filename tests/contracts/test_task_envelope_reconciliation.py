from __future__ import annotations

import unittest

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
    MismatchCategory,
    ReconciliationEvaluationInput,
    ReconciliationInputError,
    ReconciliationOutcome,
    evaluate_reconciliation,
)
from modules.contracts.task_envelope_verification import ReconciliationStatus


def _base_task_envelope() -> dict:
    return {
        "id": "task-reconcile-1",
        "title": "Reconcile canonical task state",
        "description": "Task used to validate reconciliation decision primitives.",
        "origin": {
            "source_system": "openclaw",
            "source_type": "ingress_request",
            "source_id": "req-reconcile-1",
            "ingress_id": None,
            "ingress_name": "OpenClaw",
            "requested_by": None,
        },
        "status": "completed",
        "timestamps": {
            "created_at": "2026-03-24T16:00:00Z",
            "updated_at": "2026-03-24T16:15:00Z",
            "completed_at": "2026-03-24T16:15:00Z",
        },
        "status_history": [],
        "objective": {
            "summary": "Validate reconciliation outcome behavior.",
            "deliverable_type": "code_change",
            "success_signal": "Reconciliation returns the correct structured outcome.",
        },
        "constraints": [],
        "acceptance_criteria": [
            {
                "id": "ac-1",
                "description": "Completion is backed by GitHub and Linear facts.",
                "required": True,
            }
        ],
        "parent_task_id": None,
        "child_task_ids": [],
        "dependencies": [],
        "assigned_executor": None,
        "required_capabilities": [],
        "priority": "normal",
        "artifacts": {
            "items": [],
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
                "notes": "PR and commit reconciled against GitHub before completion.",
            },
        },
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


def _evaluate(
    task_envelope: dict,
    *,
    claimed_completion: bool = True,
    evidence_policy: str = "required",
    evidence_status: str = "satisfied",
    expected_code_context: ExpectedCodeContext | None = None,
    github_facts: GitHubArtifactFacts | None = None,
    linear_facts: LinearFacts | None = None,
    review_reasons: tuple[str, ...] = (),
    pending_reasons: tuple[str, ...] = (),
):
    return evaluate_reconciliation(
        task_envelope,
        reconciliation_input=ReconciliationEvaluationInput(
            claimed_completion=claimed_completion,
            evidence_policy=evidence_policy,
            evidence_status=evidence_status,
            expected_code_context=expected_code_context,
            github_facts=github_facts,
            linear_facts=linear_facts,
            review_reasons=review_reasons,
            pending_reasons=pending_reasons,
        ),
    )


class ReconciliationPrimitiveTests(unittest.TestCase):
    def test_returns_no_mismatch_when_internal_and_external_facts_align(self) -> None:
        result = _evaluate(
            _base_task_envelope(),
            expected_code_context=ExpectedCodeContext(
                repository_host="github.com",
                repository_owner="sfayka",
                repository_name="Harness",
                branch_name="codex/reconcile",
                base_branch="main",
            ),
            github_facts=GitHubArtifactFacts(
                artifact_found=True,
                repository=RepositoryFact(host="github.com", owner="sfayka", name="Harness"),
                branch=BranchFact(name="codex/reconcile", base_branch="main"),
                commit=CommitFact(sha="abcdef1234567890"),
                pull_request=PullRequestFact(number=100, review_state="approved"),
                changed_files=ChangedFilesSummary(matches_expected_scope=True),
            ),
            linear_facts=LinearFacts(
                record_found=True,
                issue_id="lin-1",
                state="completed",
                workflow=LinearWorkflowFact(workflow_id="workflow-done", workflow_name="completed"),
            ),
        )

        self.assertEqual(result.outcome, ReconciliationOutcome.NO_MISMATCH)
        self.assertEqual(result.status, ReconciliationStatus.PASSED)
        self.assertEqual(result.mismatch_categories, ())

    def test_returns_missing_evidence_for_claimed_completion_without_required_evidence(self) -> None:
        result = _evaluate(_base_task_envelope(), evidence_status="insufficient")

        self.assertEqual(result.outcome, ReconciliationOutcome.MISSING_EVIDENCE)
        self.assertEqual(result.status, ReconciliationStatus.MISMATCH)
        self.assertIn(MismatchCategory.MISSING_VALIDATED_ARTIFACT, result.mismatch_categories)

    def test_returns_missing_evidence_when_expected_github_artifact_is_not_found(self) -> None:
        result = _evaluate(
            _base_task_envelope(),
            github_facts=GitHubArtifactFacts(artifact_found=False),
        )

        self.assertEqual(result.outcome, ReconciliationOutcome.MISSING_EVIDENCE)
        self.assertIn(MismatchCategory.GITHUB_ARTIFACT_NOT_FOUND, result.mismatch_categories)

    def test_returns_wrong_target_for_wrong_repository_or_branch(self) -> None:
        result = _evaluate(
            _base_task_envelope(),
            expected_code_context=ExpectedCodeContext(
                repository_host="github.com",
                repository_owner="sfayka",
                repository_name="Harness",
                branch_name="codex/expected",
            ),
            github_facts=GitHubArtifactFacts(
                artifact_found=True,
                repository=RepositoryFact(host="github.com", owner="other-owner", name="OtherRepo"),
                branch=BranchFact(name="codex/wrong"),
            ),
        )

        self.assertEqual(result.outcome, ReconciliationOutcome.WRONG_TARGET)
        self.assertTrue(result.terminal)
        self.assertIn(MismatchCategory.WRONG_REPOSITORY, result.mismatch_categories)
        self.assertIn(MismatchCategory.WRONG_BRANCH, result.mismatch_categories)

    def test_returns_contradictory_facts_for_linear_status_conflict(self) -> None:
        result = _evaluate(
            _base_task_envelope(),
            linear_facts=LinearFacts(
                record_found=True,
                issue_id="lin-1",
                state="in_progress",
                workflow=LinearWorkflowFact(workflow_id="workflow-active", workflow_name="in_progress"),
            ),
        )

        self.assertEqual(result.outcome, ReconciliationOutcome.CONTRADICTORY_FACTS)
        self.assertEqual(result.status, ReconciliationStatus.MISMATCH)
        self.assertIn(MismatchCategory.LINEAR_STATE_CONFLICT, result.mismatch_categories)

    def test_returns_review_required_for_review_worthy_external_facts(self) -> None:
        result = _evaluate(
            _base_task_envelope(),
            review_reasons=("GitHub and Linear disagree in a way policy cannot resolve automatically.",),
        )

        self.assertEqual(result.outcome, ReconciliationOutcome.REVIEW_REQUIRED)
        self.assertEqual(result.status, ReconciliationStatus.REVIEW_REQUIRED)
        self.assertTrue(result.blocking)

    def test_classifies_missing_linear_record_as_review_required_not_mismatch(self) -> None:
        result = _evaluate(
            _base_task_envelope(),
            linear_facts=LinearFacts(
                record_found=False,
                reasons=("Linear sync has not resolved the matching record identity.",),
            ),
        )

        self.assertEqual(result.outcome, ReconciliationOutcome.REVIEW_REQUIRED)
        self.assertEqual(result.status, ReconciliationStatus.REVIEW_REQUIRED)
        self.assertTrue(result.blocking)
        self.assertIn(MismatchCategory.LINEAR_RECORD_NOT_FOUND, result.mismatch_categories)

    def test_returns_pending_when_reconciliation_facts_are_still_pending(self) -> None:
        result = _evaluate(
            _base_task_envelope(),
            pending_reasons=("GitHub sync has not finished yet.",),
        )

        self.assertEqual(result.outcome, ReconciliationOutcome.RECONCILIATION_PENDING)
        self.assertEqual(result.status, ReconciliationStatus.PENDING)
        self.assertFalse(result.blocking)
        self.assertIn("GitHub sync has not finished yet.", result.reasons)

    def test_returns_contradictory_facts_for_changed_file_and_review_conflict(self) -> None:
        result = _evaluate(
            _base_task_envelope(),
            github_facts=GitHubArtifactFacts(
                artifact_found=True,
                repository=RepositoryFact(host="github.com", owner="sfayka", name="Harness"),
                branch=BranchFact(name="codex/reconcile"),
                pull_request=PullRequestFact(number=100, review_state="changes_requested"),
                changed_files=ChangedFilesSummary(matches_expected_scope=False),
            ),
        )

        self.assertEqual(result.outcome, ReconciliationOutcome.CONTRADICTORY_FACTS)
        self.assertIn(MismatchCategory.GITHUB_REVIEW_CONFLICT, result.mismatch_categories)
        self.assertIn(MismatchCategory.CHANGED_FILES_CONFLICT, result.mismatch_categories)

    def test_converts_result_to_verification_facts(self) -> None:
        result = _evaluate(_base_task_envelope(), evidence_status="insufficient")
        verification_facts = result.to_verification_facts()

        self.assertEqual(verification_facts.status, ReconciliationStatus.MISMATCH)
        self.assertTrue(verification_facts.blocking)
        self.assertFalse(verification_facts.terminal)

    def test_rejects_invalid_input_combinations(self) -> None:
        with self.assertRaises(ReconciliationInputError):
            _evaluate(
                _base_task_envelope(),
                evidence_policy="required",
                evidence_status="not_applicable",
            )

    def test_distinguishes_pending_external_facts_from_missing_evidence(self) -> None:
        pending = _evaluate(
            _base_task_envelope(),
            pending_reasons=("Linear sync has not completed yet.",),
        )
        missing = _evaluate(_base_task_envelope(), evidence_status="insufficient")

        self.assertEqual(pending.outcome, ReconciliationOutcome.RECONCILIATION_PENDING)
        self.assertEqual(pending.status, ReconciliationStatus.PENDING)
        self.assertEqual(missing.outcome, ReconciliationOutcome.MISSING_EVIDENCE)
        self.assertEqual(missing.status, ReconciliationStatus.MISMATCH)
        self.assertIn(MismatchCategory.MISSING_VALIDATED_ARTIFACT, missing.mismatch_categories)


if __name__ == "__main__":
    unittest.main()
