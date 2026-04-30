"""Tests for Symphony-compatible execution-substrate events."""

from __future__ import annotations

import unittest
from dataclasses import replace
from typing import Any

from modules.contracts.execution_substrate import (
    ExecutionSubstrateArtifactReference,
    ExecutionSubstrateEvent,
    ExecutionSubstrateEventType,
    ExecutionSubstrateIntent,
    ExecutionSubstrateIntentType,
    ExecutionSubstrateProvenance,
    ExecutionSubstrateValidationError,
    build_execution_substrate_intent,
    execution_substrate_intent_from_dict,
    execution_substrate_intent_to_dict,
    validate_execution_substrate_artifact_reference,
    validate_execution_substrate_event,
    validate_execution_substrate_handoff_preview,
    validate_execution_substrate_intent,
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

    def _handoff_preview(self) -> dict[str, Any]:
        intent = build_execution_substrate_intent(
            task_id="task-1",
            attention_type="retryable_failure",
            suggested_action="retry_or_redispatch",
            reason="Task is retryable.",
        )
        assert intent is not None
        intent_payload = execution_substrate_intent_to_dict(intent)
        return {
            "generated_at": "2026-04-30T15:00:00Z",
            "handoff_count": 1,
            "source": "execution_substrate_intents",
            "advisory_only": True,
            "dispatch_enabled": False,
            "completion_authority": "harness_verification",
            "handoffs": [
                {
                    "task_id": "task-1",
                    "attention_type": "retryable_failure",
                    "current_status": "blocked",
                    "last_activity_at": None,
                    "handoff": {
                        "adapter": "symphony-execution-substrate",
                        "mode": "render_only",
                        "intent": intent_payload,
                        "harness_boundary": {
                            "completion_authority": "harness_verification",
                            "advisory_only": True,
                            "runner_completion_is_truth": False,
                            "artifact_verification_required": True,
                        },
                        "runner_policy": {
                            "substrate_kind": "symphony-compatible",
                            "allowed_intent_type": "retry_execution",
                            "prohibited_actions": intent_payload["prohibited_actions"],
                        },
                        "callback": {
                            "events_endpoint": "/tasks/task-1/execution-substrate-events",
                            "events_url": "http://harness.test/tasks/task-1/execution-substrate-events",
                            "event_contract": "execution_substrate_event.v1",
                        },
                        "metadata": {
                            "task_id": "task-1",
                            "source": "harness_supervision_queue",
                            "safe_to_execute_live": False,
                        },
                    },
                },
            ],
        }

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

    def test_builds_retry_intent_as_advisory_harness_handoff(self) -> None:
        intent = build_execution_substrate_intent(
            task_id="task-1",
            attention_type="retryable_failure",
            suggested_action="retry_or_redispatch",
            reason="Task is retryable.",
        )

        self.assertIsNotNone(intent)
        assert intent is not None
        payload = execution_substrate_intent_to_dict(intent)

        self.assertEqual(payload["intent_type"], "retry_execution")
        self.assertEqual(payload["substrate_kind"], "symphony-compatible")
        self.assertEqual(payload["task_id"], "task-1")
        self.assertTrue(payload["advisory_only"])
        self.assertEqual(payload["events_endpoint"], "/tasks/task-1/execution-substrate-events")
        self.assertEqual(payload["completion_authority"], "harness_verification")
        self.assertIn("mark_harness_complete", payload["prohibited_actions"])
        self.assertIn("move_linear_to_done_as_truth", payload["prohibited_actions"])
        self.assertIn("auto_merge_without_policy", payload["prohibited_actions"])

        round_tripped = execution_substrate_intent_from_dict(payload)
        self.assertEqual(round_tripped.intent_type, intent.intent_type)
        self.assertEqual(round_tripped.task_id, intent.task_id)
        self.assertEqual(round_tripped.completion_authority, "harness_verification")

    def test_builds_stale_task_intent_as_investigation_request(self) -> None:
        intent = build_execution_substrate_intent(
            task_id="task-1",
            attention_type="stale_active_task",
            suggested_action="investigate_staleness",
            reason="Task is stale.",
        )

        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(
            intent.intent_type,
            ExecutionSubstrateIntentType.INVESTIGATE_OR_RESTART_EXECUTION,
        )

    def test_intent_builder_ignores_non_runner_attention_items(self) -> None:
        intent = build_execution_substrate_intent(
            task_id="task-1",
            attention_type="review_required",
            suggested_action="manual_review",
            reason="Review is required.",
        )

        self.assertIsNone(intent)

    def test_intent_rejects_completion_authority_transfer(self) -> None:
        intent = ExecutionSubstrateIntent(
            intent_type=ExecutionSubstrateIntentType.RETRY_EXECUTION,
            substrate_kind="symphony-compatible",
            task_id="task-1",
            source="harness_supervision_queue",
            reason="Task is retryable.",
            suggested_action="retry_or_redispatch",
            events_endpoint="/tasks/task-1/execution-substrate-events",
            completion_authority="symphony",
        )

        with self.assertRaisesRegex(
            ExecutionSubstrateValidationError,
            "completion_authority=harness_verification",
        ):
            validate_execution_substrate_intent(intent)

    def test_intent_rejects_missing_prohibited_actions(self) -> None:
        intent = ExecutionSubstrateIntent(
            intent_type=ExecutionSubstrateIntentType.RETRY_EXECUTION,
            substrate_kind="symphony-compatible",
            task_id="task-1",
            source="harness_supervision_queue",
            reason="Task is retryable.",
            suggested_action="retry_or_redispatch",
            events_endpoint="/tasks/task-1/execution-substrate-events",
            prohibited_actions=("mark_harness_complete",),
        )

        with self.assertRaisesRegex(
            ExecutionSubstrateValidationError,
            "missing required prohibited actions",
        ):
            validate_execution_substrate_intent(intent)

    def test_handoff_preview_guardrail_accepts_inert_preview(self) -> None:
        preview = self._handoff_preview()

        validated = validate_execution_substrate_handoff_preview(preview)

        self.assertIs(validated, preview)

    def test_handoff_preview_guardrail_rejects_live_dispatch(self) -> None:
        preview = self._handoff_preview()
        preview["dispatch_enabled"] = True

        with self.assertRaisesRegex(
            ExecutionSubstrateValidationError,
            "dispatch_enabled=false",
        ):
            validate_execution_substrate_handoff_preview(preview)

    def test_handoff_preview_guardrail_rejects_runner_completion_truth(self) -> None:
        preview = self._handoff_preview()
        handoff = preview["handoffs"][0]["handoff"]
        handoff["harness_boundary"]["runner_completion_is_truth"] = True

        with self.assertRaisesRegex(
            ExecutionSubstrateValidationError,
            "runner_completion_is_truth=false",
        ):
            validate_execution_substrate_handoff_preview(preview)

    def test_handoff_preview_guardrail_rejects_live_safe_flag(self) -> None:
        preview = self._handoff_preview()
        handoff = preview["handoffs"][0]["handoff"]
        handoff["metadata"]["safe_to_execute_live"] = True

        with self.assertRaisesRegex(
            ExecutionSubstrateValidationError,
            "safe_to_execute_live=false",
        ):
            validate_execution_substrate_handoff_preview(preview)


if __name__ == "__main__":
    unittest.main()
