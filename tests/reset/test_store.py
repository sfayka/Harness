from __future__ import annotations

import tempfile
import unittest

from modules.reset.contracts import ResetVerificationContract
from modules.reset.store import (
    FileBackedResetStore,
    ResetContractAlreadyExistsError,
    ResetContractNotFoundError,
)


class ResetStoreTests(unittest.TestCase):
    def test_round_trips_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileBackedResetStore(temp_dir)
            contract = ResetVerificationContract(
                contract_id="contract-1",
                linear_issue_id="KNO-999",
                repository_owner="sfayka",
                repository_name="Harness",
                branch_ref="main",
            )

            store.create_contract(contract)
            loaded = store.get_contract("contract-1")

            self.assertEqual(loaded.contract_id, "contract-1")
            self.assertEqual(loaded.linear_issue_id, "KNO-999")

    def test_duplicate_ids_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileBackedResetStore(temp_dir)
            contract = ResetVerificationContract(
                contract_id="contract-1",
                linear_issue_id="KNO-999",
                repository_owner="sfayka",
                repository_name="Harness",
                branch_ref="main",
            )

            store.create_contract(contract)
            with self.assertRaises(ResetContractAlreadyExistsError):
                store.create_contract(contract)

    def test_missing_contract_raises_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileBackedResetStore(temp_dir)
            with self.assertRaises(ResetContractNotFoundError):
                store.get_contract("missing")

