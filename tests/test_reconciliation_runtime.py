from __future__ import annotations

import io
import unittest
from unittest.mock import patch
from urllib import error

from modules.reconciliation_runtime import GitHubRestPullRequestGateway, RetryableReconciliationRuntimeError


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
