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

    def test_claim_requires_pull_request_reference(self) -> None:
        with self.assertRaises(ResetVerificationContractError):
            ResetCompletionClaim(
                repository_owner="sfayka",
                repository_name="Harness",
                branch_name="codex/reset-verifier-v1",
                commit_sha="abc123",
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

