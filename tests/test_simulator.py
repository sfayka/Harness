from __future__ import annotations

import contextlib
import io
import json
import tempfile
import threading
import unittest

from modules.api import run_server
from modules.simulator import list_scenarios, main, run_scenario


class HarnessSimulatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.server = run_server(host="127.0.0.1", port=0, store_root=self.temp_dir.name)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp_dir.cleanup()

    def _run_cli(self, *args: str) -> tuple[int, str]:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(list(args))
        return exit_code, stdout.getvalue()

    def test_lists_supported_scenarios(self) -> None:
        scenarios = list_scenarios()

        self.assertIn("successful_completion", scenarios)
        self.assertIn("missing_evidence_then_completed", scenarios)
        self.assertIn("review_required_then_completed", scenarios)
        self.assertIn("contradictory_facts_rollback", scenarios)
        self.assertIn("long_running_handoff", scenarios)

    def test_runs_successful_completion_scenario_end_to_end(self) -> None:
        result = run_scenario("successful_completion", base_url=self.base_url)

        self.assertEqual(result.final_task_status, "completed")
        self.assertEqual(len(result.steps), 1)
        self.assertEqual(result.steps[0].http_status, 200)
        self.assertEqual(result.steps[0].action, "transition_applied")
        self.assertEqual(len(result.evaluation_history), 1)

    def test_runs_missing_evidence_then_completed_scenario(self) -> None:
        result = run_scenario("missing_evidence_then_completed", base_url=self.base_url)

        self.assertEqual(result.final_task_status, "completed")
        self.assertEqual(len(result.steps), 2)
        self.assertEqual(result.steps[0].task_status, "blocked")
        self.assertEqual(result.steps[1].task_status, "completed")
        self.assertEqual(len(result.evaluation_history), 2)

    def test_runs_review_required_then_completed_scenario(self) -> None:
        result = run_scenario("review_required_then_completed", base_url=self.base_url)

        self.assertEqual(result.final_task_status, "completed")
        self.assertEqual(result.steps[0].action, "review_required")
        self.assertEqual(result.steps[0].task_status, "in_review")
        self.assertIn(result.steps[1].action, {"transition_applied", "follow_up_authorized"})
        self.assertEqual(len(result.evaluation_history), 2)

    def test_runs_contradictory_facts_rollback_scenario(self) -> None:
        result = run_scenario("contradictory_facts_rollback", base_url=self.base_url)

        self.assertEqual(result.final_task_status, "completed")
        self.assertEqual(len(result.steps), 3)
        self.assertEqual(result.steps[0].task_status, "completed")
        self.assertEqual(result.steps[1].task_status, "blocked")
        self.assertEqual(result.steps[2].task_status, "completed")

    def test_runs_long_running_handoff_scenario(self) -> None:
        result = run_scenario("long_running_handoff", base_url=self.base_url)

        artifact_types = [artifact["type"] for artifact in result.task_snapshot["artifacts"]["items"]]

        self.assertEqual(result.final_task_status, "completed")
        self.assertEqual(len(result.steps), 4)
        self.assertIn("progress_artifact", artifact_types)
        self.assertIn("handoff_artifact", artifact_types)
        self.assertEqual(len(result.evaluation_history), 4)

    def test_can_run_scenario_with_deterministic_task_identity(self) -> None:
        result = run_scenario(
            "successful_completion",
            base_url=self.base_url,
            task_id_override="demo-successful-completion",
            task_title_override="Demo: Accepted Completion",
            origin_source_id_override="demo-successful-completion",
        )

        self.assertEqual(result.final_task_id, "demo-successful-completion")
        self.assertEqual(result.task_snapshot["title"], "Demo: Accepted Completion")
        self.assertEqual(result.task_snapshot["origin"]["source_id"], "demo-successful-completion")

    def test_cli_lists_scenarios(self) -> None:
        exit_code, output = self._run_cli("list")

        self.assertEqual(exit_code, 0)
        self.assertIn("successful_completion", output)
        self.assertIn("long_running_handoff", output)

    def test_cli_runs_scenario_with_json_output(self) -> None:
        exit_code, output = self._run_cli(
            "--base-url",
            self.base_url,
            "run",
            "missing_evidence_then_completed",
            "--json",
        )
        payload = json.loads(output)

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["scenario_name"], "missing_evidence_then_completed")
        self.assertEqual(payload["final_task_status"], "completed")
        self.assertEqual(len(payload["steps"]), 2)


if __name__ == "__main__":
    unittest.main()
