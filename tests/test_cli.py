from __future__ import annotations

import contextlib
import io
import json
import unittest

from modules.cli import main


class HarnessCliTests(unittest.TestCase):
    def _run_cli(self, *args: str) -> tuple[int, str]:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(list(args))
        return exit_code, stdout.getvalue()

    def test_lists_demo_cases(self) -> None:
        exit_code, output = self._run_cli("list")

        self.assertEqual(exit_code, 0)
        self.assertIn("accepted_completion", output)
        self.assertIn("blocked_reconciliation_mismatch", output)

    def test_runs_accepted_completion_case_with_readable_output(self) -> None:
        exit_code, output = self._run_cli("run", "accepted_completion")

        self.assertEqual(exit_code, 0)
        self.assertIn("case: accepted_completion", output)
        self.assertIn("action: transition_applied", output)
        self.assertIn("task_status: completed", output)

    def test_runs_blocked_case_with_json_output(self) -> None:
        exit_code, output = self._run_cli("run", "blocked_reconciliation_mismatch", "--json")
        payload = json.loads(output)

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["action"], "transition_applied")
        self.assertEqual(payload["target_status"], "blocked")
        self.assertEqual(payload["task_envelope"]["status"], "blocked")

    def test_runs_review_required_case(self) -> None:
        exit_code, output = self._run_cli("run", "review_required")

        self.assertEqual(exit_code, 0)
        self.assertIn("requires_review: True", output)
        self.assertIn("action: review_required", output)
        self.assertIn("task_status: in_review", output)

    def test_runs_invalid_input_case(self) -> None:
        exit_code, output = self._run_cli("run", "invalid_input", "--json")
        payload = json.loads(output)

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["action"], "invalid_input")
        self.assertTrue(payload["invalid_input"])
        self.assertIsNotNone(payload["error"])


if __name__ == "__main__":
    unittest.main()
