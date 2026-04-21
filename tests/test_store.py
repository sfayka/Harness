from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules.demo_cases import build_demo_request
from modules.evaluation import evaluate_task_case
from modules.store import (
    FileBackedHarnessStore,
    PostgresHarnessStore,
    SQLiteHarnessStore,
    StoreError,
    TaskEnvelopeAlreadyExistsError,
    TaskEnvelopeNotFoundError,
    build_harness_store,
    resolve_postgres_database_url,
    resolve_sqlite_database_path,
)


POSTGRES_TEST_DATABASE_URL = os.environ.get("HARNESS_TEST_DATABASE_URL")
POSTGRES_SCHEMA_SQL = (
    Path(__file__).resolve().parents[1] / "sql" / "postgres" / "001_harness_store.sql"
).read_text(encoding="utf-8")


class HarnessStoreContractTests:
    store = None

    def test_stores_and_reads_task_envelope_by_id(self) -> None:
        request = build_demo_request("accepted_completion")

        self.store.put_task(request.task_envelope)
        stored = self.store.get_task(request.task_envelope["id"])

        self.assertEqual(stored["id"], request.task_envelope["id"])
        self.assertEqual(stored["status"], request.task_envelope["status"])

    def test_lists_tasks_in_updated_at_desc_order(self) -> None:
        first_request = build_demo_request("accepted_completion")
        second_request = build_demo_request("blocked_insufficient_evidence")
        first_request.task_envelope["id"] = "task-older"
        second_request.task_envelope["id"] = "task-newer"
        first_request.task_envelope["timestamps"]["updated_at"] = "2026-03-24T20:00:00Z"
        second_request.task_envelope["timestamps"]["updated_at"] = "2026-03-24T21:00:00Z"

        self.store.put_task(first_request.task_envelope)
        self.store.put_task(second_request.task_envelope)

        listed = self.store.list_tasks()

        self.assertEqual([task["id"] for task in listed[:2]], ["task-newer", "task-older"])

    def test_create_task_rejects_duplicate_id(self) -> None:
        request = build_demo_request("accepted_completion")

        self.store.create_task(request.task_envelope)

        with self.assertRaises(TaskEnvelopeAlreadyExistsError):
            self.store.create_task(request.task_envelope)

    def test_updates_task_after_lifecycle_change(self) -> None:
        request = build_demo_request("accepted_completion")
        result = evaluate_task_case(request)

        self.store.put_task(request.task_envelope)
        self.store.update_task(result.task_envelope)
        stored = self.store.get_task(request.task_envelope["id"])

        self.assertEqual(stored["status"], "completed")
        self.assertEqual(len(stored["status_history"]), 1)
        self.assertEqual(stored["status_history"][0]["to_status"], "completed")

    def test_raises_for_missing_task_lookup(self) -> None:
        with self.assertRaises(TaskEnvelopeNotFoundError):
            self.store.get_task("missing-task")

    def test_persists_evaluation_records_for_task(self) -> None:
        request = build_demo_request("blocked_reconciliation_mismatch")
        result = evaluate_task_case(request)

        self.store.put_task(request.task_envelope)
        record = self.store.put_evaluation_record(
            request=request,
            result=result,
            evaluation_id="eval-1",
            recorded_at="2026-03-24T21:00:00Z",
        )
        records = self.store.list_evaluation_records(request.task_envelope["id"])

        self.assertEqual(record.evaluation_id, "eval-1")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].task_id, request.task_envelope["id"])
        self.assertEqual(records[0].result["target_status"], "blocked")

    def test_evaluation_records_preserve_auditable_decision_data(self) -> None:
        request = build_demo_request("accepted_completion")
        result = evaluate_task_case(request)

        self.store.put_task(request.task_envelope)
        self.store.put_evaluation_record(
            request=request,
            result=result,
            evaluation_id="eval-2",
            recorded_at="2026-03-24T21:05:00Z",
        )
        record = self.store.list_evaluation_records(request.task_envelope["id"])[0]

        self.assertEqual(record.recorded_at, "2026-03-24T21:05:00Z")
        self.assertEqual(record.result["action"], "transition_applied")
        self.assertEqual(record.result["task_envelope"]["status"], "completed")
        self.assertIn("accepted_completion", record.result["enforcement_result"]["verification_result"]["outcome"])


class FileBackedHarnessStoreTests(HarnessStoreContractTests, unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = FileBackedHarnessStore(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_uses_explicit_task_and_evaluation_directories(self) -> None:
        request = build_demo_request("invalid_input")
        result = evaluate_task_case(request)

        self.store.put_task(request.task_envelope)
        self.store.put_evaluation_record(request=request, result=result, evaluation_id="eval-3")

        task_path = Path(self.temp_dir.name) / "tasks" / f"{request.task_envelope['id']}.json"
        evaluation_path = Path(self.temp_dir.name) / "evaluations" / request.task_envelope["id"] / "eval-3.json"

        self.assertTrue(task_path.exists())
        self.assertTrue(evaluation_path.exists())


class SQLiteHarnessStoreTests(HarnessStoreContractTests, unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "harness.db"
        self.store = SQLiteHarnessStore(self.database_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_creates_sqlite_database_with_schema_version(self) -> None:
        self.assertTrue(self.database_path.exists())
        self.assertTrue(self.store.schema_ready())

    def test_persists_across_store_restarts(self) -> None:
        request = build_demo_request("accepted_completion")
        result = evaluate_task_case(request)

        self.store.put_task(request.task_envelope)
        self.store.put_evaluation_record(
            request=request,
            result=result,
            evaluation_id="eval-sqlite-restart",
            recorded_at="2026-03-24T21:15:00Z",
        )

        restarted = SQLiteHarnessStore(self.database_path)

        self.assertEqual(restarted.get_task(request.task_envelope["id"])["id"], request.task_envelope["id"])
        self.assertEqual(
            restarted.list_evaluation_records(request.task_envelope["id"])[0].evaluation_id,
            "eval-sqlite-restart",
        )

    def test_rejects_evaluation_record_for_missing_task(self) -> None:
        request = build_demo_request("accepted_completion")
        result = evaluate_task_case(request)

        with self.assertRaises(TaskEnvelopeNotFoundError):
            self.store.put_evaluation_record(
                request=request,
                result=result,
                evaluation_id="eval-missing-task",
                recorded_at="2026-03-24T21:00:00Z",
            )

    def test_corrupt_database_raises_operator_readable_store_error(self) -> None:
        corrupt_path = Path(self.temp_dir.name) / "corrupt.db"
        corrupt_path.write_text("not a sqlite database", encoding="utf-8")

        with self.assertRaises(StoreError) as context:
            SQLiteHarnessStore(corrupt_path)

        self.assertIn("SQLite store", str(context.exception))
        self.assertIn(str(corrupt_path), str(context.exception))


class PostgresDatabaseUrlResolutionTests(unittest.TestCase):
    def test_prefers_explicit_database_url_argument(self) -> None:
        with patch.dict(
            os.environ,
            {"DATABASE_URL": "postgresql://env-primary", "POSTGRES_URL": "postgresql://env-vercel"},
            clear=False,
        ):
            resolved = resolve_postgres_database_url("postgresql://explicit")

        self.assertEqual(resolved, "postgresql://explicit")

    def test_prefers_database_url_over_vercel_injected_variants(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql://env-primary",
                "POSTGRES_URL": "postgresql://env-vercel",
                "POSTGRES_URL_NON_POOLING": "postgresql://env-direct",
            },
            clear=False,
        ):
            resolved = resolve_postgres_database_url()

        self.assertEqual(resolved, "postgresql://env-primary")

    def test_uses_vercel_postgres_url_when_database_url_is_absent(self) -> None:
        with patch.dict(
            os.environ,
            {"POSTGRES_URL": "postgresql://env-vercel"},
            clear=True,
        ):
            resolved = resolve_postgres_database_url()

        self.assertEqual(resolved, "postgresql://env-vercel")

    def test_falls_back_to_non_pooling_variant(self) -> None:
        with patch.dict(
            os.environ,
            {"POSTGRES_URL_NON_POOLING": "postgresql://env-direct"},
            clear=True,
        ):
            resolved = resolve_postgres_database_url()

        self.assertEqual(resolved, "postgresql://env-direct")

    def test_build_harness_store_accepts_vercel_postgres_envs(self) -> None:
        with patch.dict(
            os.environ,
            {"HARNESS_STORE_BACKEND": "postgres", "POSTGRES_URL": "postgresql://env-vercel"},
            clear=True,
        ):
            store = build_harness_store()

        self.assertIsInstance(store, PostgresHarnessStore)
        self.assertEqual(store.database_url, "postgresql://env-vercel")

    def test_build_harness_store_defaults_to_postgres_in_vercel_when_database_url_is_available(self) -> None:
        with patch.dict(
            os.environ,
            {
                "VERCEL_URL": "harness-preview.vercel.app",
                "POSTGRES_URL": "postgresql://env-vercel",
            },
            clear=True,
        ):
            store = build_harness_store()

        self.assertIsInstance(store, PostgresHarnessStore)
        self.assertEqual(store.database_url, "postgresql://env-vercel")

    def test_build_harness_store_defaults_to_postgres_when_explicit_database_url_is_passed(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            store = build_harness_store(database_url="postgresql://explicit")

        self.assertIsInstance(store, PostgresHarnessStore)
        self.assertEqual(store.database_url, "postgresql://explicit")

    def test_postgres_backend_error_lists_supported_environment_variables(self) -> None:
        with self.assertRaises(StoreError) as context:
            PostgresHarnessStore("")

        self.assertIn("DATABASE_URL", str(context.exception))
        self.assertIn("POSTGRES_URL", str(context.exception))


class SQLiteDatabasePathResolutionTests(unittest.TestCase):
    def test_prefers_explicit_database_path_argument(self) -> None:
        with patch.dict(os.environ, {"HARNESS_SQLITE_PATH": "/env/harness.db"}, clear=False):
            resolved = resolve_sqlite_database_path("/explicit/harness.db")

        self.assertEqual(resolved, Path("/explicit/harness.db"))

    def test_uses_harness_sqlite_path_environment_variable(self) -> None:
        with patch.dict(os.environ, {"HARNESS_SQLITE_PATH": "/env/harness.db"}, clear=True):
            resolved = resolve_sqlite_database_path()

        self.assertEqual(resolved, Path("/env/harness.db"))

    def test_uses_store_root_when_no_explicit_sqlite_path_is_set(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            resolved = resolve_sqlite_database_path(store_root="/tmp/harness-store")

        self.assertEqual(resolved, Path("/tmp/harness-store/harness.db"))

    def test_defaults_to_application_support_on_macos(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            resolved = resolve_sqlite_database_path(platform_name="darwin", home="/Users/sean")

        self.assertEqual(resolved, Path("/Users/sean/Library/Application Support/Harness/harness.db"))

    def test_defaults_to_xdg_data_home_on_linux(self) -> None:
        with patch.dict(os.environ, {"XDG_DATA_HOME": "/tmp/xdg-data"}, clear=True):
            resolved = resolve_sqlite_database_path(platform_name="linux", home="/Users/sean")

        self.assertEqual(resolved, Path("/tmp/xdg-data/harness/harness.db"))

    def test_defaults_to_local_share_on_linux_without_xdg_data_home(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            resolved = resolve_sqlite_database_path(platform_name="linux", home="/Users/sean")

        self.assertEqual(resolved, Path("/Users/sean/.local/share/harness/harness.db"))

    def test_build_harness_store_accepts_sqlite_backend_from_environment(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        database_path = str(Path(temp_dir.name) / "harness.db")
        with patch.dict(
            os.environ,
            {"HARNESS_STORE_BACKEND": "sqlite", "HARNESS_SQLITE_PATH": database_path},
            clear=True,
        ):
            store = build_harness_store()

        self.assertIsInstance(store, SQLiteHarnessStore)
        self.assertEqual(store.database_path, Path(database_path))


@unittest.skipUnless(POSTGRES_TEST_DATABASE_URL, "HARNESS_TEST_DATABASE_URL is required for Postgres store tests")
class PostgresHarnessStoreTests(HarnessStoreContractTests, unittest.TestCase):
    def setUp(self) -> None:
        self.store = PostgresHarnessStore(POSTGRES_TEST_DATABASE_URL or "")
        with self.store._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(POSTGRES_SCHEMA_SQL)
                cursor.execute("DELETE FROM evaluation_records")
                cursor.execute("DELETE FROM tasks")

    def tearDown(self) -> None:
        with self.store._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM evaluation_records")
                cursor.execute("DELETE FROM tasks")

    def test_persists_jsonb_payloads_to_required_tables(self) -> None:
        request = build_demo_request("accepted_completion")
        result = evaluate_task_case(request)

        self.store.put_task(request.task_envelope)
        self.store.put_evaluation_record(
            request=request,
            result=result,
            evaluation_id="eval-postgres-1",
            recorded_at="2026-03-24T21:10:00Z",
        )

        with self.store._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT task_json->>'id', updated_at FROM tasks WHERE task_id = %s", (request.task_envelope["id"],))
                task_row = cursor.fetchone()
                cursor.execute(
                    "SELECT result_json->>'target_status' FROM evaluation_records WHERE evaluation_id = %s",
                    ("eval-postgres-1",),
                )
                evaluation_row = cursor.fetchone()

        self.assertEqual(task_row[0], request.task_envelope["id"])
        self.assertIsNotNone(task_row[1])
        self.assertEqual(evaluation_row[0], "completed")


if __name__ == "__main__":
    unittest.main()
