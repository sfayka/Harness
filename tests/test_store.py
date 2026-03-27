from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from modules.demo_cases import build_demo_request
from modules.evaluation import evaluate_task_case
from modules.store import (
    FileBackedHarnessStore,
    PostgresHarnessStore,
    TaskEnvelopeAlreadyExistsError,
    TaskEnvelopeNotFoundError,
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
