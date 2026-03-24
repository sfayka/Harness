from __future__ import annotations

import copy
import unittest

from modules.contracts.task_envelope_evidence import (
    ArtifactValidationError,
    CompletionEvidenceValidationError,
    assert_valid_artifact_record,
    assert_valid_completion_evidence,
    validate_artifact_record,
    validate_task_evidence,
)


def _base_task_envelope() -> dict:
    return {
        "id": "task-artifacts-1",
        "title": "Verify code-bearing completion evidence",
        "description": "Task used to validate artifact-backed completion evidence behavior.",
        "origin": {
            "source_system": "openclaw",
            "source_type": "ingress_request",
            "source_id": "req-artifacts-1",
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
            "summary": "Validate completion evidence shape.",
            "deliverable_type": "code_change",
            "success_signal": "Evidence validates against the canonical schema.",
        },
        "constraints": [],
        "acceptance_criteria": [
            {
                "id": "ac-1",
                "description": "Task completion is supported by a PR and commit artifact.",
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
            "items": [
                {
                    "id": "artifact-pr-1",
                    "type": "pull_request",
                    "title": "Implement evidence model",
                    "description": "Pull request opened for the evidence-model change set.",
                    "location": "https://github.com/example/harness/pull/99",
                    "content_type": None,
                    "external_id": "PR-99",
                    "commit_sha": None,
                    "pull_request_number": 99,
                    "review_state": "approved",
                    "provenance": {
                        "source_system": "github",
                        "source_type": "api",
                        "source_id": "pull/99",
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
                        "name": "codex/evidence-model",
                        "base_branch": "main",
                        "head_commit_sha": "abcdef1234567890",
                    },
                    "changed_files": [
                        {
                            "path": "schemas/task_envelope.schema.json",
                            "change_type": "modified",
                            "previous_path": None,
                            "additions": 42,
                            "deletions": 3,
                        }
                    ],
                    "external_refs": [
                        {
                            "system": "github",
                            "id": "pull/99",
                            "url": "https://github.com/example/harness/pull/99",
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


class ArtifactValidationPrimitiveTests(unittest.TestCase):
    def test_accepts_valid_commit_artifact(self) -> None:
        artifact = _base_task_envelope()["artifacts"]["items"][1]

        result = validate_artifact_record(artifact)

        self.assertTrue(result.is_valid)
        self.assertEqual(result.issues, ())

    def test_rejects_commit_artifact_with_invalid_sha_shape(self) -> None:
        artifact = copy.deepcopy(_base_task_envelope()["artifacts"]["items"][1])
        artifact["commit_sha"] = "not-a-sha"

        result = validate_artifact_record(artifact)

        self.assertFalse(result.is_valid)
        self.assertTrue(any(issue.code == "schema_validation_error" for issue in result.issues))
        with self.assertRaises(ArtifactValidationError):
            assert_valid_artifact_record(artifact)

    def test_rejects_commit_artifact_missing_semantic_required_field(self) -> None:
        artifact = copy.deepcopy(_base_task_envelope()["artifacts"]["items"][1])
        artifact["commit_sha"] = None

        result = validate_artifact_record(artifact)

        self.assertFalse(result.is_valid)
        self.assertTrue(any(issue.code == "required_artifact_field_missing" for issue in result.issues))


class CompletionEvidenceValidationPrimitiveTests(unittest.TestCase):
    def test_accepts_required_satisfied_evidence_when_validated_artifacts_cover_required_types(self) -> None:
        task_envelope = _base_task_envelope()

        result = validate_task_evidence(task_envelope)

        self.assertTrue(result.is_valid)
        self.assertTrue(result.is_sufficient)
        self.assertEqual(result.missing_required_artifact_types, ())
        self.assertEqual(result.unknown_validated_artifact_ids, ())

    def test_reports_insufficient_evidence_when_required_artifact_types_are_missing(self) -> None:
        task_envelope = _base_task_envelope()
        task_envelope["artifacts"]["completion_evidence"]["required_artifact_types"] = [
            "pull_request",
            "commit",
            "review_note",
        ]

        result = validate_task_evidence(task_envelope)

        self.assertTrue(result.is_valid)
        self.assertFalse(result.is_sufficient)
        self.assertEqual(result.missing_required_artifact_types, ("review_note",))
        self.assertTrue(any(issue.code == "missing_required_artifact_types" for issue in result.issues))

    def test_rejects_satisfied_evidence_with_unknown_validated_artifact_id(self) -> None:
        task_envelope = _base_task_envelope()
        task_envelope["artifacts"]["completion_evidence"]["validated_artifact_ids"].append("artifact-missing")

        result = validate_task_evidence(task_envelope)

        self.assertFalse(result.is_valid)
        self.assertFalse(result.is_sufficient)
        self.assertEqual(result.unknown_validated_artifact_ids, ("artifact-missing",))
        self.assertTrue(any(issue.code == "unknown_validated_artifact_id" for issue in result.issues))
        with self.assertRaises(CompletionEvidenceValidationError):
            assert_valid_completion_evidence(
                task_envelope["artifacts"]["items"],
                task_envelope["artifacts"]["completion_evidence"],
            )

    def test_accepts_structurally_valid_not_applicable_evidence_without_treating_it_as_sufficient(self) -> None:
        task_envelope = _base_task_envelope()
        task_envelope["artifacts"]["completion_evidence"] = {
            "policy": "not_applicable",
            "status": "not_applicable",
            "required_artifact_types": [],
            "validated_artifact_ids": [],
            "validation_method": "none",
            "validated_at": None,
            "validator": None,
            "notes": "No artifact evidence is applicable for this task type.",
        }

        result = validate_task_evidence(task_envelope)

        self.assertTrue(result.is_valid)
        self.assertFalse(result.is_sufficient)
        self.assertEqual(result.issues, ())

    def test_rejects_satisfied_required_evidence_backed_by_unverified_artifact(self) -> None:
        task_envelope = _base_task_envelope()
        task_envelope["artifacts"]["items"][0]["verification_status"] = "informational"

        result = validate_task_evidence(task_envelope)

        self.assertFalse(result.is_valid)
        self.assertFalse(result.is_sufficient)
        self.assertTrue(any(issue.code == "validated_artifact_not_verified" for issue in result.issues))

    def test_rejects_contradictory_not_applicable_policy_shape(self) -> None:
        task_envelope = _base_task_envelope()
        task_envelope["artifacts"]["completion_evidence"] = {
            "policy": "not_applicable",
            "status": "satisfied",
            "required_artifact_types": ["commit"],
            "validated_artifact_ids": ["artifact-commit-1"],
            "validation_method": "none",
            "validated_at": None,
            "validator": None,
            "notes": None,
        }

        result = validate_task_evidence(task_envelope)

        self.assertFalse(result.is_valid)
        self.assertFalse(result.is_sufficient)
        self.assertTrue(any(issue.code == "not_applicable_status_mismatch" for issue in result.issues))
        self.assertTrue(any(issue.code == "not_applicable_requires_no_types" for issue in result.issues))
        self.assertTrue(
            any(issue.code == "not_applicable_requires_no_validated_artifacts" for issue in result.issues)
        )


if __name__ == "__main__":
    unittest.main()
