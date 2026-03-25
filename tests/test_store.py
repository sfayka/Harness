from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from modules.demo_cases import build_demo_request
from modules.evaluation import evaluate_task_case
from modules.store import (
    FileBackedHarnessStore,
    TaskEnvelopeAlreadyExistsError,
    TaskEnvelopeNotFoundError,
)


class HarnessStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = FileBackedHarnessStore(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_stores_and_reads_task_envelope_by_id(self) -> None:
        request = build_demo_request("accepted_completion")

        self.store.put_task(request.task_envelope)
        stored = self.store.get_task(request.task_envelope["id"])

        self.assertEqual(stored["id"], request.task_envelope["id"])
        self.assertEqual(stored["status"], request.task_envelope["status"])

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

    def test_uses_explicit_task_and_evaluation_directories(self) -> None:
        request = build_demo_request("invalid_input")
        result = evaluate_task_case(request)

        self.store.put_task(request.task_envelope)
        self.store.put_evaluation_record(request=request, result=result, evaluation_id="eval-3")

        task_path = Path(self.temp_dir.name) / "tasks" / f"{request.task_envelope['id']}.json"
        evaluation_path = Path(self.temp_dir.name) / "evaluations" / request.task_envelope["id"] / "eval-3.json"

        self.assertTrue(task_path.exists())
        self.assertTrue(evaluation_path.exists())


if __name__ == "__main__":
    unittest.main()
