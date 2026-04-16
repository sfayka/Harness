from __future__ import annotations

import unittest

from modules.reset.contracts import (
    ResetCompletionClaim,
    ResetVerificationContract,
    ResetVerificationContractError,
)


class ResetContractTests(unittest.TestCase):
    def test_contract_requires_linear_issue_and_repository(self) -> None:
        with self.assertRaises(ResetVerificationContractError):
            ResetVerificationContract(
                contract_id="",
                linear_issue_id="",
                repository_owner="",
                repository_name="",
                branch_ref="",
            )

    def test_claim_requires_pull_request_url(self) -> None:
        with self.assertRaises(ResetVerificationContractError):
            ResetCompletionClaim(
                repository_owner="sfayka",
                repository_name="Harness",
                branch_name="codex/reset-verifier-v1",
                commit_sha="abc123",
                pull_request_number=42,
            )

    def test_branch_ref_supports_glob_matching(self) -> None:
        contract = ResetVerificationContract(
            contract_id="contract-1",
            linear_issue_id="KNO-999",
            repository_owner="sfayka",
            repository_name="Harness",
            branch_ref="codex/*",
        )

        self.assertTrue(contract.branch_matches("codex/reset-verifier-v1"))
        self.assertFalse(contract.branch_matches("main"))

    def test_contract_tracks_claim_timeout_policy(self) -> None:
        contract = ResetVerificationContract(
            contract_id="contract-1",
            linear_issue_id="KNO-999",
            repository_owner="sfayka",
            repository_name="Harness",
            branch_ref="codex/*",
            claim_timeout_seconds=120,
        )

        self.assertEqual(contract.claim_timeout_seconds, 120)
