from __future__ import annotations

import unittest

from modules.contracts.task_envelope_validation import validate_task_envelope


def _base_task_envelope() -> dict:
    return {
        "id": "task-artifacts-1",
        "title": "Verify code-bearing completion evidence",
        "description": "Task used to validate artifact-backed completion schema behavior.",
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


class TaskEnvelopeArtifactSchemaTests(unittest.TestCase):
    def test_accepts_valid_pull_request_and_commit_evidence(self) -> None:
        task_envelope = _base_task_envelope()
        task_envelope["artifacts"]["items"] = [
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
        ]

        errors = validate_task_envelope(task_envelope)
        self.assertEqual(errors, [])

    def test_rejects_pull_request_artifact_missing_repository_context(self) -> None:
        task_envelope = _base_task_envelope()
        task_envelope["artifacts"]["items"] = [
            {
                "id": "artifact-pr-1",
                "type": "pull_request",
                "title": None,
                "description": None,
                "location": "https://github.com/example/harness/pull/99",
                "content_type": None,
                "external_id": "PR-99",
                "commit_sha": None,
                "pull_request_number": 99,
                "review_state": None,
                "provenance": {
                    "source_system": "github",
                    "source_type": "api",
                    "source_id": "pull/99",
                    "captured_by": "github-sync",
                },
                "verification_status": "verified",
                "repository": None,
                "branch": None,
                "changed_files": [],
                "external_refs": [],
                "captured_at": "2026-03-24T16:10:00Z",
                "metadata": {},
            }
        ]

        errors = validate_task_envelope(task_envelope)
        self.assertTrue(errors)
        self.assertTrue(any("/artifacts/items/0/repository" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
