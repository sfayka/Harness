from __future__ import annotations

import unittest
from dataclasses import asdict, is_dataclass
from enum import Enum

from modules.connectors import GitHubSyncInputError, translate_github_sync_reevaluation_payload


def _to_jsonable(value):
    if is_dataclass(value):
        return {key: _to_jsonable(val) for key, val in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _to_jsonable(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    return value


def _github_sync_payload() -> dict:
    return {
        "task_id": "task-github-sync-1",
        "captured_at": "2026-04-13T15:00:00Z",
        "expected_code_context": {
            "repository_host": "github.com",
            "repository_owner": "KnoxAnalytics",
            "repository_name": "HARNESS-DRYRUN",
            "branch_name": "codex/e2e-test",
            "base_branch": "main",
        },
        "github": {
            "repository": {
                "host": "github.com",
                "owner": "KnoxAnalytics",
                "name": "HARNESS-DRYRUN",
                "node_id": "repo-dryrun-1",
            },
            "branch": {
                "name": "codex/e2e-test",
                "baseRefName": "main",
                "target": {"oid": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705"},
            },
            "commit": {
                "sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                "html_url": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/commit/8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                "commit": {"message": "Attach GitHub sync bridge"},
            },
            "pull_request": {
                "number": 2,
                "state": "open",
                "reviewDecision": "approved",
                "html_url": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/pull/2",
                "merged": False,
            },
            "files": [
                {
                    "filename": "modules/api.py",
                    "status": "modified",
                    "additions": 12,
                    "deletions": 1,
                }
            ],
        },
    }


class GitHubSyncTranslationTests(unittest.TestCase):
    def test_translates_github_sync_payload_into_canonical_reevaluation_request(self) -> None:
        canonical_payload = translate_github_sync_reevaluation_payload(_github_sync_payload())

        self.assertEqual(canonical_payload["task_id"], "task-github-sync-1")
        request = canonical_payload["request"]
        self.assertFalse(request["claimed_completion"])
        self.assertFalse(request["acceptance_criteria_satisfied"])
        self.assertEqual(
            request["external_facts"]["expected_code_context"]["branch_name"],
            "codex/e2e-test",
        )
        github_facts = request["external_facts"]["github_facts"]
        self.assertEqual(github_facts["repository"]["name"], "HARNESS-DRYRUN")
        self.assertEqual(github_facts["pull_request"]["number"], 2)
        self.assertEqual(len(request["new_artifacts"]), 4)
        artifact_types = [artifact["type"] for artifact in request["new_artifacts"]]
        self.assertEqual(artifact_types, ["branch", "commit", "pull_request", "changed_file"])
        self.assertTrue(all(artifact["verification_status"] == "verified" for artifact in request["new_artifacts"]))
        self.assertEqual(request["new_artifacts"][2]["changed_files"][0]["path"], "modules/api.py")
        self.assertEqual(request["new_artifacts"][3]["changed_files"][0]["path"], "modules/api.py")

    def test_rejects_runtime_and_completion_shaped_fields(self) -> None:
        payload = _github_sync_payload()
        payload["runtime_facts"] = {"executor_reported_success": True}
        with self.assertRaisesRegex(GitHubSyncInputError, "cannot submit runtime_facts"):
            translate_github_sync_reevaluation_payload(payload)

        payload = _github_sync_payload()
        payload["claimed_completion"] = True
        with self.assertRaisesRegex(GitHubSyncInputError, "cannot claim completion"):
            translate_github_sync_reevaluation_payload(payload)

        payload = _github_sync_payload()
        payload["acceptance_criteria_satisfied"] = True
        with self.assertRaisesRegex(GitHubSyncInputError, "cannot assert acceptance_criteria_satisfied"):
            translate_github_sync_reevaluation_payload(payload)

        payload = _github_sync_payload()
        payload["completion_evidence"] = {"status": "satisfied"}
        with self.assertRaisesRegex(GitHubSyncInputError, "cannot submit completion_evidence"):
            translate_github_sync_reevaluation_payload(payload)

    def test_rejects_string_completion_booleans(self) -> None:
        payload = _github_sync_payload()
        payload["claimed_completion"] = "false"
        with self.assertRaisesRegex(GitHubSyncInputError, "claimed_completion must be a boolean"):
            translate_github_sync_reevaluation_payload(payload)

        payload = _github_sync_payload()
        payload["acceptance_criteria_satisfied"] = "true"
        with self.assertRaisesRegex(
            GitHubSyncInputError,
            "acceptance_criteria_satisfied must be a boolean",
        ):
            translate_github_sync_reevaluation_payload(payload)


if __name__ == "__main__":
    unittest.main()
