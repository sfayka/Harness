"""Tests for advisory execution-substrate event ingestion."""

from __future__ import annotations

import tempfile
import unittest

from modules.api import HarnessApiService
from modules.intake.task_envelope import create_task_envelope
from modules.store import FileBackedHarnessStore


def _task(task_id: str = "task-substrate-ingest-1") -> dict:
    return create_task_envelope(
        {
            "id": task_id,
            "title": "Record Symphony runner event",
            "description": "Persist a runner event without trusting it as completion.",
            "origin": {
                "source_system": "linear",
                "source_type": "synchronization",
                "source_id": "KNO-999",
            },
            "acceptance_criteria": [
                {
                    "id": "ac-1",
                    "description": "Harness records runner status as advisory runtime context.",
                    "required": True,
                }
            ],
        },
        now="2026-04-27T20:00:00Z",
    )


def _runner_event_payload(task_id: str = "task-substrate-ingest-1") -> dict:
    return {
        "event": {
            "event_id": "runner-event-1",
            "task_id": task_id,
            "attempt_id": "attempt-1",
            "runner_kind": "symphony",
            "runner_session_id": "runner-session-1",
            "executor_kind": "codex_app_server",
            "workspace_id": "workspace/task-substrate-ingest-1",
            "event_type": "run_completed_by_executor",
            "occurred_at": "2026-04-27T20:05:00Z",
            "provenance": {
                "source_system": "symphony",
                "source_type": "runner_event",
                "source_id": "runner-session-1:runner-event-1",
                "captured_by": "execution_substrate_adapter",
            },
            "payload": {
                "reported_complete": True,
                "handoff_state": "human_review",
                "summary": "Codex reports the work is ready for Harness verification.",
            },
            "artifact_references": [
                {
                    "artifact_type": "pull_request",
                    "repository": "sfayka/Harness",
                    "branch": "codex/task-substrate-ingest-1",
                    "pr_url": "https://github.com/sfayka/Harness/pull/999",
                    "reported_by": "symphony",
                    "reported_at": "2026-04-27T20:05:00Z",
                    "source_attempt_id": "attempt-1",
                }
            ],
        }
    }


class ExecutionSubstrateIngestionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = FileBackedHarnessStore(self.temp_dir.name)
        self.service = HarnessApiService(store=self.store)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_runner_completion_event_is_stored_as_advisory_runtime_fact(self) -> None:
        task = self.store.create_task(_task())

        status, payload = self.service.submit_execution_substrate_event(
            str(task["id"]),
            _runner_event_payload(),
        )

        stored_task = self.store.get_task(str(task["id"]))
        execution_metadata = stored_task["observability"]["execution_metadata"]
        substrate_events = execution_metadata["execution_substrate_events"]

        self.assertEqual(status, 200)
        self.assertEqual(payload["action"], "execution_substrate_event_recorded")
        self.assertFalse(payload["accepted_completion"])
        self.assertEqual(payload["completion_validation_summary"]["status"], "pending")
        self.assertFalse(payload["completion_validation_summary"]["completion_accepted"])
        self.assertEqual(payload["completion_validation_summary"]["intent_status"], "pending")
        self.assertEqual(stored_task["status"], "intake_ready")
        self.assertEqual(len(substrate_events), 1)
        self.assertEqual(substrate_events[0]["event_type"], "run_completed_by_executor")
        self.assertEqual(substrate_events[0]["artifact_references"][0]["verification_status"], "unverified")
        self.assertEqual(payload["execution_summary"]["substrate_event_count"], 1)
        self.assertEqual(payload["execution_summary"]["latest_runner_session_id"], "runner-session-1")

    def test_runner_event_rejects_lifecycle_authority(self) -> None:
        task = self.store.create_task(_task("task-substrate-ingest-2"))
        payload = _runner_event_payload("task-substrate-ingest-2")
        payload["event"]["payload"]["target_status"] = "completed"

        status, response = self.service.submit_execution_substrate_event(str(task["id"]), payload)

        stored_task = self.store.get_task(str(task["id"]))
        execution_metadata = stored_task["observability"]["execution_metadata"]

        self.assertEqual(status, 400)
        self.assertTrue(response["invalid_input"])
        self.assertIn("prohibited lifecycle authority", response["error"])
        self.assertNotIn("execution_substrate_events", execution_metadata)
        self.assertEqual(stored_task["status"], "intake_ready")

    def test_read_model_and_timeline_expose_substrate_events(self) -> None:
        task = self.store.create_task(_task("task-substrate-ingest-3"))
        payload = _runner_event_payload("task-substrate-ingest-3")

        status, _ = self.service.submit_execution_substrate_event(str(task["id"]), payload)
        read_model_status, read_model_payload = self.service.get_task_read_model(str(task["id"]))
        timeline_status, timeline_payload = self.service.get_task_timeline(str(task["id"]))

        timeline_events = [
            event
            for event in timeline_payload["timeline"]
            if event["event_type"] == "execution_substrate_event_recorded"
        ]

        self.assertEqual(status, 200)
        self.assertEqual(read_model_status, 200)
        self.assertEqual(timeline_status, 200)
        self.assertEqual(read_model_payload["task"]["execution_summary"]["substrate_event_count"], 1)
        self.assertEqual(
            read_model_payload["task"]["execution_summary"]["latest_substrate_event"]["event_type"],
            "run_completed_by_executor",
        )
        self.assertEqual(len(timeline_events), 1)
        self.assertEqual(timeline_events[0]["details"]["runner_kind"], "symphony")

    def test_duplicate_runner_event_id_is_rejected(self) -> None:
        task = self.store.create_task(_task("task-substrate-ingest-4"))
        payload = _runner_event_payload("task-substrate-ingest-4")

        first_status, _ = self.service.submit_execution_substrate_event(str(task["id"]), payload)
        second_status, second_payload = self.service.submit_execution_substrate_event(str(task["id"]), payload)

        stored_task = self.store.get_task(str(task["id"]))
        substrate_events = stored_task["observability"]["execution_metadata"]["execution_substrate_events"]

        self.assertEqual(first_status, 200)
        self.assertEqual(second_status, 400)
        self.assertIn("already exists", second_payload["error"])
        self.assertEqual(len(substrate_events), 1)


if __name__ == "__main__":
    unittest.main()
