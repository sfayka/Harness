"""Tests for Codex Cloud executor adapter preflight enforcement and normalization."""

from __future__ import annotations

import unittest

from modules.adapters.codex_cloud import CodexCloudExecutorAdapter
from modules.adapters.executor_adapter import ExecutorDispatchInput
from modules.intake.task_envelope import create_task_envelope


class _FakeCodexCloudClient:
    def __init__(self, response_payload: dict) -> None:
        self.response_payload = response_payload
        self.last_request: dict | None = None

    def execute(self, request_payload: dict) -> dict:
        self.last_request = request_payload
        return self.response_payload


class CodexCloudExecutorAdapterTests(unittest.TestCase):
    def _dispatch_input(self) -> ExecutorDispatchInput:
        task_envelope = create_task_envelope(
            {
                "id": "task-codex-cloud-1",
                "title": "Implement Codex Cloud adapter",
                "description": "Require bootstrap preflight before trusting executor output",
                "origin": {
                    "source_system": "linear",
                    "source_type": "ingress_request",
                    "source_id": "KNO-999",
                },
                "constraints": [
                    {
                        "type": "policy",
                        "description": "Do not trust executor summaries without external proof.",
                    }
                ],
                "acceptance_criteria": [
                    {
                        "id": "ac-1",
                        "description": "Codex Cloud preflight is present and valid.",
                    },
                    {
                        "id": "ac-2",
                        "description": "Branch, commit, and PR proof are normalized canonically.",
                    },
                ],
            }
        )
        task_envelope["artifacts"]["completion_evidence"]["required_artifact_types"] = [
            "pull_request",
            "commit",
        ]
        return ExecutorDispatchInput.from_task_envelope(
            task_envelope,
            attempt_id="attempt-codex-cloud-1",
            assigned_executor="codex",
            context_references=("https://linear.app/knoxanalytics/issue/KNO-999",),
        )

    def test_dispatch_projects_canonical_input_to_codex_cloud_request_and_normalizes_success(self) -> None:
        fake_client = _FakeCodexCloudClient(
            response_payload={
                "run_id": "codex-run-1",
                "preflight": {
                    "pwd": "/workspace/Harness",
                    "git_remote_v": (
                        "origin\thttps://github.com/sfayka/Harness.git (fetch)\n"
                        "origin\thttps://github.com/sfayka/Harness.git (push)"
                    ),
                    "bootstrap_proof": "bootstrap ok",
                },
                "events": [
                    {"id": "evt-1", "type": "run_started", "timestamp": "2026-04-12T12:00:00Z"},
                    {"id": "evt-2", "type": "run_succeeded", "timestamp": "2026-04-12T12:05:00Z"},
                ],
                "artifacts": [
                    {
                        "type": "branch",
                        "id": "branch-1",
                        "external_id": "codex/task-codex-cloud-1",
                        "head_commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                    },
                    {
                        "type": "commit",
                        "id": "commit-1",
                        "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                        "url": "https://github.com/sfayka/Harness/commit/8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                    },
                    {
                        "type": "pull_request",
                        "id": "pr-1",
                        "url": "https://github.com/sfayka/Harness/pull/999",
                        "number": 999,
                        "state": "open",
                        "merged": False,
                        "branch_name": "codex/task-codex-cloud-1",
                        "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                    },
                ],
                "completion": {
                    "reported_complete": True,
                    "confidence": "high",
                    "reason": "Codex Cloud produced repository-backed artifacts",
                },
            }
        )
        adapter = CodexCloudExecutorAdapter(runtime_client=fake_client)

        output = adapter.dispatch(self._dispatch_input())

        assert fake_client.last_request is not None
        self.assertEqual(
            fake_client.last_request["execution"]["bootstrap_command"],
            "bash /workspace/Harness/scripts/codex-cloud-setup.sh",
        )
        self.assertEqual(
            fake_client.last_request["execution"]["preflight_commands"],
            ["pwd", "git remote -v", "cat .codex-bootstrap-proof"],
        )
        self.assertEqual(fake_client.last_request["task"]["id"], "task-codex-cloud-1")
        self.assertEqual(output.events[0].event_type.value, "execution_started")
        self.assertEqual(output.events[-1].event_type.value, "execution_succeeded")
        self.assertTrue(output.events[-1].advisory_completion.reported_complete)
        self.assertEqual(len(output.artifact_references), 3)
        branch_ref, commit_ref, pr_ref = output.artifact_references
        self.assertEqual(branch_ref.metadata["branch_name"], "codex/task-codex-cloud-1")
        self.assertEqual(branch_ref.metadata["head_commit_sha"], "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705")
        self.assertEqual(commit_ref.metadata["repository_owner"], "sfayka")
        self.assertEqual(commit_ref.metadata["repository_name"], "Harness")
        self.assertEqual(pr_ref.metadata["pull_request_state"], "open")
        self.assertEqual(pr_ref.metadata["pull_request_number"], 999)
        self.assertEqual(output.metadata["adapter"], "codex-cloud")
        self.assertTrue(output.metadata["preflight_passed"])

    def test_dispatch_blocks_when_preflight_contract_is_invalid(self) -> None:
        fake_client = _FakeCodexCloudClient(
            response_payload={
                "run_id": "codex-run-2",
                "preflight": {
                    "pwd": "/workspace/OtherRepo",
                    "git_remote_v": "origin\thttps://github.com/sfayka/Harness.git (fetch)",
                    "bootstrap_proof": "",
                },
                "artifacts": [],
                "completion": {
                    "reported_complete": True,
                    "confidence": "high",
                    "reason": "This should not be trusted",
                },
            }
        )
        adapter = CodexCloudExecutorAdapter(runtime_client=fake_client)

        output = adapter.dispatch(self._dispatch_input())

        self.assertEqual(output.events[0].event_type.value, "execution_started")
        self.assertEqual(output.events[-1].event_type.value, "execution_failed")
        self.assertIsNone(output.events[-1].advisory_completion)
        self.assertFalse(output.metadata["preflight_passed"])
        self.assertIn("wrong repository root", output.metadata["preflight_failure_reason"])


if __name__ == "__main__":
    unittest.main()
