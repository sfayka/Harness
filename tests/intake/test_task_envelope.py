from __future__ import annotations

import unittest

from modules.contracts.task_envelope_validation import (
    assert_valid_task_envelope,
    validate_task_envelope,
)
from modules.intake import create_task_envelope


class CreateTaskEnvelopeTests(unittest.TestCase):
    def test_maps_intake_input_into_valid_task_envelope(self) -> None:
        task_envelope = create_task_envelope(
            {
                "id": "task-123",
                "title": "Draft architecture baseline",
                "description": "Normalize this inbound request into the canonical task contract.",
                "origin": {
                    "source_system": "openclaw",
                    "source_type": "ingress_request",
                    "source_id": "req-123",
                    "ingress_id": "session-001",
                    "ingress_name": "OpenClaw",
                    "requested_by": "user-42",
                },
                "objective": {
                    "summary": "Create the first canonical TaskEnvelope for the request.",
                    "deliverable_type": "document",
                    "success_signal": "A valid TaskEnvelope exists and can be routed downstream.",
                },
                "constraints": [
                    {
                        "type": "scope",
                        "description": "Do not implement planner behavior.",
                        "required": True,
                    }
                ],
                "acceptance_criteria": [
                    {
                        "id": "ac-1",
                        "description": "Envelope validates against the JSON Schema.",
                        "required": True,
                    }
                ],
            },
            now="2026-03-24T12:00:00Z",
        )

        self.assertEqual(task_envelope["id"], "task-123")
        self.assertEqual(task_envelope["status"], "intake_ready")
        self.assertEqual(
            task_envelope["timestamps"],
            {
                "created_at": "2026-03-24T12:00:00Z",
                "updated_at": "2026-03-24T12:00:00Z",
                "completed_at": None,
            },
        )
        self.assertIsNone(task_envelope["parent_task_id"])
        self.assertEqual(task_envelope["child_task_ids"], [])
        self.assertEqual(task_envelope["dependencies"], [])
        self.assertIsNone(task_envelope["assigned_executor"])
        self.assertEqual(task_envelope["required_capabilities"], [])
        self.assertEqual(task_envelope["priority"], "normal")
        self.assertEqual(task_envelope["artifacts"], {"pr_links": [], "commit_shas": [], "logs": [], "outputs": []})

        assert_valid_task_envelope(task_envelope)

    def test_populates_only_schema_required_defaults_for_deferred_fields(self) -> None:
        task_envelope = create_task_envelope(
            {
                "title": "Investigate flaky test failure",
                "description": "Determine what is needed to unblock execution.",
                "origin": {
                    "source_system": "openclaw",
                    "source_type": "ingress_request",
                    "source_id": "req-456",
                },
                "acceptance_criteria": [
                    {
                        "description": "Task is represented in the canonical schema."
                    }
                ],
            },
            now="2026-03-24T12:15:00Z",
        )

        self.assertEqual(task_envelope["status"], "intake_ready")
        self.assertEqual(
            task_envelope["objective"]["summary"],
            "Determine what is needed to unblock execution.",
        )
        self.assertEqual(task_envelope["objective"]["deliverable_type"], "unspecified")
        self.assertEqual(
            task_envelope["objective"]["success_signal"],
            "Task satisfies declared acceptance criteria.",
        )
        self.assertEqual(task_envelope["constraints"], [])
        self.assertEqual(task_envelope["status_history"], [])
        self.assertEqual(
            task_envelope["observability"]["execution_metadata"]["schema_required_deferred_fields"],
            [
                "parent_task_id",
                "child_task_ids",
                "dependencies",
                "assigned_executor",
                "required_capabilities",
                "priority",
                "artifacts",
                "observability",
            ],
        )

    def test_schema_validation_reports_invalid_task_envelope_objects(self) -> None:
        errors = validate_task_envelope({"id": "bad-task"})
        self.assertTrue(errors)

    def test_rejects_missing_required_intake_fields(self) -> None:
        with self.assertRaisesRegex(ValueError, "title"):
            create_task_envelope(
                {
                    "description": "Missing a title.",
                    "origin": {
                        "source_system": "openclaw",
                        "source_type": "ingress_request",
                        "source_id": "req-789",
                    },
                    "acceptance_criteria": [
                        {
                            "description": "Should not be created."
                        }
                    ],
                }
            )

    def test_rejects_empty_acceptance_criteria(self) -> None:
        with self.assertRaisesRegex(ValueError, "acceptance_criteria"):
            create_task_envelope(
                {
                    "title": "Investigate failure mode",
                    "description": "Missing completion conditions.",
                    "origin": {
                        "source_system": "openclaw",
                        "source_type": "ingress_request",
                        "source_id": "req-999",
                    },
                    "acceptance_criteria": [],
                }
            )


if __name__ == "__main__":
    unittest.main()
