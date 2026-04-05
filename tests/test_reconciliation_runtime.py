from __future__ import annotations

import io
import unittest
from unittest.mock import patch
from urllib import error

from modules.intake import create_task_envelope
from modules.reconciliation_runtime import (
    GitHubRestPullRequestGateway,
    ReconciliationRuntimeError,
    RetryableReconciliationRuntimeError,
    _resolved_code_context,
)


class GitHubRestPullRequestGatewayTests(unittest.TestCase):
    def test_branch_exists_raises_retryable_error_on_http_500(self) -> None:
        gateway = GitHubRestPullRequestGateway(token="test-token")
        http_error = error.HTTPError(
            url="https://api.github.com/repos/KnoxAnalytics/HARNESS-DRYRUN/branches/codex%2Fe2e-test",
            code=500,
            msg="Server Error",
            hdrs=None,
            fp=io.BytesIO(b'{"message":"bad gateway"}'),
        )

        with patch("modules.reconciliation_runtime.request.urlopen", side_effect=http_error):
            with self.assertRaises(RetryableReconciliationRuntimeError) as captured:
                gateway.branch_exists(
                    owner="KnoxAnalytics",
                    repo="HARNESS-DRYRUN",
                    branch_name="codex/e2e-test",
                )

        self.assertIn("HTTP 500", str(captured.exception))

    def test_branch_exists_raises_retryable_error_on_transport_failure(self) -> None:
        gateway = GitHubRestPullRequestGateway(token="test-token")

        with patch(
            "modules.reconciliation_runtime.request.urlopen",
            side_effect=error.URLError("timed out"),
        ):
            with self.assertRaises(RetryableReconciliationRuntimeError) as captured:
                gateway.branch_exists(
                    owner="KnoxAnalytics",
                    repo="HARNESS-DRYRUN",
                    branch_name="codex/e2e-test",
                )

        self.assertIn("timed out", str(captured.exception))


class ResolveCodeContextTests(unittest.TestCase):
    def test_rejects_conflicting_sources_instead_of_picking_first_available(self) -> None:
        task = create_task_envelope(
            {
                "id": "task-context-conflict-1",
                "title": "Reject conflicting reconciliation context",
                "description": "Exercise conflict detection across reconciliation context sources.",
                "origin": {
                    "source_system": "openclaw",
                    "source_type": "ingress_request",
                    "source_id": "req-context-conflict-1",
                },
                "acceptance_criteria": [
                    {
                        "id": "ac-1",
                        "description": "Harness rejects conflicting reconciliation context.",
                        "required": True,
                    }
                ],
            },
            now="2026-04-05T10:00:00Z",
        )
        task["artifacts"]["items"] = [
            {
                "id": "artifact-commit-1",
                "type": "commit",
                "location": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/commit/8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                "repository": {
                    "host": "github.com",
                    "owner": "KnoxAnalytics",
                    "name": "HARNESS-DRYRUN",
                },
                "branch": {
                    "name": "codex/e2e-test",
                    "base_branch": "main",
                    "head_commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                },
            }
        ]
        external_facts = {
            "expected_code_context": {
                "repository_host": "github.com",
                "repository_owner": "KnoxAnalytics",
                "repository_name": "HARNESS-DRYRUN",
                "branch_name": "codex/conflicting-branch",
                "base_branch": "main",
            },
            "github_facts": {
                "repository": {
                    "host": "github.com",
                    "owner": "KnoxAnalytics",
                    "name": "HARNESS-DRYRUN",
                },
                "branch": {
                    "name": "codex/conflicting-branch",
                    "base_branch": "main",
                    "head_commit_sha": "1111111111111111111111111111111111111111",
                },
                "commit": {
                    "sha": "1111111111111111111111111111111111111111",
                },
            },
        }

        with self.assertRaises(ReconciliationRuntimeError) as captured:
            _resolved_code_context(task, external_facts=external_facts)

        self.assertIn("Conflicting reconciliation code context across sources", str(captured.exception))
