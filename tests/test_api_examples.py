from __future__ import annotations

import json
from pathlib import Path
import unittest

from modules.api import parse_evaluation_request


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = REPO_ROOT / "examples" / "api"


class CanonicalApiExampleTests(unittest.TestCase):
    def _load_example(self, filename: str) -> dict:
        return json.loads((EXAMPLES_DIR / filename).read_text(encoding="utf-8"))

    def test_generated_examples_parse_through_public_api_parser(self) -> None:
        for filename in (
            "create-task.json",
            "evaluate-happy-path.json",
            "evaluate-mismatch.json",
            "evaluate-review-required.json",
        ):
            request = parse_evaluation_request(self._load_example(filename))
            self.assertIsNotNone(request.task_envelope["id"])

    def test_review_required_example_uses_record_not_found_with_null_workflow(self) -> None:
        payload = self._load_example("evaluate-review-required.json")
        linear_facts = payload["request"]["external_facts"]["linear_facts"]

        self.assertFalse(linear_facts["record_found"])
        self.assertIsNone(linear_facts["workflow"])


if __name__ == "__main__":
    unittest.main()
