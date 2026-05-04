from __future__ import annotations

import json
import subprocess
import unittest
from unittest.mock import patch

from scripts.proofline_live_preflight import build_live_preflight_checks


def _completed(command: tuple[str, ...], returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr=stderr)


class ProoflineLivePreflightTests(unittest.TestCase):
    def test_preflight_is_not_ready_without_required_live_credentials(self) -> None:
        with patch("scripts.proofline_live_preflight.shutil.which", return_value=None):
            checks = build_live_preflight_checks(env={})

        by_code = {check.code: check for check in checks}

        self.assertEqual(by_code["linear_api_key"].status, "fail")
        self.assertEqual(by_code["github_env_token"].status, "warn")
        self.assertEqual(by_code["target_guard"].status, "pass")

    def test_preflight_accepts_approved_targets_and_read_only_github_repo(self) -> None:
        def runner(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
            if command[1:] == ("auth", "status"):
                return _completed(command, 0, stdout="ok")
            if command[1:] == ("auth", "token"):
                return _completed(command, 0, stdout="ghp_token\n")
            if command[1:3] == ("repo", "view"):
                return _completed(
                    command,
                    0,
                    stdout=json.dumps(
                        {
                            "nameWithOwner": "sfayka/HARNESS-DRYRUN",
                            "url": "https://github.com/sfayka/HARNESS-DRYRUN",
                            "defaultBranchRef": {"name": "main"},
                            "isPrivate": True,
                        }
                    ),
                )
            return _completed(command, 1, stderr="unexpected")

        with patch("scripts.proofline_live_preflight.shutil.which", return_value="/usr/bin/gh"):
            checks = build_live_preflight_checks(
                env={
                    "HARNESS_RUN_LIVE_RESET_TESTS": "1",
                    "GH_TOKEN": "ghp_token",
                    "LINEAR_API_KEY": "linear-token",
                },
                runner=runner,
            )

        by_code = {check.code: check for check in checks}

        self.assertEqual(by_code["live_mutation_flag"].status, "pass")
        self.assertEqual(by_code["github_env_token"].status, "pass")
        self.assertEqual(by_code["linear_api_key"].status, "pass")
        self.assertEqual(by_code["target_guard"].status, "pass")
        self.assertEqual(by_code["github_repo_readonly"].status, "pass")

    def test_preflight_fails_closed_for_unapproved_targets(self) -> None:
        with patch("scripts.proofline_live_preflight.shutil.which", return_value=None):
            checks = build_live_preflight_checks(
                env={"LINEAR_API_KEY": "linear-token", "GITHUB_TOKEN": "ghp_token"},
                github_repo="production-repo",
            )

        by_code = {check.code: check for check in checks}

        self.assertEqual(by_code["target_guard"].status, "fail")


if __name__ == "__main__":
    unittest.main()
