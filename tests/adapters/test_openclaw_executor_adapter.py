"""Tests for minimal real OpenClaw executor adapter translation and normalization."""

from __future__ import annotations

import unittest

from modules.adapters.executor_adapter import ExecutorDispatchInput
from modules.adapters.openclaw import OpenClawExecutorAdapter
from modules.intake.task_envelope import create_task_envelope


class _FakeOpenClawClient:
    def __init__(self, response_payload: dict) -> None:
        self.response_payload = response_payload
        self.last_request: dict | None = None

    def execute(self, request_payload: dict) -> dict:
        self.last_request = request_payload
        return self.response_payload


class OpenClawExecutorAdapterTests(unittest.TestCase):
    def _dispatch_input(self) -> ExecutorDispatchInput:
        task_envelope = create_task_envelope(
            {
                "id": "task-oc-1",
                "title": "Implement minimal adapter",
                "description": "Map canonical task input to OpenClaw and normalize output",
                "origin": {
                    "source_system": "linear",
                    "source_type": "ingress_request",
                    "source_id": "KNO-157",
                },
                "constraints": [
                    {
                        "type": "policy",
                        "description": "Do not allow executor to mutate lifecycle directly",
                    }
                ],
                "acceptance_criteria": [
                    {
                        "id": "ac-1",
                        "description": "OpenClaw request shape is adapter-local",
                    },
                    {
                        "id": "ac-2",
                        "description": "Outputs are normalized into canonical execution advisory facts",
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
            attempt_id="attempt-oc-1",
            assigned_executor="openclaw-worker",
            context_references=("https://example.test/context/1",),
        )

    def test_dispatch_projects_canonical_input_to_openclaw_request(self) -> None:
        fake_client = _FakeOpenClawClient(
            response_payload={
                "run_id": "run-1",
                "events": [
                    {
                        "id": "evt-1",
                        "type": "run_started",
                        "timestamp": "2026-04-02T10:00:00Z",
                    },
                    {
                        "id": "evt-2",
                        "type": "run_succeeded",
                        "timestamp": "2026-04-02T10:05:00Z",
                    },
                ],
                "artifacts": [
                    {
                        "type": "pull_request",
                        "id": "pr-77",
                        "url": "https://github.com/sfayka/Harness/pull/77",
                    }
                ],
                "completion": {
                    "reported_complete": True,
                    "confidence": "medium",
                    "reason": "OpenClaw finished execution",
                },
            }
        )
        adapter = OpenClawExecutorAdapter(runtime_client=fake_client)

        dispatch_input = self._dispatch_input()
        output = adapter.dispatch(dispatch_input)

        assert fake_client.last_request is not None
        self.assertEqual(fake_client.last_request["task"]["id"], "task-oc-1")
        self.assertEqual(fake_client.last_request["task"]["attempt_id"], "attempt-oc-1")
        self.assertEqual(fake_client.last_request["task"]["required_artifacts"], ["pull_request", "commit"])
        self.assertEqual(fake_client.last_request["executor"]["target"], "openclaw-worker")

        self.assertEqual(output.events[0].event_type.value, "execution_started")
        self.assertEqual(output.events[1].event_type.value, "execution_succeeded")
        self.assertEqual(output.events[1].advisory_completion.reported_complete, True)
        self.assertEqual(output.events[1].provenance.source_system, "openclaw")
        self.assertEqual(output.artifact_references[0].artifact_type, "pull_request")
        self.assertTrue(output.metadata["advisory_only"])

    def test_dispatch_rejects_unknown_openclaw_event_type(self) -> None:
        fake_client = _FakeOpenClawClient(
            response_payload={
                "run_id": "run-2",
                "events": [
                    {
                        "id": "evt-1",
                        "type": "unknown",
                        "timestamp": "2026-04-02T10:00:00Z",
                    }
                ],
                "artifacts": [],
            }
        )
        adapter = OpenClawExecutorAdapter(runtime_client=fake_client)

        with self.assertRaisesRegex(ValueError, "Unsupported OpenClaw event type"):
            adapter.dispatch(self._dispatch_input())


if __name__ == "__main__":
    unittest.main()
