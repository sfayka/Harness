"""Persistence backends for reset verifier contracts."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, cast

from .contracts import ResetVerificationContract
from modules.store import POSTGRES_DATABASE_URL_ENV_VARS, StoreError, resolve_postgres_database_url

try:
    import psycopg
    from psycopg.errors import UniqueViolation
    from psycopg.types.json import Jsonb
except ImportError:  # pragma: no cover - exercised when postgres backend is requested without dependency.
    psycopg = None
    UniqueViolation = None
    Jsonb = None


class ResetContractNotFoundError(ValueError):
    """Raised when a reset verifier contract is missing."""


class ResetContractAlreadyExistsError(ValueError):
    """Raised when a contract ID collision occurs."""


class ResetStore(Protocol):
    """Persistence boundary for reset verifier contracts."""

    def create_contract(self, contract: ResetVerificationContract) -> ResetVerificationContract: ...

    def get_contract(self, contract_id: str) -> ResetVerificationContract: ...

    def update_contract(self, contract: ResetVerificationContract) -> ResetVerificationContract: ...

    def list_contracts(self) -> tuple[ResetVerificationContract, ...]: ...


class FileBackedResetStore(ResetStore):
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


class PostgresResetStore(ResetStore):
    """Postgres-backed store for reset verifier contracts."""

    def __init__(self, database_url: str) -> None:
        if psycopg is None or Jsonb is None or UniqueViolation is None:
            raise StoreError("psycopg is required for HARNESS_RESET_STORE_BACKEND=postgres")
        if not database_url.strip():
            supported_envs = ", ".join(POSTGRES_DATABASE_URL_ENV_VARS)
            raise StoreError(
                "A Postgres connection string is required for HARNESS_RESET_STORE_BACKEND=postgres "
                f"(checked: {supported_envs})"
            )
        self.database_url = database_url

    def _connect(self):
        return psycopg.connect(self.database_url)

    def create_contract(self, contract: ResetVerificationContract) -> ResetVerificationContract:
        contract_payload = cast(dict[str, Any], contract.asdict())
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO reset_contracts (
                            contract_id,
                            linear_issue_id,
                            contract_json,
                            created_at,
                            updated_at
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            contract.contract_id,
                            contract.linear_issue_id,
                            Jsonb(contract_payload),
                            _parse_iso_timestamp(contract.created_at),
                            _parse_iso_timestamp(contract.updated_at),
                        ),
                    )
        except UniqueViolation as error:
            raise ResetContractAlreadyExistsError(f"contract {contract.contract_id!r} already exists") from error
        return contract

    def get_contract(self, contract_id: str) -> ResetVerificationContract:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT contract_json FROM reset_contracts WHERE contract_id = %s",
                    (contract_id,),
                )
                row = cursor.fetchone()
        if row is None:
            raise ResetContractNotFoundError(f"contract {contract_id!r} was not found")
        return ResetVerificationContract.from_dict(cast(dict[str, Any], row[0]))

    def update_contract(self, contract: ResetVerificationContract) -> ResetVerificationContract:
        contract_payload = cast(dict[str, Any], contract.asdict())
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE reset_contracts
                    SET linear_issue_id = %s,
                        contract_json = %s,
                        updated_at = %s
                    WHERE contract_id = %s
                    """,
                    (
                        contract.linear_issue_id,
                        Jsonb(contract_payload),
                        _parse_iso_timestamp(contract.updated_at),
                        contract.contract_id,
                    ),
                )
                if cursor.rowcount == 0:
                    raise ResetContractNotFoundError(f"contract {contract.contract_id!r} was not found")
        return contract

    def list_contracts(self) -> tuple[ResetVerificationContract, ...]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT contract_json
                    FROM reset_contracts
                    ORDER BY updated_at DESC, contract_id DESC
                    """
                )
                rows = cursor.fetchall()
        return tuple(ResetVerificationContract.from_dict(cast(dict[str, Any], row[0])) for row in rows)


def _parse_iso_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _is_vercel_runtime() -> bool:
    return any(
        (
            os.environ.get("VERCEL_URL"),
            os.environ.get("VERCEL_ENV"),
            os.environ.get("VERCEL_REGION"),
        )
    )


def build_reset_store(
    *,
    store_backend: str | None = None,
    store_root: str | Path | None = None,
    database_url: str | None = None,
) -> ResetStore:
    """Construct the configured persistence backend for reset verifier contracts."""

    resolved_database_url = resolve_postgres_database_url(database_url)
    configured_backend = (
        store_backend
        or os.environ.get("HARNESS_RESET_STORE_BACKEND")
        or os.environ.get("HARNESS_STORE_BACKEND")
        or ""
    ).strip().lower()
    if configured_backend:
        backend = configured_backend
    elif database_url and database_url.strip():
        backend = "postgres"
    elif _is_vercel_runtime() and resolved_database_url:
        backend = "postgres"
    else:
        backend = "file"

    if backend == "postgres":
        return PostgresResetStore(resolved_database_url)

    explicit_reset_root = store_root or os.environ.get("HARNESS_RESET_STORE_ROOT")
    if explicit_reset_root:
        return FileBackedResetStore(explicit_reset_root)

    shared_root = os.environ.get("HARNESS_STORE_ROOT")
    if shared_root:
        return FileBackedResetStore(shared_root)

    if _is_vercel_runtime():
        return FileBackedResetStore(Path("/tmp/harness-reset"))

    return FileBackedResetStore(Path(".harness-store"))


__all__ = [
    "build_reset_store",
    "FileBackedResetStore",
    "PostgresResetStore",
    "ResetContractAlreadyExistsError",
    "ResetContractNotFoundError",
    "ResetStore",
]
