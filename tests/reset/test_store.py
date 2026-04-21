from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules.reset.contracts import ResetCompletionClaim, ResetVerificationContract
from modules.reset.store import (
    FileBackedResetStore,
    PostgresResetStore,
    ResetContractAlreadyExistsError,
    ResetContractNotFoundError,
    SQLiteResetStore,
    build_reset_store,
)


POSTGRES_TEST_DATABASE_URL = os.environ.get("HARNESS_TEST_DATABASE_URL")
POSTGRES_SCHEMA_SQL = (
    Path(__file__).resolve().parents[2] / "sql" / "postgres" / "001_harness_store.sql"
).read_text(encoding="utf-8")


class ResetStoreResolutionTests(unittest.TestCase):
    def test_build_reset_store_uses_postgres_in_vercel_when_database_url_exists(self) -> None:
        with patch.dict(
            os.environ,
            {
                "VERCEL_URL": "harness-preview.vercel.app",
                "POSTGRES_URL": "postgresql://env-vercel",
            },
            clear=True,
        ):
            store = build_reset_store()

        self.assertIsInstance(store, PostgresResetStore)
        self.assertEqual(store.database_url, "postgresql://env-vercel")

    def test_build_reset_store_honors_explicit_file_backend(self) -> None:
        with patch.dict(
            os.environ,
            {
                "HARNESS_RESET_STORE_BACKEND": "file",
                "VERCEL_URL": "harness-preview.vercel.app",
                "POSTGRES_URL": "postgresql://env-vercel",
            },
            clear=True,
        ):
            store = build_reset_store(store_root="/tmp/harness-reset-test")

        self.assertIsInstance(store, FileBackedResetStore)

    def test_build_reset_store_honors_sqlite_backend(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        database_path = str(Path(temp_dir.name) / "harness.db")
        with patch.dict(
            os.environ,
            {
                "HARNESS_RESET_STORE_BACKEND": "sqlite",
                "HARNESS_SQLITE_PATH": database_path,
            },
            clear=True,
        ):
            store = build_reset_store()

        self.assertIsInstance(store, SQLiteResetStore)
        self.assertEqual(store.database_path, Path(database_path))


class _RecordingCursor:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.rowcount = 1

    def execute(self, sql: str, params=None) -> None:  # noqa: ANN001
        self.statements.append(" ".join(sql.split()))

    def fetchone(self):  # noqa: ANN201
        return None

    def fetchall(self):  # noqa: ANN201
        return []

    def __enter__(self) -> "_RecordingCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        return None


class _RecordingConnection:
    def __init__(self, cursor: _RecordingCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> _RecordingCursor:
        return self._cursor

    def __enter__(self) -> "_RecordingConnection":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        return None


class PostgresResetStoreSchemaBootstrapTests(unittest.TestCase):
    def test_create_contract_bootstraps_reset_schema_before_insert(self) -> None:
        store = PostgresResetStore("postgresql://example")
        cursor = _RecordingCursor()
        contract = ResetVerificationContract(
            contract_id="contract-bootstrap",
            linear_issue_id="KNO-999",
            repository_owner="sfayka",
            repository_name="Harness",
            branch_ref="codex/reset-verifier-v1",
        )

        with patch.object(store, "_connect", return_value=_RecordingConnection(cursor)):
            store.create_contract(contract)

        self.assertGreaterEqual(len(cursor.statements), 2)
        self.assertIn("CREATE TABLE IF NOT EXISTS reset_contracts", cursor.statements[0])
        self.assertIn("INSERT INTO reset_contracts", cursor.statements[-1])


class ResetStoreContractTests:
    store = None

    def _sample_contract(self) -> ResetVerificationContract:
        return ResetVerificationContract(
            contract_id="contract-1",
            linear_issue_id="KNO-999",
            repository_owner="sfayka",
            repository_name="Harness",
            branch_ref="codex/reset-verifier-v1",
        )

    def test_create_and_get_contract_round_trip(self) -> None:
        contract = self._sample_contract()

        self.store.create_contract(contract)
        stored = self.store.get_contract(contract.contract_id)

        self.assertEqual(stored.contract_id, contract.contract_id)
        self.assertEqual(stored.harness_status, "running")

    def test_create_rejects_duplicate_contract_id(self) -> None:
        contract = self._sample_contract()

        self.store.create_contract(contract)

        with self.assertRaises(ResetContractAlreadyExistsError):
            self.store.create_contract(contract)

    def test_update_persists_latest_claim_and_event_log(self) -> None:
        contract = self._sample_contract()
        self.store.create_contract(contract)

        updated = contract.updated(
            latest_claim=ResetCompletionClaim(
                repository_owner="sfayka",
                repository_name="Harness",
                branch_name="codex/reset-verifier-v1",
                commit_sha="abc123",
                pull_request_number=42,
                pull_request_url="https://github.com/sfayka/Harness/pull/42",
            ),
            latest_verdict="verified_done",
            latest_reason="github proof verified",
            harness_status="verified",
            last_activity_at="2026-04-17T12:00:00Z",
            last_verified_at="2026-04-17T12:00:00Z",
        ).append_event(
            kind="verified",
            message="github proof verified",
            timestamp="2026-04-17T12:00:00Z",
        )

        self.store.update_contract(updated)
        stored = self.store.get_contract(contract.contract_id)

        self.assertEqual(stored.harness_status, "verified")
        self.assertEqual(stored.latest_claim.commit_sha, "abc123")
        self.assertEqual(stored.event_log[-1].kind, "verified")

    def test_list_contracts_orders_by_updated_at_desc(self) -> None:
        older = ResetVerificationContract(
            contract_id="contract-older",
            linear_issue_id="KNO-998",
            repository_owner="sfayka",
            repository_name="Harness",
            branch_ref="codex/reset-verifier-v1",
            created_at="2026-04-17T11:00:00Z",
            updated_at="2026-04-17T11:00:00Z",
        )
        newer = ResetVerificationContract(
            contract_id="contract-newer",
            linear_issue_id="KNO-999",
            repository_owner="sfayka",
            repository_name="Harness",
            branch_ref="codex/reset-verifier-v2",
            created_at="2026-04-17T12:00:00Z",
            updated_at="2026-04-17T12:00:00Z",
        )

        self.store.create_contract(older)
        self.store.create_contract(newer)

        listed = self.store.list_contracts()

        self.assertEqual([contract.contract_id for contract in listed[:2]], ["contract-newer", "contract-older"])

    def test_get_missing_contract_raises(self) -> None:
        with self.assertRaises(ResetContractNotFoundError):
            self.store.get_contract("missing-contract")


class FileBackedResetStoreTests(ResetStoreContractTests, unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = FileBackedResetStore(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()


class SQLiteResetStoreTests(ResetStoreContractTests, unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "harness.db"
        self.store = SQLiteResetStore(self.database_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_persists_contracts_across_store_restarts(self) -> None:
        contract = self._sample_contract()

        self.store.create_contract(contract)
        restarted = SQLiteResetStore(self.database_path)

        self.assertEqual(restarted.get_contract(contract.contract_id).contract_id, contract.contract_id)
        self.assertTrue(restarted.schema_ready())


@unittest.skipUnless(POSTGRES_TEST_DATABASE_URL, "HARNESS_TEST_DATABASE_URL is required for Postgres reset store tests")
class PostgresResetStoreTests(ResetStoreContractTests, unittest.TestCase):
    def setUp(self) -> None:
        self.store = PostgresResetStore(POSTGRES_TEST_DATABASE_URL or "")
        with self.store._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(POSTGRES_SCHEMA_SQL)
                cursor.execute("DELETE FROM reset_contracts")

    def tearDown(self) -> None:
        with self.store._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM reset_contracts")

    def test_persists_contract_jsonb_payloads(self) -> None:
        contract = ResetVerificationContract(
            contract_id="contract-postgres-1",
            linear_issue_id="KNO-999",
            repository_owner="sfayka",
            repository_name="Harness",
            branch_ref="codex/reset-verifier-v1",
        )

        self.store.create_contract(contract)

        with self.store._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT contract_json->>'contract_id', updated_at FROM reset_contracts WHERE contract_id = %s",
                    (contract.contract_id,),
                )
                row = cursor.fetchone()

        self.assertEqual(row[0], contract.contract_id)
        self.assertIsNotNone(row[1])


if __name__ == "__main__":
    unittest.main()
