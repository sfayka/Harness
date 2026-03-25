from __future__ import annotations

import unittest

from modules.contracts.task_envelope_lifecycle import (
    ForbiddenTransitionError,
    TransitionAuthorityError,
    TransitionPreconditionError,
    apply_task_transition,
    validate_task_transition,
)
from modules.intake import create_task_envelope


def _base_task() -> dict:
    return create_task_envelope(
        {
            "id": "task-lifecycle-1",
            "title": "Lifecycle primitive coverage",
            "description": "Exercise TaskEnvelope state enforcement primitives.",
            "origin": {
                "source_system": "openclaw",
                "source_type": "ingress_request",
                "source_id": "req-lifecycle-1",
            },
            "acceptance_criteria": [
                {
                    "id": "ac-1",
                    "description": "Lifecycle transitions are enforced in code.",
                    "required": True,
                }
            ],
        },
        now="2026-03-25T12:00:00Z",
    )


class TaskEnvelopeLifecycleTests(unittest.TestCase):
    def test_allows_planner_transition_and_records_history(self) -> None:
        result = apply_task_transition(
            _base_task(),
            to_status="planned",
            actor="planner",
            reason="Planning preconditions satisfied.",
            now="2026-03-25T12:05:00Z",
        )

        self.assertEqual(result.from_status, "intake_ready")
        self.assertEqual(result.to_status, "planned")
        self.assertEqual(result.task_envelope["status"], "planned")
        self.assertEqual(result.task_envelope["timestamps"]["updated_at"], "2026-03-25T12:05:00Z")
        self.assertEqual(
            result.task_envelope["status_history"],
            [
                {
                    "from_status": "intake_ready",
                    "to_status": "planned",
                    "changed_at": "2026-03-25T12:05:00Z",
                    "reason": "Planning preconditions satisfied.",
                    "changed_by": "planner",
                }
            ],
        )

    def test_rejects_forbidden_transition(self) -> None:
        with self.assertRaisesRegex(ForbiddenTransitionError, "Forbidden lifecycle transition"):
            validate_task_transition(
                _base_task(),
                to_status="assigned",
                actor="dispatcher",
                reason="Skip directly to assignment.",
            )

    def test_rejects_wrong_authority(self) -> None:
        task = apply_task_transition(
            _base_task(),
            to_status="planned",
            actor="planner",
            reason="Ready for planning.",
            now="2026-03-25T12:05:00Z",
        ).task_envelope

        with self.assertRaisesRegex(TransitionAuthorityError, "not authorized"):
            validate_task_transition(
                task,
                to_status="dispatch_ready",
                actor="dispatcher",
                reason="Dispatcher should not finalize planning.",
            )

    def test_rejects_assignment_without_active_executor(self) -> None:
        task = apply_task_transition(
            _base_task(),
            to_status="planned",
            actor="planner",
            reason="Plan created.",
            now="2026-03-25T12:05:00Z",
        ).task_envelope
        task = apply_task_transition(
            task,
            to_status="dispatch_ready",
            actor="planner",
            reason="Routing preconditions satisfied.",
            now="2026-03-25T12:06:00Z",
        ).task_envelope

        with self.assertRaisesRegex(TransitionPreconditionError, "assigned_executor"):
            validate_task_transition(
                task,
                to_status="assigned",
                actor="dispatcher",
                reason="Try to dispatch without assignment.",
            )

    def test_rejects_execution_start_without_real_start_fact(self) -> None:
        task = _base_task()
        task["status"] = "assigned"
        task["assigned_executor"] = {
            "executor_type": "codex",
            "executor_id": "executor-1",
            "assignment_reason": "Capability match.",
        }

        with self.assertRaisesRegex(TransitionPreconditionError, "execution-start fact"):
            validate_task_transition(
                task,
                to_status="executing",
                actor="runtime",
                reason="Attempted start without runtime fact.",
            )

    def test_allows_verified_completion_and_sets_completed_timestamp(self) -> None:
        task = _base_task()
        task["status"] = "executing"
        task["assigned_executor"] = {
            "executor_type": "codex",
            "executor_id": "executor-1",
            "assignment_reason": "Capability match.",
        }
        task["artifacts"]["completion_evidence"] = {
            "policy": "required",
            "status": "satisfied",
            "required_artifact_types": ["commit"],
            "validated_artifact_ids": ["artifact-1"],
            "validation_method": "external_reconciliation",
            "validated_at": "2026-03-25T12:20:00Z",
            "validator": {
                "source_system": "harness",
                "source_type": "manual",
                "source_id": "verification-1",
                "captured_by": "verification",
            },
            "notes": None,
        }

        result = apply_task_transition(
            task,
            to_status="completed",
            actor="verification",
            reason="Verification accepted the completed outcome.",
            now="2026-03-25T12:21:00Z",
            facts={
                "verification_passed": True,
                "acceptance_criteria_satisfied": True,
                "reconciliation_passed": True,
            },
        )

        self.assertEqual(result.task_envelope["status"], "completed")
        self.assertEqual(result.task_envelope["timestamps"]["completed_at"], "2026-03-25T12:21:00Z")
        self.assertEqual(result.task_envelope["status_history"][-1]["to_status"], "completed")

    def test_rejects_completion_without_verification_preconditions(self) -> None:
        task = _base_task()
        task["status"] = "executing"

        with self.assertRaisesRegex(TransitionPreconditionError, "passing verification"):
            validate_task_transition(
                task,
                to_status="completed",
                actor="verification",
                reason="Attempt completion without verification facts.",
            )

    def test_completed_to_blocked_clears_completed_timestamp(self) -> None:
        task = _base_task()
        task["status"] = "completed"
        task["timestamps"]["completed_at"] = "2026-03-25T12:30:00Z"

        result = apply_task_transition(
            task,
            to_status="blocked",
            actor="verification",
            reason="Later reconciliation invalidated the completed outcome.",
            now="2026-03-25T12:35:00Z",
        )

        self.assertEqual(result.task_envelope["status"], "blocked")
        self.assertIsNone(result.task_envelope["timestamps"]["completed_at"])
        self.assertEqual(result.task_envelope["status_history"][-1]["from_status"], "completed")

    def test_blocked_to_completed_is_allowed_when_verification_later_resolves_the_blocker(self) -> None:
        task = _base_task()
        task["status"] = "blocked"
        task["artifacts"]["completion_evidence"] = {
            "policy": "required",
            "status": "satisfied",
            "required_artifact_types": ["commit"],
            "validated_artifact_ids": ["artifact-1"],
            "validation_method": "external_reconciliation",
            "validated_at": "2026-03-25T12:40:00Z",
            "validator": {
                "source_system": "harness",
                "source_type": "verification",
                "source_id": "verification-2",
                "captured_by": "verification",
            },
            "notes": "Later evidence resolved the blocked completion claim.",
        }

        result = apply_task_transition(
            task,
            to_status="completed",
            actor="verification",
            reason="Previously blocked completion claim is now verified.",
            now="2026-03-25T12:41:00Z",
            facts={
                "verification_passed": True,
                "acceptance_criteria_satisfied": True,
                "reconciliation_passed": True,
            },
        )

        self.assertEqual(result.task_envelope["status"], "completed")
        self.assertEqual(result.task_envelope["timestamps"]["completed_at"], "2026-03-25T12:41:00Z")
        self.assertEqual(result.task_envelope["status_history"][-1]["from_status"], "blocked")
        self.assertEqual(result.task_envelope["status_history"][-1]["to_status"], "completed")

    def test_blocked_to_planned_rejects_unresolved_clarification(self) -> None:
        task = _base_task()
        task["status"] = "blocked"
        task["clarification"] = {
            "status": "requested",
            "blocking_reason": "waiting_on_human_input",
            "resume_target_status": "planned",
            "required_inputs": [
                {
                    "id": "input-1",
                    "label": "Target repo",
                    "description": "Need repository target.",
                    "required": True,
                    "need_type": "missing",
                    "status": "open",
                    "value_summary": None,
                }
            ],
            "questions": [],
            "responses": [],
            "requested_at": "2026-03-25T12:01:00Z",
            "resolved_at": None,
            "requested_by": "clarification",
            "resolution_summary": None,
        }

        with self.assertRaisesRegex(TransitionPreconditionError, "clarification"):
            validate_task_transition(
                task,
                to_status="planned",
                actor="planner",
                reason="Attempting to resume planning too early.",
            )


if __name__ == "__main__":
    unittest.main()
