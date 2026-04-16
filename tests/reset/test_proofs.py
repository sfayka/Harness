from __future__ import annotations

import unittest

from modules.reset.proofs import ResetWorkerProofError, parse_worker_proof_output


class ResetWorkerProofParsingTests(unittest.TestCase):
    def test_parses_happy_path_final_proof_lines(self) -> None:
        proof = parse_worker_proof_output(
            """
            Repository: sfayka/HARNESS-DRYRUN
            Branch: codex/kno-999-happy-path
            Commit SHA: 1234567890abcdef1234567890abcdef12345678
            PR URL: https://github.com/sfayka/HARNESS-DRYRUN/pull/42
            """
        )

        self.assertEqual(proof.repository_owner, "sfayka")
        self.assertEqual(proof.repository_name, "HARNESS-DRYRUN")
        self.assertEqual(proof.branch_name, "codex/kno-999-happy-path")
        self.assertEqual(proof.commit_sha, "1234567890abcdef1234567890abcdef12345678")
        self.assertEqual(proof.pull_request_number, 42)
        self.assertEqual(proof.pull_request_url, "https://github.com/sfayka/HARNESS-DRYRUN/pull/42")

    def test_rejects_missing_pull_request_url(self) -> None:
        with self.assertRaises(ResetWorkerProofError):
            parse_worker_proof_output(
                """
                Repository: sfayka/HARNESS-DRYRUN
                Branch: codex/kno-999-happy-path
                Commit SHA: 1234567890abcdef1234567890abcdef12345678
                """
            )
