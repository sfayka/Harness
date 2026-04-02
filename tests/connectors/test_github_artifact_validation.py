from __future__ import annotations

import unittest

from modules.connectors.github_artifact_validation import (
    GitHubArtifactLookup,
    validate_github_artifact_references,
)
from modules.contracts.execution_advisory import ArtifactReference, ExecutionProvenance
from modules.contracts.task_envelope_external_facts import RepositoryFact


class _FakeLookup(GitHubArtifactLookup):
    def __init__(self, *, prs: set[int] | None = None, commits: set[str] | None = None, branches: set[str] | None = None) -> None:
        self.prs = prs or set()
        self.commits = commits or set()
        self.branches = branches or set()

    def pull_request_exists(self, repository: RepositoryFact, number: int) -> bool:
        return number in self.prs

    def commit_exists(self, repository: RepositoryFact, commit_sha: str) -> bool:
        return commit_sha in self.commits

    def branch_exists(self, repository: RepositoryFact, branch_name: str) -> bool:
        return branch_name in self.branches


def _provenance() -> ExecutionProvenance:
    return ExecutionProvenance(
        source_system="openclaw",
        source_type="executor",
        source_id="attempt-1",
        captured_by="codex",
    )


class GitHubArtifactValidationTests(unittest.TestCase):
    def test_validates_pr_commit_and_branch_against_expected_repository(self) -> None:
        lookup = _FakeLookup(prs={101}, commits={"abc123"}, branches={"codex/github-artifact-validation"})
        artifacts = (
            ArtifactReference(
                artifact_type="pull_request",
                reference_id="pr-ref",
                provenance=_provenance(),
                location="https://github.com/sfayka/Harness/pull/101",
                external_id="PR-101",
            ),
            ArtifactReference(
                artifact_type="commit",
                reference_id="commit-ref",
                provenance=_provenance(),
                location="https://github.com/sfayka/Harness/commit/abc123",
                commit_sha="abc123",
            ),
            ArtifactReference(
                artifact_type="branch",
                reference_id="branch-ref",
                provenance=_provenance(),
                location="https://github.com/sfayka/Harness/tree/codex/github-artifact-validation",
                external_id="codex/github-artifact-validation",
            ),
        )

        result = validate_github_artifact_references(
            artifacts,
            expected_repository=RepositoryFact(host="github.com", owner="sfayka", name="Harness"),
            lookup=lookup,
        )

        self.assertTrue(result.is_valid)
        self.assertEqual(len(result.item_results), 3)
        self.assertTrue(all(item.exists for item in result.item_results))

    def test_detects_missing_artifact(self) -> None:
        result = validate_github_artifact_references(
            (
                ArtifactReference(
                    artifact_type="pull_request",
                    reference_id="pr-ref",
                    provenance=_provenance(),
                    location="https://github.com/sfayka/Harness/pull/999",
                    external_id="PR-999",
                ),
            ),
            expected_repository=RepositoryFact(host="github.com", owner="sfayka", name="Harness"),
            lookup=_FakeLookup(prs={101}),
        )

        self.assertFalse(result.is_valid)
        self.assertFalse(result.item_results[0].exists)
        self.assertEqual(result.item_results[0].issues[-1].code, "artifact_not_found")

    def test_detects_wrong_repository(self) -> None:
        result = validate_github_artifact_references(
            (
                ArtifactReference(
                    artifact_type="commit",
                    reference_id="commit-ref",
                    provenance=_provenance(),
                    location="https://github.com/other/OtherRepo/commit/abc123",
                    commit_sha="abc123",
                ),
            ),
            expected_repository=RepositoryFact(host="github.com", owner="sfayka", name="Harness"),
            lookup=_FakeLookup(commits={"abc123"}),
        )

        self.assertFalse(result.is_valid)
        self.assertFalse(result.item_results[0].repository_matches)
        self.assertEqual(result.item_results[0].issues[0].code, "wrong_repository")

    def test_detects_mismatched_identifiers(self) -> None:
        result = validate_github_artifact_references(
            (
                ArtifactReference(
                    artifact_type="pull_request",
                    reference_id="pr-ref",
                    provenance=_provenance(),
                    location="https://github.com/sfayka/Harness/pull/101",
                    external_id="PR-202",
                ),
            ),
            expected_repository=RepositoryFact(host="github.com", owner="sfayka", name="Harness"),
            lookup=_FakeLookup(prs={101, 202}),
        )

        self.assertFalse(result.is_valid)
        self.assertFalse(result.item_results[0].identity_matches)
        self.assertEqual(result.item_results[0].issues[0].code, "mismatched_identifier")


if __name__ == "__main__":
    unittest.main()
