from __future__ import annotations

import os
import tempfile
import unittest
from copy import deepcopy
from unittest.mock import patch

from modules.api import HarnessApiService
from modules.store import FileBackedHarnessStore
from modules.supervision import HarnessSupervisionService
from tests.test_api import (
    _completion_claim_payload,
    _execution_attempt_payload,
    _manual_happy_path_overlay_payload,
    _request_payload,
)


class HarnessSupervisionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = FileBackedHarnessStore(self.temp_dir.name)
        self.api = HarnessApiService(store=self.store)
        self.service = HarnessSupervisionService(
            store=self.store,
            now_provider=lambda: "2026-04-14T12:00:00Z",
            stale_after_seconds_by_status={
                "planned": 24 * 60 * 60,
                "dispatch_ready": 2 * 60 * 60,
                "assigned": 2 * 60 * 60,
                "blocked": 8 * 60 * 60,
            },
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _queue_by_task_id(self) -> dict[str, dict]:
        return {item["task_id"]: item for item in self.service.list_attention_queue()}

    def test_queue_surfaces_review_and_clarification_attention(self) -> None:
        review_status, review_response = self.api.evaluate(_request_payload("review_required"))
        self.assertEqual(review_status, 200)

        clarification_payload = _manual_happy_path_overlay_payload()
        clarification_payload["request"]["task_envelope"]["id"] = "task-supervision-clarification-1"
        clarification_payload["request"]["task_envelope"]["title"] = "Clarification queue coverage"
        clarification_payload["request"]["task_envelope"]["description"] = "Queue should surface clarification blockers."
        clarification_status, clarification_response = self.api.submit(
            {
                "request": {
                    "task_envelope": deepcopy(clarification_payload["request"]["task_envelope"]),
                    "task_status": "dispatch_ready",
                    "unresolved_conditions": ["Need repository clarification before execution can begin."],
                }
            }
        )
        self.assertEqual(clarification_status, 200)

        queue = self._queue_by_task_id()

        review_item = queue[review_response["task_envelope"]["id"]]
        self.assertEqual(review_item["attention_type"], "review_required")
        self.assertEqual(review_item["suggested_action"], "resolve_review_gate")

        clarification_item = queue[clarification_response["task_envelope"]["id"]]
        self.assertEqual(clarification_item["attention_type"], "clarification_required")
        self.assertEqual(clarification_item["suggested_action"], "collect_clarification")

    def test_queue_surfaces_retryable_and_invalid_execution_attention(self) -> None:
        retry_payload = _request_payload("blocked_insufficient_evidence")
        retry_payload["request"]["runtime_facts"] = {
            "executor_reported_failure": True,
            "attempt_count": 1,
            "latest_attempt_outcome": "failed",
        }
        with patch.dict(os.environ, {"HARNESS_CLASSIFIED_RETRY_BUDGET": "2"}):
            retry_status, retry_response = self.api.evaluate(retry_payload)
        self.assertEqual(retry_status, 200)

        invalid_payload = _manual_happy_path_overlay_payload()
        invalid_task = deepcopy(invalid_payload["request"]["task_envelope"])
        invalid_task["id"] = "task-supervision-invalid-attempt-1"
        invalid_task["title"] = "Invalid execution attempt queue coverage"
        invalid_task["description"] = "Queue should surface invalid execution proof."
        submit_status, submit_response = self.api.submit({"request": {"task_envelope": invalid_task}})
        self.assertEqual(submit_status, 200)

        task_id = submit_response["task_envelope"]["id"]
        stored_task = deepcopy(self.store.get_task(task_id))
        stored_task["status"] = "assigned"
        stored_task["assigned_executor"] = {
            "executor_type": "codex",
            "executor_id": "executor-supervision-invalid-attempt-1",
            "assignment_reason": "Exercise invalid execution attempt supervision.",
        }
        stored_task["timestamps"]["updated_at"] = "2026-04-01T10:03:00Z"
        self.store.update_task(stored_task)

        with patch.dict(os.environ, {"HARNESS_INVALID_EXECUTION_RETRY_BUDGET": "1"}):
            invalid_status, invalid_response = self.api.submit_completion_claim(
                task_id,
                {
                    "request": {
                        **_completion_claim_payload(claim_id="claim-supervision-invalid-1"),
                        **_execution_attempt_payload(attempt_id="attempt-supervision-invalid-1"),
                        "runtime_facts": {"executor_reported_success": True, "attempt_count": 1},
                    }
                },
            )
        self.assertEqual(invalid_status, 200)

        queue = self._queue_by_task_id()

        retry_item = queue[retry_response["task_envelope"]["id"]]
        self.assertEqual(retry_item["attention_type"], "retryable_failure")
        self.assertEqual(retry_item["suggested_action"], "retry_or_redispatch")

        invalid_item = queue[invalid_response["task_envelope"]["id"]]
        self.assertEqual(invalid_item["attention_type"], "invalid_execution_attempt")
        self.assertEqual(invalid_item["suggested_action"], "request_fresh_proof_or_rework")

    def test_queue_surfaces_stale_active_tasks(self) -> None:
        stale_payload = _manual_happy_path_overlay_payload()
        stale_task = deepcopy(stale_payload["request"]["task_envelope"])
        stale_task["id"] = "task-supervision-stale-assigned-1"
        stale_task["title"] = "Stale assigned task"
        stale_task["description"] = "Queue should surface stale active tasks."
        stale_task["timestamps"]["created_at"] = "2026-04-01T08:00:00Z"
        stale_task["timestamps"]["updated_at"] = "2026-04-01T08:00:00Z"

        submit_status, submit_response = self.api.submit({"request": {"task_envelope": stale_task}})
        self.assertEqual(submit_status, 200)

        task_id = submit_response["task_envelope"]["id"]
        stored_task = deepcopy(self.store.get_task(task_id))
        stored_task["status"] = "assigned"
        stored_task["assigned_executor"] = {
            "executor_type": "codex",
            "executor_id": "executor-supervision-stale-1",
            "assignment_reason": "Exercise stale assignment supervision.",
        }
        stored_task["timestamps"]["updated_at"] = "2026-04-01T08:00:00Z"
        self.store.update_task(stored_task)

        queue = self._queue_by_task_id()

        stale_item = queue[task_id]
        self.assertEqual(stale_item["attention_type"], "stale_active_task")
        self.assertEqual(stale_item["suggested_action"], "investigate_staleness")
        self.assertTrue(stale_item["stale"])

    def test_queue_surfaces_github_sync_required_when_valid_execution_proof_exists_without_synced_artifacts(self) -> None:
        payload = _manual_happy_path_overlay_payload()
        task = deepcopy(payload["request"]["task_envelope"])
        task["id"] = "task-supervision-github-sync-1"
        task["title"] = "GitHub sync required queue coverage"
        task["description"] = "Queue should surface missing canonical GitHub sync when current-run proof already exists."
        task["artifacts"]["completion_evidence"]["required_artifact_types"] = ["pull_request", "commit"]

        submit_status, submit_response = self.api.submit({"request": {"task_envelope": task}})
        self.assertEqual(submit_status, 200)

        task_id = submit_response["task_envelope"]["id"]
        stored_task = deepcopy(self.store.get_task(task_id))
        stored_task["status"] = "assigned"
        stored_task["assigned_executor"] = {
            "executor_type": "codex",
            "executor_id": "executor-supervision-github-sync-1",
            "assignment_reason": "Exercise GitHub sync supervision.",
        }
        self.store.update_task(stored_task)

        stored_task["status"] = "blocked"
        stored_task["observability"]["execution_metadata"]["execution_attempts"] = [
            {
                "attempt_id": "attempt-supervision-github-sync-1",
                "completion_claim_id": "claim-supervision-github-sync-1",
                "recorded_at": "2026-04-13T10:00:05Z",
                "reported_by": "codex",
                "status": "succeeded",
                "artifact_references": [
                    {
                        "reference_id": "attempt-supervision-github-sync-1:pr",
                        "artifact_type": "pull_request",
                        "location": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/pull/123",
                        "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                        "metadata": {
                            "repository_host": "github.com",
                            "repository_owner": "KnoxAnalytics",
                            "repository_name": "HARNESS-DRYRUN",
                            "branch_name": "codex/e2e-test",
                            "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                            "pull_request_number": 123,
                            "state": "open",
                        },
                    },
                    {
                        "reference_id": "attempt-supervision-github-sync-1:commit",
                        "artifact_type": "commit",
                        "location": (
                            "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/commit/"
                            "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705"
                        ),
                        "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                        "metadata": {
                            "repository_host": "github.com",
                            "repository_owner": "KnoxAnalytics",
                            "repository_name": "HARNESS-DRYRUN",
                            "branch_name": "codex/e2e-test",
                            "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                        },
                    },
                ],
                "metadata": {
                    "attempt_validation": {
                        "status": "valid",
                        "validated_by": "execution_validation",
                    }
                },
            }
        ]
        self.store.update_task(stored_task)

        queue = self._queue_by_task_id()

        sync_item = queue[task_id]
        self.assertEqual(sync_item["attention_type"], "github_sync_required")
        self.assertEqual(sync_item["suggested_action"], "sync_github_artifacts")
        self.assertFalse(sync_item["stale"])
