from __future__ import annotations

import unittest

from modules.connectors import OpenClawIngressInputError, translate_openclaw_submission_payload


class OpenClawIngressTranslationTests(unittest.TestCase):
    def _payload(self) -> dict:
        return {
            "task_id": "task-openclaw-ingress-1",
            "requested_by": "operator@example.com",
            "context": {
                "conversation_id": "conv-123",
                "message_id": "msg-456",
                "channel": "cli",
                "workspace_id": "workspace-1",
                "user_id": "operator@example.com",
                "agent_id": "openclaw-assistant",
            },
            "task": {
                "title": "Implement OpenClaw ingress path",
                "description": "Submit work from OpenClaw via a canonical Harness ingress endpoint.",
                "acceptance_criteria": [
                    "Harness persists the task.",
                    "OpenClaw provenance remains auditable.",
                ],
                "constraints": ["Keep canonical POST /tasks semantics."],
                "priority": "high",
                "status": "intake_ready",
            },
            "metadata": {"source": "openclaw-integration-test"},
            "external_facts": {"expected_code_context": {"repository_owner": "sfayka"}},
            "claimed_completion": False,
            "acceptance_criteria_satisfied": False,
            "unresolved_conditions": ["Awaiting external evidence."],
        }

    def test_translate_openclaw_submission_payload_generates_canonical_request(self) -> None:
        payload = translate_openclaw_submission_payload(self._payload())
        request = payload["request"]
        task = request["task_envelope"]

        self.assertEqual(task["id"], "task-openclaw-ingress-1")
        self.assertEqual(task["status"], "blocked")
        self.assertEqual(task["origin"]["source_system"], "openclaw")
        self.assertEqual(task["origin"]["source_id"], "msg-456")
        self.assertEqual(task["origin"]["ingress_id"], "conv-123")
        self.assertEqual(task["extensions"]["openclaw"]["conversation_id"], "conv-123")
        self.assertEqual(task["extensions"]["openclaw"]["metadata"]["source"], "openclaw-integration-test")
        self.assertEqual(task["clarification"]["status"], "required")
        self.assertEqual(task["clarification"]["resume_target_status"], "intake_ready")
        self.assertEqual(
            task["clarification"]["required_inputs"][0]["description"],
            "Awaiting external evidence.",
        )
        self.assertNotIn("unresolved_conditions", request)

    def test_translate_openclaw_submission_payload_requires_context_shape(self) -> None:
        payload = self._payload()
        payload["context"] = "invalid"

        with self.assertRaises(OpenClawIngressInputError):
            translate_openclaw_submission_payload(payload)

    def test_translate_openclaw_submission_payload_allows_planned_handoff_status(self) -> None:
        payload = self._payload()
        payload["task"]["status"] = "planned"
        payload["task"]["objective_summary"] = "Produce a routing-ready implementation task."
        payload["task"]["objective_deliverable_type"] = "code_change"
        payload["task"]["objective_success_signal"] = "The task is defined enough to route without clarification."
        payload["task"]["parent_task_id"] = "epic-openclaw-1"
        payload["task"]["dependencies"] = [
            {
                "task_id": "task-upstream-1",
                "dependency_type": "blocks",
                "required_status": "completed",
                "description": "Upstream repository bootstrap must finish first.",
            }
        ]
        payload["task"]["required_capabilities"] = ["github", "python"]
        payload["metadata"]["plan_summary"] = "Single-task implementation handoff is ready for dispatcher review."
        payload["unresolved_conditions"] = []

        translated = translate_openclaw_submission_payload(payload)

        self.assertEqual(translated["request"]["task_envelope"]["status"], "planned")
        self.assertEqual(translated["request"]["task_envelope"]["parent_task_id"], "epic-openclaw-1")
        self.assertEqual(
            translated["request"]["task_envelope"]["dependencies"][0]["task_id"],
            "task-upstream-1",
        )
        self.assertEqual(
            translated["request"]["task_envelope"]["required_capabilities"],
            ["github", "python"],
        )

    def test_translate_openclaw_submission_payload_rejects_execution_or_terminal_status(self) -> None:
        for invalid_status in ("dispatch_ready", "assigned", "executing", "completed"):
            payload = self._payload()
            payload["task"]["status"] = invalid_status

            with self.assertRaises(OpenClawIngressInputError):
                translate_openclaw_submission_payload(payload)

    def test_translate_openclaw_submission_payload_rejects_planned_handoff_without_explicit_objective_contract(self) -> None:
        payload = self._payload()
        payload["task"]["status"] = "planned"

        with self.assertRaises(OpenClawIngressInputError):
            translate_openclaw_submission_payload(payload)

        payload = self._payload()
        payload["task"]["status"] = "planned"
        payload["task"]["objective_summary"] = "Produce a routing-ready implementation task."
        payload["task"]["objective_deliverable_type"] = "unspecified"
        payload["task"]["objective_success_signal"] = "The task is defined enough to route without clarification."
        payload["metadata"]["plan_summary"] = "Single-task implementation handoff is ready for dispatcher review."

        with self.assertRaises(OpenClawIngressInputError):
            translate_openclaw_submission_payload(payload)

        payload = self._payload()
        payload["task"]["status"] = "planned"
        payload["task"]["objective_summary"] = "Produce a routing-ready implementation task."
        payload["task"]["objective_deliverable_type"] = "code_change"
        payload["task"]["objective_success_signal"] = "The task is defined enough to route without clarification."
        payload["unresolved_conditions"] = []

        with self.assertRaisesRegex(OpenClawIngressInputError, "metadata.plan_summary"):
            translate_openclaw_submission_payload(payload)

    def test_translate_openclaw_submission_payload_rejects_planned_handoff_with_unresolved_conditions(self) -> None:
        payload = self._payload()
        payload["task"]["status"] = "planned"
        payload["task"]["objective_summary"] = "Produce a routing-ready implementation task."
        payload["task"]["objective_deliverable_type"] = "code_change"
        payload["task"]["objective_success_signal"] = "The task is defined enough to route without clarification."

        with self.assertRaises(OpenClawIngressInputError):
            translate_openclaw_submission_payload(payload)

    def test_translate_openclaw_submission_payload_rejects_self_referential_plan_structure(self) -> None:
        payload = self._payload()
        payload["task"]["status"] = "planned"
        payload["task"]["objective_summary"] = "Produce a routing-ready implementation task."
        payload["task"]["objective_deliverable_type"] = "code_change"
        payload["task"]["objective_success_signal"] = "The task is defined enough to route without clarification."
        payload["metadata"]["plan_summary"] = "Single-task implementation handoff is ready for dispatcher review."
        payload["unresolved_conditions"] = []
        payload["task"]["dependencies"] = [
            {
                "task_id": "task-openclaw-ingress-1",
                "dependency_type": "blocks",
                "required_status": "completed",
            }
        ]

        with self.assertRaisesRegex(OpenClawIngressInputError, "self-dependency"):
            translate_openclaw_submission_payload(payload)

    def test_translate_openclaw_submission_payload_rejects_completion_claim_fields(self) -> None:
        payload = self._payload()
        payload["claimed_completion"] = True

        with self.assertRaises(OpenClawIngressInputError):
            translate_openclaw_submission_payload(payload)

        payload = self._payload()
        payload["acceptance_criteria_satisfied"] = True

        with self.assertRaises(OpenClawIngressInputError):
            translate_openclaw_submission_payload(payload)

    def test_translate_openclaw_submission_payload_rejects_runtime_facts(self) -> None:
        payload = self._payload()
        payload["runtime_facts"] = {"attempt_count": 1}

        with self.assertRaises(OpenClawIngressInputError):
            translate_openclaw_submission_payload(payload)


if __name__ == "__main__":
    unittest.main()
