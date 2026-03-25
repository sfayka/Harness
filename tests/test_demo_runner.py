from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from modules.demo_runner import (
    CANONICAL_DEMO_SCENARIOS,
    main,
    render_console_timeline,
    render_mermaid_trace,
    run_demo_pack,
)
from modules.simulator import run_scenario


class HarnessDemoRunnerTests(unittest.TestCase):
    def _run_cli(self, *args: str) -> tuple[int, str]:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(list(args))
        return exit_code, stdout.getvalue()

    def test_runs_canonical_demo_pack_and_writes_trace_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            results = run_demo_pack(output_dir=temp_dir)
            output_path = Path(temp_dir)

            self.assertEqual(len(results), len(CANONICAL_DEMO_SCENARIOS))
            self.assertTrue((output_path / "index.json").exists())

            expected_final_states = {
                "successful_completion": "completed",
                "missing_evidence_then_completed": "completed",
                "wrong_target_corrected": "completed",
                "review_required_then_completed": "completed",
                "contradictory_facts_blocked": "blocked",
                "long_running_handoff": "completed",
            }

            for result in results:
                self.assertEqual(result.final_task_status, expected_final_states[result.scenario_name])
                self.assertTrue((output_path / f"{result.scenario_name}.timeline.txt").exists())
                self.assertTrue((output_path / f"{result.scenario_name}.mmd").exists())
                self.assertTrue((output_path / f"{result.scenario_name}.json").exists())

    def test_console_timeline_includes_key_flow_details(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_demo_pack(
                scenario_names=("missing_evidence_then_completed",),
                output_dir=temp_dir,
            )[0]
            timeline = render_console_timeline(result)

        self.assertIn("Task ID:", timeline)
        self.assertIn("verification:", timeline)
        self.assertIn("reconciliation:", timeline)
        self.assertIn("lifecycle:", timeline)
        self.assertIn("new_artifacts=review_note", timeline)
        self.assertIn("Final Task State: completed", timeline)

    def test_mermaid_trace_includes_transitions_and_final_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_demo_pack(
                scenario_names=("contradictory_facts_blocked",),
                output_dir=temp_dir,
            )[0]
            mermaid = render_mermaid_trace(result)

        self.assertIn("sequenceDiagram", mermaid)
        self.assertIn("introduce_contradictory_facts", mermaid)
        self.assertIn("action=transition_applied", mermaid)
        self.assertIn("final task state = blocked", mermaid)

    def test_cli_runs_subset_and_prints_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            exit_code, output = self._run_cli(
                "--output-dir",
                temp_dir,
                "successful_completion",
                "contradictory_facts_blocked",
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("Scenario: successful_completion", output)
        self.assertIn("Scenario: contradictory_facts_blocked", output)
        self.assertIn("Artifacts written to", output)

    def test_cli_can_emit_json_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            exit_code, output = self._run_cli(
                "--output-dir",
                temp_dir,
                "--json",
                "successful_completion",
            )
            payload = json.loads(output)

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload[0]["scenario_name"], "successful_completion")
        self.assertEqual(payload[0]["final_task_status"], "completed")


if __name__ == "__main__":
    unittest.main()
