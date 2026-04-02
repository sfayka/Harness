"""Tests for canonical execution advisory models."""

from __future__ import annotations

import unittest

from modules.contracts.execution_advisory import (
    AdvisoryCompletionClaim,
    ArtifactReference,
    ExecutionAdvisoryValidationError,
    ExecutionEvent,
    ExecutionEventType,
    ExecutionProvenance,
    derive_runtime_advisory_facts,
    validate_execution_event,
)


class ExecutionAdvisoryModelTests(unittest.TestCase):
    def _provenance(self) -> ExecutionProvenance:
        return ExecutionProvenance(
            source_system="openclaw",
            source_type="executor_event",
            source_id="evt-1",
            captured_by="adapter",
        )

    def _event(self, event_type: ExecutionEventType) -> ExecutionEvent:
        return ExecutionEvent(
            event_id="event-1",
            task_id="task-1",
            attempt_id="attempt-1",
            event_type=event_type,
            occurred_at="2026-04-01T00:00:00Z",
            provenance=self._provenance(),
        )

    def test_validate_execution_event_accepts_valid_event(self) -> None:
        event = self._event(ExecutionEventType.EXECUTION_STARTED)
        validated = validate_execution_event(event)
        self.assertEqual(validated.event_type, ExecutionEventType.EXECUTION_STARTED)

    def test_validate_execution_event_rejects_lifecycle_authority_fields(self) -> None:
        with self.assertRaises(ExecutionAdvisoryValidationError):
            validate_execution_event(
                ExecutionEvent(
                    event_id="event-1",
                    task_id="task-1",
                    attempt_id="attempt-1",
                    event_type=ExecutionEventType.EXECUTION_SUCCEEDED,
                    occurred_at="2026-04-01T00:00:00Z",
                    provenance=self._provenance(),
                    metadata={"target_status": "completed"},
                )
            )

    def test_validate_execution_event_rejects_artifact_without_locator(self) -> None:
        with self.assertRaises(ExecutionAdvisoryValidationError):
            validate_execution_event(
                ExecutionEvent(
                    event_id="event-1",
                    task_id="task-1",
                    attempt_id="attempt-1",
                    event_type=ExecutionEventType.ARTIFACT_ATTACHED,
                    occurred_at="2026-04-01T00:00:00Z",
                    provenance=self._provenance(),
                    artifact_references=(
                        ArtifactReference(
                            artifact_type="pull_request",
                            reference_id="artifact-pr-1",
                        ),
                    ),
                )
            )

    def test_validate_execution_event_rejects_completion_claim_lifecycle_authority(self) -> None:
        with self.assertRaises(ExecutionAdvisoryValidationError):
            validate_execution_event(
                ExecutionEvent(
                    event_id="event-1",
                    task_id="task-1",
                    attempt_id="attempt-1",
                    event_type=ExecutionEventType.EXECUTION_SUCCEEDED,
                    occurred_at="2026-04-01T00:00:00Z",
                    provenance=self._provenance(),
                    advisory_completion=AdvisoryCompletionClaim(
                        claim_id="claim-1",
                        reported_complete=True,
                        metadata={"canonical_status": "completed"},
                    ),
                )
            )

    def test_derive_runtime_advisory_facts_aggregates_attempts_and_outcomes(self) -> None:
        facts = derive_runtime_advisory_facts(
            (
                self._event(ExecutionEventType.EXECUTION_STARTED),
                ExecutionEvent(
                    event_id="event-2",
                    task_id="task-1",
                    attempt_id="attempt-2",
                    event_type=ExecutionEventType.EXECUTION_SUCCEEDED,
                    occurred_at="2026-04-01T00:01:00Z",
                    provenance=self._provenance(),
                    advisory_completion=AdvisoryCompletionClaim(
                        claim_id="claim-1",
                        reported_complete=True,
                    ),
                ),
            )
        )

        self.assertTrue(facts.executor_reported_success)
        self.assertFalse(facts.executor_reported_failure)
        self.assertFalse(facts.terminal_failure)
        self.assertEqual(facts.attempt_count, 2)


if __name__ == "__main__":
    unittest.main()
