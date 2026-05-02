from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.render_api_examples import STABLE_EXAMPLE_TIMESTAMP, render_examples


class RenderApiExamplesTests(unittest.TestCase):
    def test_create_task_example_uses_stable_timestamp_and_current_contract_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = render_examples(Path(temp_dir))

            payload = json.loads((output_dir / "create-task.json").read_text(encoding="utf-8"))

        task = payload["request"]["task_envelope"]
        self.assertEqual(task["timestamps"]["created_at"], STABLE_EXAMPLE_TIMESTAMP)
        self.assertEqual(task["timestamps"]["updated_at"], STABLE_EXAMPLE_TIMESTAMP)
        self.assertEqual(task["coordination"], {"linear": None})
        self.assertEqual(task["reconciliation"]["status"], "not_required")

    def test_evaluation_examples_include_retry_context_contract_field(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = render_examples(Path(temp_dir))

            payload = json.loads((output_dir / "evaluate-happy-path.json").read_text(encoding="utf-8"))

        self.assertIn("retry_context", payload["request"])
        self.assertIsNone(payload["request"]["retry_context"])


if __name__ == "__main__":
    unittest.main()
