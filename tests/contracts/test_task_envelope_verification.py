from __future__ import annotations

import copy
import unittest

from modules.contracts.task_envelope_evidence import validate_task_evidence
from modules.contracts.task_envelope_verification import (
    ReconciliationFacts,
    ReconciliationStatus,
    RuntimeVerificationFacts,
    VerificationDecisionInput,
    VerificationInputError,
    VerificationOutcome,
    evaluate_verification_decision,
)


def _base_task_envelope() -> dict:
    return {
        "id": "task-verify-1",
        "title": "Verify canonical completion policy",
        "description": "Task used to validate verification decision primitives.",
        "origin": {
            "source_system": "openclaw",
            "source_type": "ingress_request",
            "source_id": "req-verify-1",
            "ingress_id": None,
            "ingress_name": "OpenClaw",
            "requested_by": None,
        },
        "status": "executing",
        "timestamps": {
            "created_at": "2026-03-24T16:00:00Z",
            "updated_at": "2026-03-24T16:15:00Z",
            "completed_at": None,
        },
        "status_history": [],
        "objective": {
            "summary": "Validate verification outcome behavior.",
            "deliverable_type": "code_change",
            "success_signal": "Verification returns the correct structured outcome.",
        },
        "constraints": [],
        "acceptance_criteria": [
            {
                "id": "ac-1",
                "description": "Completion is backed by verified repository evidence.",
                "required": True,
            }
        ],
        "parent_task_id": None,
        "child_task_ids": [],
        "dependencies": [],
        "assigned_executor": {
            "executor_type": "codex",
            "executor_id": "executor-1",
            "assignment_reason": "Task requires code changes.",
        },
        "required_capabilities": [],
        "priority": "normal",
        "artifacts": {
            "items": [
                {
                    "id": "artifact-pr-1",
                    "type": "pull_request",
                    "title": "Implement verification primitives",
                    "description": None,
                    "location": "https://github.com/example/harness/pull/100",
                    "content_type": None,
                    "external_id": "PR-100",
                    "commit_sha": None,
                    "pull_request_number": 100,
                    "review_state": "approved",
                    "provenance": {
                        "source_system": "github",
                        "source_type": "api",
                        "source_id": "pull/100",
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
                        "name": "codex/verification-primitives",
                        "base_branch": "main",
                        "head_commit_sha": "abcdef1234567890",
                    },
                    "changed_files": [],
                    "external_refs": [
                        {
                            "system": "github",
                            "id": "pull/100",
                            "url": "https://github.com/example/harness/pull/100",
                        }
                    ],
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
                    "external_refs": [
                        {
                            "system": "github",
                            "id": "commit/abcdef1234567890",
                            "url": "https://github.com/example/harness/commit/abcdef1234567890",
                        }
                    ],
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
    acceptance_criteria_satisfied: bool = True,
    runtime_facts: RuntimeVerificationFacts | None = None,
    reconciliation_facts: ReconciliationFacts | None = None,
    unresolved_conditions: tuple[str, ...] = (),
    review_reasons: tuple[str, ...] = (),
):
    evidence_result = validate_task_evidence(task_envelope)
    return evaluate_verification_decision(
        task_envelope,
        decision_input=VerificationDecisionInput(
            claimed_completion=claimed_completion,
            acceptance_criteria_satisfied=acceptance_criteria_satisfied,
            evidence_result=evidence_result,
            runtime_facts=runtime_facts or RuntimeVerificationFacts(executor_reported_success=True, attempt_count=1),
            reconciliation_facts=reconciliation_facts or ReconciliationFacts(status=ReconciliationStatus.PASSED),
            unresolved_conditions=unresolved_conditions,
            review_reasons=review_reasons,
        ),
    )


class VerificationDecisionPrimitiveTests(unittest.TestCase):
    def test_accepts_claimed_completion_with_sufficient_evidence(self) -> None:
        result = _evaluate(_base_task_envelope())

        self.assertEqual(result.outcome, VerificationOutcome.ACCEPTED_COMPLETION)
        self.assertEqual(result.target_status, "completed")
        self.assertTrue(result.accepted_completion)
        self.assertTrue(result.verification_passed)

    def test_returns_insufficient_evidence_when_validated_evidence_is_not_sufficient(self) -> None:
        task_envelope = _base_task_envelope()
        task_envelope["artifacts"]["completion_evidence"]["required_artifact_types"].append("review_note")

        result = _evaluate(task_envelope)

        self.assertEqual(result.outcome, VerificationOutcome.INSUFFICIENT_EVIDENCE)
        self.assertEqual(result.target_status, "blocked")
        self.assertFalse(result.accepted_completion)

    def test_returns_external_mismatch_when_reconciliation_conflicts(self) -> None:
        result = _evaluate(
            _base_task_envelope(),
            reconciliation_facts=ReconciliationFacts(
                status=ReconciliationStatus.MISMATCH,
                blocking=True,
                terminal=False,
                reasons=("GitHub branch does not match expected task branch.",),
            ),
        )

        self.assertEqual(result.outcome, VerificationOutcome.EXTERNAL_MISMATCH)
        self.assertEqual(result.target_status, "blocked")
        self.assertFalse(result.is_terminal)

    def test_returns_review_required_when_manual_review_is_needed(self) -> None:
        result = _evaluate(
            _base_task_envelope(),
            review_reasons=("Acceptance criteria require human judgment.",),
        )

        self.assertEqual(result.outcome, VerificationOutcome.REVIEW_REQUIRED)
        self.assertTrue(result.requires_review)
        self.assertEqual(result.target_status, "blocked")

    def test_returns_blocked_when_verification_conditions_are_unresolved(self) -> None:
        result = _evaluate(
            _base_task_envelope(),
            reconciliation_facts=ReconciliationFacts(status=ReconciliationStatus.PENDING),
            unresolved_conditions=("Required review note has not been attached yet.",),
        )

        self.assertEqual(result.outcome, VerificationOutcome.BLOCKED_UNRESOLVED_CONDITIONS)
        self.assertEqual(result.target_status, "blocked")
        self.assertFalse(result.is_terminal)

    def test_returns_terminal_invalid_for_terminal_runtime_failure(self) -> None:
        result = _evaluate(
            _base_task_envelope(),
            runtime_facts=RuntimeVerificationFacts(
                executor_reported_success=True,
                executor_reported_failure=True,
                terminal_failure=True,
                attempt_count=2,
                latest_attempt_outcome="failed",
            ),
        )

        self.assertEqual(result.outcome, VerificationOutcome.TERMINAL_INVALID)
        self.assertEqual(result.target_status, "failed")
        self.assertTrue(result.is_terminal)

    def test_rejects_invalid_evidence_inputs_before_policy_evaluation(self) -> None:
        task_envelope = _base_task_envelope()
        task_envelope["artifacts"]["completion_evidence"]["validated_artifact_ids"].append("artifact-missing")
        evidence_result = validate_task_evidence(task_envelope)

        with self.assertRaises(VerificationInputError):
            evaluate_verification_decision(
                task_envelope,
                decision_input=VerificationDecisionInput(
                    claimed_completion=True,
                    acceptance_criteria_satisfied=True,
                    evidence_result=evidence_result,
                    runtime_facts=RuntimeVerificationFacts(executor_reported_success=True),
                    reconciliation_facts=ReconciliationFacts(status=ReconciliationStatus.PASSED),
                ),
            )

    def test_returns_deferred_when_no_completion_claim_is_being_evaluated(self) -> None:
        result = _evaluate(_base_task_envelope(), claimed_completion=False)

        self.assertEqual(result.outcome, VerificationOutcome.VERIFICATION_DEFERRED)
        self.assertIsNone(result.target_status)
        self.assertFalse(result.verification_passed)

    def test_returns_terminal_invalid_for_terminal_external_mismatch(self) -> None:
        result = _evaluate(
            _base_task_envelope(),
            reconciliation_facts=ReconciliationFacts(
                status=ReconciliationStatus.MISMATCH,
                blocking=True,
                terminal=True,
                reasons=("Execution occurred in the wrong repository.",),
            ),
        )

        self.assertEqual(result.outcome, VerificationOutcome.TERMINAL_INVALID)
        self.assertEqual(result.target_status, "failed")
        self.assertTrue(result.is_terminal)


if __name__ == "__main__":
    unittest.main()
