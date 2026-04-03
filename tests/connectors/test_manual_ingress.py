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


if __name__ == "__main__":
    unittest.main()
