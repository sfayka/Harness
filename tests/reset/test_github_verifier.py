from __future__ import annotations

import unittest

from modules.reset.github_verifier import ResetGitHubVerifier


class FakeGitHubClient:
    def __init__(self) -> None:
        self.branch_exists_result = True
        self.commit_exists_result = True
        self.pull_request_payload = {
            "number": 42,
            "html_url": "https://github.com/sfayka/Harness/pull/42",
            "state": "open",
            "merged_at": None,
            "head": {
                "ref": "codex/reset-verifier-v1",
                "sha": "abc123",
                "repo": {"owner": {"login": "sfayka"}, "name": "Harness"},
            },
        }

    def branch_exists(self, owner: str, repo: str, branch_name: str) -> bool:
        return self.branch_exists_result

    def commit_exists(self, owner: str, repo: str, commit_sha: str) -> bool:
        return self.commit_exists_result

    def get_pull_request(self, owner: str, repo: str, pull_request_number: int) -> dict | None:
        return self.pull_request_payload


class ResetGitHubVerifierTests(unittest.TestCase):
    def test_returns_verified_done_for_matching_claim(self) -> None:
        verifier = ResetGitHubVerifier(client=FakeGitHubClient())

        verdict = verifier.verify(
            expected_owner="sfayka",
            expected_repo="Harness",
            expected_branch="codex/reset-verifier-v1",
            branch_name="codex/reset-verifier-v1",
            commit_sha="abc123",
            pull_request_number=42,
            pull_request_url="https://github.com/sfayka/Harness/pull/42",
            claimed_owner="sfayka",
            claimed_repo="Harness",
        )

        self.assertEqual(verdict.status, "verified_done")

    def test_rejects_wrong_sha(self) -> None:
        verifier = ResetGitHubVerifier(client=FakeGitHubClient())

        verdict = verifier.verify(
            expected_owner="sfayka",
            expected_repo="Harness",
            expected_branch="codex/reset-verifier-v1",
            branch_name="codex/reset-verifier-v1",
            commit_sha="wrong",
            pull_request_number=42,
        )

        self.assertEqual(verdict.status, "retryable_invalid_proof")
        self.assertIn("sha", verdict.reason)

    def test_rejects_missing_remote_branch(self) -> None:
        client = FakeGitHubClient()
        client.branch_exists_result = False
        verifier = ResetGitHubVerifier(client=client)

        verdict = verifier.verify(
            expected_owner="sfayka",
            expected_repo="Harness",
            expected_branch="codex/reset-verifier-v1",
            branch_name="codex/reset-verifier-v1",
            commit_sha="abc123",
            pull_request_number=42,
        )

        self.assertEqual(verdict.status, "retryable_invalid_proof")
        self.assertIn("branch", verdict.reason)

