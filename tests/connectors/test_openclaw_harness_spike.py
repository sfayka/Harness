from __future__ import annotations

import tempfile
import threading
import unittest

from modules.api import run_server
from modules.connectors.openclaw_harness_spike import (
    OpenClawHarnessSpikeClient,
    OpenClawSourceContext,
    OpenClawTaskIntent,
    build_task_submission_payload,
    run_openclaw_spike_flow,
)


class OpenClawHarnessSpikeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.server = run_server(host="127.0.0.1", port=0, store_root=self.temp_dir.name)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"
        self.client = OpenClawHarnessSpikeClient(self.base_url)

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp_dir.cleanup()

    def _context(self) -> OpenClawSourceContext:
        return OpenClawSourceContext(
            conversation_id="conv-spike-1",
            message_id="msg-spike-1",
            channel="cli",
            workspace_id="workspace-spike",
            user_id="operator@example.com",
            agent_id="openclaw-assistant",
        )

    def _intent(self, task_id: str = "task-openclaw-1") -> OpenClawTaskIntent:
        return OpenClawTaskIntent(
            task_id=task_id,
            title="OpenClaw boundary spike",
            description="Submit a task from an OpenClaw-style client and keep source metadata auditable.",
            acceptance_criteria=(
                "Harness accepts canonical task submission over HTTP.",
                "Harness preserves OpenClaw source metadata for inspection.",
            ),
            objective_summary="Validate the OpenClaw -> Harness API boundary.",
        )

    def test_builder_embeds_openclaw_source_metadata(self) -> None:
        payload = build_task_submission_payload(intent=self._intent(), context=self._context())
        task = payload["request"]["task_envelope"]

        self.assertEqual(task["origin"]["source_system"], "openclaw")
        self.assertEqual(task["origin"]["ingress_name"], "OpenClaw")
        self.assertEqual(task["extensions"]["openclaw"]["conversation_id"], "conv-spike-1")
        self.assertEqual(task["extensions"]["openclaw"]["channel"], "cli")

    def test_client_can_submit_and_inspect_task_through_public_api(self) -> None:
        submit_status, submit_payload = self.client.submit_task(
            intent=self._intent(),
            context=self._context(),
        )
        self.assertEqual(submit_status, 200)
        task_id = submit_payload["task_envelope"]["id"]

        task_status, task_payload = self.client.get_task(task_id)
        read_model_status, read_model_payload = self.client.get_task_read_model(task_id)
        timeline_status, timeline_payload = self.client.get_task_timeline(task_id)
        history_status, history_payload = self.client.get_evaluation_history(task_id)

        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["id"], task_id)
        self.assertEqual(read_model_status, 200)
        self.assertEqual(read_model_payload["task"]["extensions"]["openclaw"]["conversation_id"], "conv-spike-1")
        self.assertEqual(timeline_status, 200)
        self.assertGreaterEqual(timeline_payload["event_count"], 1)
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 1)

    def test_representative_spike_flow_moves_blocked_to_completed(self) -> None:
        result = run_openclaw_spike_flow(base_url=self.base_url, task_id="task-openclaw-flow-1")

        self.assertEqual(result.submission_status, 200)
        self.assertEqual(result.initial_task_status, "blocked")
        self.assertEqual(result.reevaluation_status, 200)
        self.assertEqual(result.final_task_status, "completed")
        self.assertEqual(result.read_model_status, 200)
        self.assertEqual(result.timeline_status, 200)
        self.assertEqual(result.evaluation_history_count, 2)

    def test_duplicate_task_id_behavior_matches_canonical_submission_policy(self) -> None:
        self.client.submit_task(intent=self._intent(task_id="task-openclaw-duplicate-1"), context=self._context())
        duplicate_status, duplicate_payload = self.client.submit_task(
            intent=self._intent(task_id="task-openclaw-duplicate-1"),
            context=self._context(),
        )

        self.assertEqual(duplicate_status, 409)
        self.assertTrue(duplicate_payload["duplicate_task_id"])


if __name__ == "__main__":
    unittest.main()
