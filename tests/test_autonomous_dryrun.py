from __future__ import annotations

import unittest
from unittest.mock import patch

import modules.autonomous_dryrun as autonomous_dryrun
from modules.autonomous_dryrun import (
    SampleCodexCloudRuntimeClient,
    run_retryable_codex_supervision_dry_run,
)


class _SuccessfulCodexCloudRuntimeClient:
    def execute(self, request_payload: dict) -> dict:
        branch_name = request_payload["task"]["branch_hint"]
        commit_sha = "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705"
        return {
            "run_id": "codex-autonomous-run-1",
            "preflight": {
                "pwd": "/workspace/Harness",
                "git_remote_v": (
                    "origin\thttps://github.com/sfayka/Harness.git (fetch)\n"
                    "origin\thttps://github.com/sfayka/Harness.git (push)"
                ),
                "bootstrap_proof": "bootstrap ok",
            },
            "events": [
                {"id": "evt-1", "type": "run_started", "timestamp": "2026-04-12T16:00:00Z"},
                {"id": "evt-2", "type": "run_succeeded", "timestamp": "2026-04-12T16:05:00Z"},
            ],
            "artifacts": [
                {
                    "type": "branch",
                    "id": "branch-1",
                    "external_id": branch_name,
                    "head_commit_sha": commit_sha,
                },
                {
                    "type": "commit",
                    "id": "commit-1",
                    "commit_sha": commit_sha,
                    "url": f"https://github.com/KnoxAnalytics/HARNESS-DRYRUN/commit/{commit_sha}",
                },
                {
                    "type": "pull_request",
                    "id": "pr-1",
                    "url": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/pull/2",
                    "number": 2,
                    "state": "open",
                    "merged": False,
                    "branch_name": branch_name,
                    "commit_sha": commit_sha,
                },
                {
                    "type": "changed_file",
                    "id": "changed-file-1",
                    "url": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/blob/main/modules/api.py",
                    "commit_sha": commit_sha,
                },
            ],
            "completion": {
                "reported_complete": True,
                "confidence": "high",
                "reason": "Controlled dry run produced the full artifact set",
            },
        }


class AutonomousDryRunTests(unittest.TestCase):
    def test_stale_codex_supervision_dry_run_escalates_to_review_required(self) -> None:
        result = autonomous_dryrun.run_stale_codex_supervision_dry_run(
            runtime_client=SampleCodexCloudRuntimeClient(),
            task_id="autonomous-dryrun-stale-1",
        )

        self.assertEqual(result.create_status, 200)
        self.assertEqual(result.initial_task_status, "assigned")
        self.assertEqual(result.initial_supervision_queue_status, 200)
        self.assertEqual(result.initial_supervision_attention_type, "stale_active_task")
        self.assertEqual(result.supervisor_queue_status, 200)
        self.assertEqual(result.supervisor_decision_count, 1)
        self.assertEqual(result.supervisor_action_statuses, ("redispatch_triggered",))
        self.assertEqual(result.final_task_status, "in_review")
        self.assertEqual(result.final_supervision_queue_status, 200)
        self.assertEqual(result.final_supervision_attention_type, "review_required")
        self.assertTrue(result.sample_runtime)

    def test_stale_codex_supervision_dry_run_stops_before_github_sync(self) -> None:
        with patch(
            "modules.autonomous_dryrun._request_json",
            wraps=autonomous_dryrun._request_json,
        ) as request_json:
            result = autonomous_dryrun.run_stale_codex_supervision_dry_run(
                runtime_client=SampleCodexCloudRuntimeClient(),
                task_id="autonomous-dryrun-stale-sync-1",
            )

        request_pairs = [(call.args[1], call.args[2]) for call in request_json.call_args_list]

        self.assertEqual(result.final_supervision_attention_type, "review_required")
        self.assertNotIn(("POST", "/sync/github"), request_pairs)

    def test_retryable_codex_supervision_dry_run_uses_github_sync_endpoint(self) -> None:
        with patch(
            "modules.autonomous_dryrun._request_json",
            wraps=autonomous_dryrun._request_json,
        ) as request_json:
            result = run_retryable_codex_supervision_dry_run(
                runtime_client=_SuccessfulCodexCloudRuntimeClient(),
                task_id="autonomous-dryrun-sync-endpoint-1",
            )

        request_pairs = [(call.args[1], call.args[2]) for call in request_json.call_args_list]

        self.assertEqual(result.final_task_status, "completed")
        self.assertIn(("POST", "/sync/github"), request_pairs)
        self.assertNotIn(
            ("POST", f"/tasks/{result.task_id}/reevaluate"),
            request_pairs,
        )

    def test_retryable_codex_supervision_dry_run_recovers_to_completed(self) -> None:
        result = run_retryable_codex_supervision_dry_run(
            runtime_client=_SuccessfulCodexCloudRuntimeClient(),
            task_id="autonomous-dryrun-success-1",
        )

        self.assertEqual(result.create_status, 200)
        self.assertEqual(result.initial_task_status, "blocked")
        self.assertEqual(result.initial_supervision_queue_status, 200)
        self.assertEqual(result.initial_supervision_attention_type, "retryable_failure")
        self.assertEqual(result.supervisor_queue_status, 200)
        self.assertEqual(result.supervisor_decision_count, 1)
        self.assertEqual(result.supervisor_action_statuses, ("redispatch_triggered",))
        self.assertEqual(result.final_task_status, "completed")
        self.assertEqual(result.final_supervision_queue_status, 200)
        self.assertIsNone(result.final_supervision_attention_type)
        self.assertFalse(result.sample_runtime)

    def test_retryable_codex_supervision_dry_run_labels_sample_runtime(self) -> None:
        result = run_retryable_codex_supervision_dry_run(
            runtime_client=SampleCodexCloudRuntimeClient(),
            task_id="autonomous-dryrun-sample-1",
        )

        self.assertTrue(result.sample_runtime)
        self.assertEqual(result.initial_supervision_attention_type, "retryable_failure")
        self.assertIn("redispatch_triggered", result.supervisor_action_statuses)
        self.assertEqual(result.final_task_status, "completed")


if __name__ == "__main__":
    unittest.main()
