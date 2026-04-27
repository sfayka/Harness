"""Tests for Symphony-compatible execution-substrate events."""

from __future__ import annotations

import unittest
from dataclasses import replace

from modules.contracts.execution_substrate import (
    ExecutionSubstrateArtifactReference,
    ExecutionSubstrateEvent,
    ExecutionSubstrateEventType,
    ExecutionSubstrateProvenance,
    ExecutionSubstrateValidationError,
    validate_execution_substrate_artifact_reference,
    validate_execution_substrate_event,
)


class ExecutionSubstrateEventTests(unittest.TestCase):
    def _provenance(self) -> ExecutionSubstrateProvenance:
        return ExecutionSubstrateProvenance(
            source_system="symphony",
            source_type="runner_event",
            source_id="runner-session-1:event-1",
            captured_by="execution_substrate_adapter",
        )

    def _event(self, event_type: ExecutionSubstrateEventType) -> ExecutionSubstrateEvent:
        return ExecutionSubstrateEvent(
            event_id="event-1",
            task_id="task-1",
            attempt_id="attempt-1",
            runner_kind="symphony",
            runner_session_id="runner-session-1",
            executor_kind="codex_app_server",
            workspace_id="workspace/task-1",
            event_type=event_type,
            occurred_at="2026-04-27T20:00:00Z",
            provenance=self._provenance(),
        )

    def test_validate_event_accepts_runner_handoff(self) -> None:
        event = self._event(ExecutionSubstrateEventType.HANDOFF_REPORTED)

        validated = validate_execution_substrate_event(event)

        self.assertEqual(validated.event_type, ExecutionSubstrateEventType.HANDOFF_REPORTED)
        self.assertEqual(validated.runner_kind, "symphony")

    def test_executor_completed_event_remains_advisory_only(self) -> None:
        event = replace(
            self._event(ExecutionSubstrateEventType.RUN_COMPLETED_BY_EXECUTOR),
            payload={
                "reported_complete": True,
                "handoff_state": "human_review",
                "summary": "Executor reports the work is ready for Harness verification.",
            },
        )

        validated = validate_execution_substrate_event(event)

        self.assertTrue(validated.payload["reported_complete"])
        self.assertNotIn("target_status", validated.payload)
        self.assertNotIn("verified_complete", validated.payload)

    def test_event_rejects_lifecycle_authority_payload(self) -> None:
        event = replace(
            self._event(ExecutionSubstrateEventType.RUN_COMPLETED_BY_EXECUTOR),
            payload={
                "reported_complete": True,
                "target_status": "completed",
            },
        )

        with self.assertRaisesRegex(
            ExecutionSubstrateValidationError,
            "prohibited lifecycle authority",
        ):
            validate_execution_substrate_event(event)

    def test_runner_reported_artifacts_start_unverified(self) -> None:
        artifact = ExecutionSubstrateArtifactReference(
            artifact_type="pull_request",
            repository="sfayka/Harness",
            branch="codex/task-1",
            pr_url="https://github.com/sfayka/Harness/pull/1",
            reported_by="symphony",
            reported_at="2026-04-27T20:00:00Z",
            source_attempt_id="attempt-1",
        )

        validated = validate_execution_substrate_artifact_reference(artifact)

        self.assertEqual(validated.verification_status, "unverified")

    def test_runner_reported_artifact_cannot_self_verify(self) -> None:
        artifact = ExecutionSubstrateArtifactReference(
            artifact_type="pull_request",
            repository="sfayka/Harness",
            pr_url="https://github.com/sfayka/Harness/pull/1",
            reported_by="symphony",
            reported_at="2026-04-27T20:00:00Z",
            source_attempt_id="attempt-1",
            verification_status="verified",
        )

        with self.assertRaisesRegex(
            ExecutionSubstrateValidationError,
            "must not start with verification_status=verified",
        ):
            validate_execution_substrate_artifact_reference(artifact)


if __name__ == "__main__":
    unittest.main()
