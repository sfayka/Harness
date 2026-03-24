from __future__ import annotations

import unittest

from modules.contracts.task_envelope_validation import validate_task_envelope


def _base_task_envelope() -> dict:
    return {
        "id": "task-clarification-1",
        "title": "Clarify repository target",
        "description": "Task used to validate clarification contract behavior.",
        "origin": {
            "source_system": "openclaw",
            "source_type": "ingress_request",
            "source_id": "req-clarification-1",
            "ingress_id": None,
            "ingress_name": "OpenClaw",
            "requested_by": None,
        },
        "status": "blocked",
        "timestamps": {
            "created_at": "2026-03-24T18:00:00Z",
            "updated_at": "2026-03-24T18:05:00Z",
            "completed_at": None,
        },
        "status_history": [
            {
                "from_status": "intake_ready",
                "to_status": "blocked",
                "changed_at": "2026-03-24T18:05:00Z",
                "reason": "Required repository context is missing.",
                "changed_by": "harness",
            }
        ],
        "objective": {
            "summary": "Obtain the missing repository information and resume work safely.",
            "deliverable_type": "clarified_request",
            "success_signal": "Required clarification is resolved and the task can resume.",
        },
        "constraints": [],
        "acceptance_criteria": [
            {
                "id": "ac-1",
                "description": "The repository and target branch are clarified.",
                "required": True,
            }
        ],
        "parent_task_id": None,
        "child_task_ids": [],
        "dependencies": [],
        "assigned_executor": None,
        "required_capabilities": [],
        "priority": "normal",
        "artifacts": {
            "items": [],
            "completion_evidence": {
                "policy": "deferred",
                "status": "deferred",
                "required_artifact_types": [],
                "validated_artifact_ids": [],
                "validation_method": "deferred",
                "validated_at": None,
                "validator": None,
                "notes": None,
            },
        },
        "clarification": {
            "status": "requested",
            "blocking_reason": "waiting_on_human_input",
            "resume_target_status": "intake_ready",
            "required_inputs": [
                {
                    "id": "repo-target",
                    "label": "Target repository",
                    "description": "Repository where the requested work should occur.",
                    "required": True,
                    "need_type": "missing",
                    "status": "open",
                    "value_summary": None,
                }
            ],
            "questions": [
                {
                    "id": "question-1",
                    "input_id": "repo-target",
                    "prompt": "Which repository should this task be executed in?",
                    "status": "open",
                    "asked_at": "2026-03-24T18:04:00Z",
                    "asked_to": "requester",
                    "channel": "openclaw",
                }
            ],
            "responses": [],
            "requested_at": "2026-03-24T18:04:00Z",
            "resolved_at": None,
            "requested_by": "harness-intake",
            "resolution_summary": None,
        },
        "observability": {
            "errors": [],
            "retries": {
                "attempt_count": 0,
                "max_attempts": 0,
                "last_retry_at": None,
            },
            "execution_metadata": {},
        },
    }


class TaskEnvelopeClarificationSchemaTests(unittest.TestCase):
    def test_accepts_valid_blocked_task_with_clarification_contract(self) -> None:
        errors = validate_task_envelope(_base_task_envelope())
        self.assertEqual(errors, [])

    def test_rejects_invalid_clarification_need_type(self) -> None:
        task_envelope = _base_task_envelope()
        task_envelope["clarification"]["required_inputs"][0]["need_type"] = "guess"

        errors = validate_task_envelope(task_envelope)
        self.assertTrue(errors)
        self.assertTrue(any("/clarification/required_inputs/0/need_type" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
