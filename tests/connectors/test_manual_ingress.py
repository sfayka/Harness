from __future__ import annotations

import unittest

from modules.connectors import ManualIngressInputError, translate_manual_submission_payload


class ManualIngressConnectorTests(unittest.TestCase):
    def _payload(self) -> dict:
        return {
            "task": {
                "title": "Verify canonical manual ingestion",
                "description": "Ensure manual task ingestion persists in Harness store.",
                "requested_by": "operator@example.com",
                "acceptance_criteria": [
                    {
                        "id": "ac-1",
                        "description": "Manual task is persisted in store-backed task list.",
                        "required": True,
                    }
                ],
            },
            "metadata": {"source": "manual-test"},
            "claimed_completion": False,
            "acceptance_criteria_satisfied": False,
        }

    def test_translate_manual_submission_payload_generates_task_id_when_omitted(self) -> None:
        payload = translate_manual_submission_payload(self._payload())
        task = payload["request"]["task_envelope"]

        self.assertIsInstance(task["id"], str)
        self.assertTrue(task["id"])
        self.assertEqual(task["origin"]["source_system"], "manual")
        self.assertEqual(task["extensions"]["manual"]["submission"]["metadata"]["source"], "manual-test")

    def test_translate_manual_submission_payload_requires_task_shape(self) -> None:
        with self.assertRaises(ManualIngressInputError):
            translate_manual_submission_payload({"task": "invalid"})

    def test_translate_manual_submission_payload_rejects_completion_shaped_fields(self) -> None:
        payload = self._payload()
        payload["claimed_completion"] = True
        with self.assertRaisesRegex(ManualIngressInputError, "cannot claim completion"):
            translate_manual_submission_payload(payload)

        payload = self._payload()
        payload["acceptance_criteria_satisfied"] = True
        with self.assertRaisesRegex(ManualIngressInputError, "cannot assert acceptance_criteria_satisfied"):
            translate_manual_submission_payload(payload)

        payload = self._payload()
        payload["runtime_facts"] = {"attempt_count": 1}
        with self.assertRaisesRegex(ManualIngressInputError, "cannot submit runtime_facts"):
            translate_manual_submission_payload(payload)

    def test_translate_manual_submission_payload_rejects_execution_artifacts_and_completion_evidence(self) -> None:
        payload = self._payload()
        payload["linked_artifacts"] = [{"id": "artifact-pr-1", "type": "pull_request"}]
        with self.assertRaisesRegex(ManualIngressInputError, "cannot attach repository execution artifacts"):
            translate_manual_submission_payload(payload)

        payload = self._payload()
        payload["completion_evidence"] = {"status": "satisfied"}
        with self.assertRaisesRegex(ManualIngressInputError, "cannot submit completion_evidence"):
            translate_manual_submission_payload(payload)

    def test_translate_manual_submission_payload_rejects_runtime_or_terminal_task_status(self) -> None:
        payload = self._payload()
        payload["task_status"] = "completed"
        with self.assertRaisesRegex(ManualIngressInputError, "task_status must be one of"):
            translate_manual_submission_payload(payload)


if __name__ == "__main__":
    unittest.main()
