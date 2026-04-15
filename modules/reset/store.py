"""File-backed persistence for reset verifier contracts."""

from __future__ import annotations

import json
from pathlib import Path

from .contracts import ResetVerificationContract


class ResetContractNotFoundError(ValueError):
    """Raised when a reset verifier contract is missing."""


class ResetContractAlreadyExistsError(ValueError):
    """Raised when a contract ID collision occurs."""


class FileBackedResetStore:
    """Simple JSON-file store for the reset verifier slice."""

    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)
        self.contracts_dir = self.root_dir / "reset-contracts"
        self.contracts_dir.mkdir(parents=True, exist_ok=True)

    def _contract_path(self, contract_id: str) -> Path:
        return self.contracts_dir / f"{contract_id}.json"

    def create_contract(self, contract: ResetVerificationContract) -> ResetVerificationContract:
        path = self._contract_path(contract.contract_id)
        if path.exists():
            raise ResetContractAlreadyExistsError(f"contract {contract.contract_id!r} already exists")
        path.write_text(json.dumps(contract.asdict(), indent=2, sort_keys=True), encoding="utf-8")
        return contract

    def get_contract(self, contract_id: str) -> ResetVerificationContract:
        path = self._contract_path(contract_id)
        if not path.exists():
            raise ResetContractNotFoundError(f"contract {contract_id!r} was not found")
        return ResetVerificationContract.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def update_contract(self, contract: ResetVerificationContract) -> ResetVerificationContract:
        path = self._contract_path(contract.contract_id)
        if not path.exists():
            raise ResetContractNotFoundError(f"contract {contract.contract_id!r} was not found")
        path.write_text(json.dumps(contract.asdict(), indent=2, sort_keys=True), encoding="utf-8")
        return contract

    def list_contracts(self) -> tuple[ResetVerificationContract, ...]:
        contracts = [
            ResetVerificationContract.from_dict(json.loads(path.read_text(encoding="utf-8")))
            for path in self.contracts_dir.glob("*.json")
        ]
        contracts.sort(key=lambda contract: (contract.updated_at, contract.contract_id), reverse=True)
        return tuple(contracts)


__all__ = [
    "FileBackedResetStore",
    "ResetContractAlreadyExistsError",
    "ResetContractNotFoundError",
]
