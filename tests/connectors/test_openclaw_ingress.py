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
            "runtime_facts": {"attempt_count": 1},
            "claimed_completion": False,
            "acceptance_criteria_satisfied": False,
            "unresolved_conditions": ["Awaiting external evidence."],
        }

    def test_translate_openclaw_submission_payload_generates_canonical_request(self) -> None:
        payload = translate_openclaw_submission_payload(self._payload())
        request = payload["request"]
        task = request["task_envelope"]

        self.assertEqual(task["id"], "task-openclaw-ingress-1")
        self.assertEqual(task["origin"]["source_system"], "openclaw")
        self.assertEqual(task["origin"]["source_id"], "msg-456")
        self.assertEqual(task["origin"]["ingress_id"], "conv-123")
        self.assertEqual(task["extensions"]["openclaw"]["conversation_id"], "conv-123")
        self.assertEqual(task["extensions"]["openclaw"]["metadata"]["source"], "openclaw-integration-test")
        self.assertEqual(request["runtime_facts"]["attempt_count"], 1)
        self.assertEqual(request["unresolved_conditions"], ["Awaiting external evidence."])

    def test_translate_openclaw_submission_payload_requires_context_shape(self) -> None:
        payload = self._payload()
        payload["context"] = "invalid"

        with self.assertRaises(OpenClawIngressInputError):
            translate_openclaw_submission_payload(payload)


if __name__ == "__main__":
    unittest.main()
