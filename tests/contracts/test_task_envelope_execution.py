"""Tests for canonical execution event and advisory models."""

from __future__ import annotations

import unittest

from modules.contracts.task_envelope_execution import (
    AdvisoryCompletionClaim,
    ExecutionArtifactReference,
    ExecutionEvent,
    ExecutionModelValidationError,
    ExecutionProvenance,
    validate_execution_event,
)


class TaskEnvelopeExecutionModelTests(unittest.TestCase):
    def _base_event(self) -> ExecutionEvent:
        return ExecutionEvent(
            event_id="evt-1",
            task_id="task-123",
            attempt_id="attempt-1",
            event_type="execution_succeeded",
            occurred_at="2026-04-02T00:00:00Z",
            provenance=ExecutionProvenance(
                source_system="openclaw",
                source_type="executor_adapter",
                source_id="run-123",
                ingestion_id="ingress-1",
                recorder="openclaw-adapter",
            ),
            payload={"message": "run finished"},
            artifact_references=(
                ExecutionArtifactReference(
                    artifact_type="pull_request",
                    reference_id="123",
                    uri="https://github.com/sfayka/Harness/pull/123",
                ),
            ),
            advisory_completion=AdvisoryCompletionClaim(
                outcome="reported_success",
                summary="Executor reported completion",
                confidence=0.9,
                reasons=("exit_code_zero",),
            ),
        )

    def test_valid_terminal_event_with_completion_claim_is_accepted(self) -> None:
        event = self._base_event()

        validated = validate_execution_event(event)

        self.assertEqual(validated.event_id, "evt-1")
        self.assertEqual(validated.advisory_completion.outcome, "reported_success")

    def test_progress_event_rejects_advisory_completion_claim(self) -> None:
        with self.assertRaises(ExecutionModelValidationError):
            validate_execution_event(
                ExecutionEvent(
                    event_id="evt-2",
                    task_id="task-123",
                    attempt_id="attempt-1",
                    event_type="progress_reported",
                    occurred_at="2026-04-02T00:00:00Z",
                    provenance=ExecutionProvenance(
                        source_system="openclaw",
                        source_type="executor_adapter",
                        source_id="run-123",
                    ),
                    advisory_completion=AdvisoryCompletionClaim(outcome="reported_success"),
                )
            )

    def test_event_payload_cannot_encode_authoritative_status(self) -> None:
        with self.assertRaises(ExecutionModelValidationError):
            validate_execution_event(
                ExecutionEvent(
                    event_id="evt-3",
                    task_id="task-123",
                    attempt_id="attempt-1",
                    event_type="execution_failed",
                    occurred_at="2026-04-02T00:00:00Z",
                    provenance=ExecutionProvenance(
                        source_system="openclaw",
                        source_type="executor_adapter",
                        source_id="run-123",
                    ),
                    payload={"status": "completed"},
                )
            )

    def test_confidence_must_be_within_zero_and_one(self) -> None:
        event = self._base_event()
        event_with_invalid_confidence = ExecutionEvent(
            event_id=event.event_id,
            task_id=event.task_id,
            attempt_id=event.attempt_id,
            event_type=event.event_type,
            occurred_at=event.occurred_at,
            provenance=event.provenance,
            payload=event.payload,
            artifact_references=event.artifact_references,
            advisory_completion=AdvisoryCompletionClaim(
                outcome="reported_success",
                confidence=1.5,
            ),
        )

        with self.assertRaises(ExecutionModelValidationError):
            validate_execution_event(event_with_invalid_confidence)


if __name__ == "__main__":
    unittest.main()
