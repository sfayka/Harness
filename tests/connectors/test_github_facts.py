from __future__ import annotations

import unittest

from modules.connectors.github_facts import (
    GitHubConnectorInputError,
    translate_github_artifact_facts,
    translate_github_artifact_references,
    translate_github_changed_files,
    translate_github_pull_request,
    translate_github_repository,
)
from modules.contracts.task_envelope_reconciliation import (
    ExpectedCodeContext,
    ReconciliationEvaluationInput,
    ReconciliationOutcome,
    evaluate_reconciliation,
)


def _base_task_envelope() -> dict:
    return {
        "id": "task-github-connector-1",
        "title": "Translate GitHub-shaped inputs",
        "description": "Task used to validate GitHub connector scaffolding.",
        "origin": {
            "source_system": "openclaw",
            "source_type": "ingress_request",
            "source_id": "req-github-connector-1",
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
            "summary": "Validate GitHub connector translation.",
            "deliverable_type": "code_change",
            "success_signal": "Normalized GitHub facts can be consumed by reconciliation.",
        },
        "constraints": [],
        "acceptance_criteria": [
            {
                "id": "ac-1",
                "description": "GitHub facts normalize cleanly.",
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
                "validated_artifact_ids": [],
                "validation_method": "external_reconciliation",
                "validated_at": "2026-03-24T16:14:00Z",
                "validator": {
                    "source_system": "harness",
                    "source_type": "verification",
                    "source_id": "verification-run-1",
                    "captured_by": "github-sync",
                },
                "notes": "GitHub facts consumed through connector scaffolding.",
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


class GitHubConnectorScaffoldingTests(unittest.TestCase):
    def test_translates_github_shaped_payload_into_normalized_facts(self) -> None:
        payload = {
            "repository": {
                "name": "Harness",
                "owner": {"login": "sfayka"},
                "node_id": "repo-123",
            },
            "branch": {
                "name": "codex/github-connector",
                "baseRefName": "main",
                "target": {"oid": "abcdef1234567890"},
            },
            "commit": {
                "sha": "abcdef1234567890",
                "html_url": "https://github.com/example/harness/commit/abcdef1234567890",
                "commit": {"message": "Implement connector scaffolding"},
            },
            "pull_request": {
                "number": 321,
                "state": "open",
                "reviewDecision": "approved",
                "html_url": "https://github.com/example/harness/pull/321",
                "merged": False,
            },
            "files": [
                {
                    "filename": "modules/connectors/github_facts.py",
                    "status": "modified",
                    "additions": 120,
                    "deletions": 0,
                }
            ],
        }

        github_facts = translate_github_artifact_facts(payload)

        self.assertEqual(github_facts.repository_name, "Harness")
        self.assertEqual(github_facts.repository_owner, "sfayka")
        self.assertEqual(github_facts.branch_name, "codex/github-connector")
        self.assertEqual(github_facts.review_state, "approved")
        self.assertTrue(github_facts.commit_found)
        self.assertTrue(github_facts.pull_request_found)
        self.assertEqual(len(github_facts.artifact_refs), 2)

    def test_rejects_repository_payload_missing_owner(self) -> None:
        with self.assertRaisesRegex(GitHubConnectorInputError, "repository owner"):
            translate_github_repository({"name": "Harness"})

    def test_rejects_pull_request_payload_missing_number(self) -> None:
        with self.assertRaisesRegex(GitHubConnectorInputError, "pull_request.number"):
            translate_github_pull_request({"state": "open"})

    def test_rejects_changed_files_payload_with_invalid_shape(self) -> None:
        with self.assertRaisesRegex(GitHubConnectorInputError, "files\\[0\\]\\.filename"):
            translate_github_changed_files([{"status": "modified"}])

    def test_artifact_reference_translation_derives_commit_and_pr_refs(self) -> None:
        refs = translate_github_artifact_references(
            {
                "commit": {"sha": "abcdef1234567890"},
                "pull_request": {"number": 321},
            }
        )

        self.assertEqual(len(refs), 2)
        self.assertEqual(refs[0].artifact_type, "pull_request")
        self.assertEqual(refs[1].artifact_type, "commit")

    def test_normalized_connector_output_can_flow_into_reconciliation(self) -> None:
        github_facts = translate_github_artifact_facts(
            {
                "repository": {"name": "Harness", "owner": {"login": "sfayka"}},
                "branch": {"name": "codex/github-connector", "baseRefName": "main"},
                "commit": {"sha": "abcdef1234567890"},
                "pull_request": {"number": 321, "reviewDecision": "approved"},
            }
        )

        result = evaluate_reconciliation(
            _base_task_envelope(),
            reconciliation_input=ReconciliationEvaluationInput(
                claimed_completion=True,
                evidence_policy="required",
                evidence_status="satisfied",
                expected_code_context=ExpectedCodeContext(
                    repository_host="github.com",
                    repository_owner="sfayka",
                    repository_name="Harness",
                    branch_name="codex/github-connector",
                ),
                github_facts=github_facts,
                review_reasons=(),
                pending_reasons=(),
            ),
        )

        self.assertEqual(result.outcome, ReconciliationOutcome.NO_MISMATCH)


if __name__ == "__main__":
    unittest.main()
