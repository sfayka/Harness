"""Tests for ExecutorAdapter interface and stub behavior."""

from __future__ import annotations

import unittest

from modules.adapters.executor_adapter import (
    ExecutorAdapterInputError,
    ExecutorDispatchInput,
    StubExecutorAdapter,
)
from modules.intake.task_envelope import create_task_envelope


class ExecutorDispatchInputTests(unittest.TestCase):
    def test_from_task_envelope_projects_canonical_fields(self) -> None:
        task_envelope = create_task_envelope(
            {
                "id": "task-123",
                "title": "Implement adapter",
                "description": "Add executor adapter interface",
                "origin": {
                    "source_system": "linear",
                    "source_type": "issue",
                    "source_id": "KNO-153",
                },
                "constraints": [
                    {
                        "type": "policy",
                        "description": "Do not mutate lifecycle status from adapter",
                    }
                ],
                "acceptance_criteria": [
                    {
                        "id": "ac-1",
                        "description": "Adapter returns advisory execution outputs",
                    }
                ],
            }
        )
        task_envelope["artifacts"]["completion_evidence"]["required_artifact_types"] = [
            "pull_request",
            "commit",
        ]

        dispatch_input = ExecutorDispatchInput.from_task_envelope(
            task_envelope,
            attempt_id="attempt-1",
            assigned_executor="stub-executor",
            context_references=("https://example.test/context",),
        )

        self.assertEqual(dispatch_input.task_id, "task-123")
        self.assertEqual(
            dispatch_input.acceptance_criteria,
            ("Adapter returns advisory execution outputs",),
        )
        self.assertEqual(
            dispatch_input.required_artifact_types,
            ("pull_request", "commit"),
        )
        self.assertEqual(
            dispatch_input.constraints,
            ("Do not mutate lifecycle status from adapter",),
        )

    def test_from_task_envelope_rejects_invalid_envelope(self) -> None:
        with self.assertRaises(ExecutorAdapterInputError):
            ExecutorDispatchInput.from_task_envelope(
                {
                    "id": "task-1",
                    "title": "broken",
                    "description": "broken",
                    "objective": {"summary": "broken"},
                    "acceptance_criteria": [],
                },
                attempt_id="attempt-1",
                assigned_executor="stub-executor",
            )


class StubExecutorAdapterTests(unittest.TestCase):
    def test_dispatch_returns_advisory_only_valid_outputs(self) -> None:
        task_envelope = create_task_envelope(
            {
                "id": "task-123",
                "title": "Implement adapter",
                "description": "Add executor adapter interface",
                "origin": {
                    "source_system": "linear",
                    "source_type": "issue",
                    "source_id": "KNO-153",
                },
                "acceptance_criteria": [
                    {
                        "id": "ac-1",
                        "description": "Adapter returns advisory execution outputs",
                    }
                ],
            }
        )

        dispatch_input = ExecutorDispatchInput.from_task_envelope(
            task_envelope,
            attempt_id="attempt-99",
            assigned_executor="stub-executor",
        )

        adapter = StubExecutorAdapter(now_provider=lambda: "2026-04-02T00:00:00Z")
        output = adapter.dispatch(dispatch_input)

        self.assertEqual(len(output.events), 2)
        self.assertEqual(output.events[0].event_type.value, "execution_started")
        self.assertEqual(output.events[1].event_type.value, "execution_succeeded")
        self.assertTrue(output.events[1].advisory_completion.reported_complete)
        self.assertTrue(output.metadata["advisory_only"])
        self.assertEqual(len(output.artifact_references), 1)

    def test_dispatch_output_does_not_include_lifecycle_authority_fields(self) -> None:
        task_envelope = create_task_envelope(
            {
                "id": "task-123",
                "title": "Implement adapter",
                "description": "Add executor adapter interface",
                "origin": {
                    "source_system": "linear",
                    "source_type": "issue",
                    "source_id": "KNO-153",
                },
                "acceptance_criteria": [
                    {
                        "id": "ac-1",
                        "description": "Adapter returns advisory execution outputs",
                    }
                ],
            }
        )

        dispatch_input = ExecutorDispatchInput.from_task_envelope(
            task_envelope,
            attempt_id="attempt-101",
            assigned_executor="stub-executor",
        )

        output = StubExecutorAdapter(now_provider=lambda: "2026-04-02T00:00:00Z").dispatch(
            dispatch_input
        )

        prohibited = {"target_status", "canonical_status", "lifecycle_status", "authorized_transition"}

        for event in output.events:
            self.assertTrue(prohibited.isdisjoint(set(event.metadata.keys())))
            if event.advisory_completion is not None:
                self.assertTrue(
                    prohibited.isdisjoint(set(event.advisory_completion.metadata.keys()))
                )
        for artifact in output.artifact_references:
            self.assertTrue(prohibited.isdisjoint(set(artifact.metadata.keys())))


if __name__ == "__main__":
    unittest.main()
