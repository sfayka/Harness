from __future__ import annotations

import unittest

from modules.contracts.task_envelope_external_facts import (
    ArtifactReferenceFact,
    BranchFact,
    ChangedFileFact,
    ChangedFilesSummary,
    CommitFact,
    ExternalFactValidationError,
    GitHubArtifactFacts,
    LinearFacts,
    LinearProjectFact,
    LinearTaskReference,
    LinearWorkflowFact,
    PullRequestFact,
    RepositoryFact,
    validate_github_facts,
    validate_linear_facts,
)


class NormalizedExternalFactModelTests(unittest.TestCase):
    def test_accepts_valid_normalized_github_facts(self) -> None:
        github_facts = GitHubArtifactFacts(
            artifact_found=True,
            repository=RepositoryFact(host="github.com", owner="sfayka", name="Harness"),
            branch=BranchFact(name="codex/normalized-facts", base_branch="main"),
            commit=CommitFact(sha="abcdef1234567890", url="https://github.com/example/commit/abcdef1234567890"),
            pull_request=PullRequestFact(
                number=123,
                state="open",
                review_state="approved",
                url="https://github.com/example/pull/123",
            ),
            changed_files=ChangedFilesSummary(
                files=(
                    ChangedFileFact(path="schemas/task_envelope.schema.json", change_type="modified", additions=3),
                ),
                matches_expected_scope=True,
            ),
            artifact_refs=(
                ArtifactReferenceFact(
                    artifact_type="pull_request",
                    external_id="PR-123",
                    url="https://github.com/example/pull/123",
                ),
            ),
        )

        validated = validate_github_facts(github_facts)

        self.assertEqual(validated.repository_name, "Harness")
        self.assertEqual(validated.branch_name, "codex/normalized-facts")
        self.assertEqual(validated.review_state, "approved")
        self.assertTrue(validated.pull_request_found)
        self.assertTrue(validated.commit_found)

    def test_rejects_github_facts_when_branch_exists_without_repository(self) -> None:
        github_facts = GitHubArtifactFacts(
            artifact_found=True,
            repository=None,
            branch=BranchFact(name="codex/no-repo"),
        )

        with self.assertRaisesRegex(ExternalFactValidationError, "repository identity"):
            validate_github_facts(github_facts)

    def test_rejects_github_facts_when_artifact_not_found_still_carries_resolved_facts(self) -> None:
        github_facts = GitHubArtifactFacts(
            artifact_found=False,
            repository=RepositoryFact(host="github.com", owner="sfayka", name="Harness"),
        )

        with self.assertRaisesRegex(ExternalFactValidationError, "artifact_found=False"):
            validate_github_facts(github_facts)

    def test_accepts_valid_normalized_linear_facts(self) -> None:
        linear_facts = LinearFacts(
            record_found=True,
            issue_id="lin_123",
            issue_key="HAR-123",
            state="completed",
            workflow=LinearWorkflowFact(workflow_id="wf-1", workflow_name="Done", state_type="completed"),
            project=LinearProjectFact(project_id="proj-1", project_name="Harness"),
            task_reference=LinearTaskReference(harness_task_id="task-completed-1"),
        )

        validated = validate_linear_facts(linear_facts)

        self.assertEqual(validated.issue_key, "HAR-123")
        self.assertEqual(validated.workflow.workflow_name, "Done")
        self.assertEqual(validated.task_reference.harness_task_id, "task-completed-1")

    def test_rejects_linear_facts_missing_issue_identity(self) -> None:
        linear_facts = LinearFacts(
            record_found=True,
            issue_id=None,
            issue_key=None,
            state="in_progress",
        )

        with self.assertRaisesRegex(ExternalFactValidationError, "issue_id or issue_key"):
            validate_linear_facts(linear_facts)

    def test_rejects_linear_facts_when_record_not_found_still_carries_state(self) -> None:
        linear_facts = LinearFacts(
            record_found=False,
            state="completed",
        )

        with self.assertRaisesRegex(ExternalFactValidationError, "record_found=False"):
            validate_linear_facts(linear_facts)


if __name__ == "__main__":
    unittest.main()
