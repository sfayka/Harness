from __future__ import annotations

import json
import unittest
from pathlib import Path


class DemoProofBundleTests(unittest.TestCase):
    def test_in_review_read_model_fixtures_hide_stale_assignment_and_show_active_review(self) -> None:
        read_model_paths = sorted(Path("docs/demo").glob("**/*read-model-final.json"))
        self.assertTrue(read_model_paths)

        failures: list[str] = []
        for path in read_model_paths:
            payload = json.loads(path.read_text(encoding="utf-8"))
            task = payload.get("task") or {}
            if task.get("current_status") != "in_review":
                continue

            review_status = ((task.get("review_summary") or {}).get("status")) or "none"
            assigned_executor = task.get("assigned_executor")

            if review_status != "requested":
                failures.append(f"{path}: expected review_summary.status=requested, found {review_status!r}")
            if assigned_executor is not None:
                failures.append(f"{path}: expected assigned_executor to be null while review gate is active")

        self.assertFalse(failures, "\n".join(failures))


if __name__ == "__main__":
    unittest.main()
