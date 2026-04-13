from __future__ import annotations

import json
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from modules.api import HarnessApiService, run_server
from modules.connectors.openclaw_harness_spike import (
    OpenClawHarnessSpikeClient,
    OpenClawSourceContext,
    OpenClawTaskIntent,
    run_openclaw_review_gate_spike_flow,
)
from modules.connectors.openclaw_supervisor import OpenClawHarnessSupervisor
from modules.demo_cases import build_demo_request
from modules.runtime_scenario_builders import to_jsonable
from modules.store import FileBackedHarnessStore


class OpenClawHarnessSupervisorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.service = HarnessApiService(store=FileBackedHarnessStore(self.temp_dir.name))
        self.server = run_server(
            host="127.0.0.1",
            port=0,
            store_root=self.temp_dir.name,
            service=self.service,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"
        self.client = OpenClawHarnessSpikeClient(self.base_url)

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp_dir.cleanup()

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
    ) -> tuple[int, dict]:
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with urlopen(request) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            try:
                return error.code, json.loads(error.read().decode("utf-8"))
            finally:
                error.close()

    def _context(self) -> OpenClawSourceContext:
        return OpenClawSourceContext(
            conversation_id="conv-supervisor-1",
            message_id="msg-supervisor-1",
            channel="cli",
            workspace_id="workspace-supervisor",
            user_id="operator@example.com",
            agent_id="openclaw-assistant",
        )

    def _intent(self, task_id: str) -> OpenClawTaskIntent:
        return OpenClawTaskIntent(
            task_id=task_id,
            title="OpenClaw supervisor attention test",
            description="Create canonical supervision attention for the OpenClaw loop.",
            acceptance_criteria=(
                "Harness persists the task.",
                "Harness exposes canonical supervision attention for the task.",
            ),
            objective_summary="Exercise canonical attention states through the OpenClaw client boundary.",
            deliverable_type="integration_spike",
            success_signal="The OpenClaw supervisor loop can inspect and react to the task.",
            requested_by="operator@example.com",
        )

    def test_cycle_collects_canonical_context_for_review_and_clarification_attention(self) -> None:
        run_openclaw_review_gate_spike_flow(
            base_url=self.base_url,
            task_id="task-openclaw-supervisor-review-1",
        )
        submit_status, _ = self.client.submit_task(
            intent=self._intent("task-openclaw-supervisor-clarification-1"),
            context=self._context(),
            unresolved_conditions=("Need operator clarification before dispatch can continue.",),
        )
        self.assertEqual(submit_status, 200)

        supervisor = OpenClawHarnessSupervisor(self.base_url)
        cycle = supervisor.run_cycle()
        decisions = {decision.task_id: decision for decision in cycle.decisions}
        actions = {result.task_id: result for result in cycle.action_results}

        self.assertEqual(cycle.queue_status, 200)
        self.assertGreaterEqual(cycle.decision_count, 2)

        review_decision = decisions["task-openclaw-supervisor-review-1"]
        self.assertEqual(review_decision.attention_type, "review_required")
        self.assertEqual(review_decision.suggested_action, "resolve_review_gate")
        self.assertEqual(review_decision.read_model_status, 200)
        self.assertEqual(review_decision.timeline_status, 200)
        self.assertGreaterEqual(review_decision.evaluation_history_count, 2)
        self.assertFalse(review_decision.can_autonomously_dispatch)
        self.assertIsNone(review_decision.proposed_dispatch_payload)
        self.assertEqual(actions[review_decision.task_id].action_status, "manual_review_required")

        clarification_decision = decisions["task-openclaw-supervisor-clarification-1"]
        self.assertEqual(clarification_decision.attention_type, "clarification_required")
        self.assertEqual(clarification_decision.suggested_action, "collect_clarification")
        self.assertEqual(clarification_decision.read_model_status, 200)
        self.assertEqual(clarification_decision.timeline_status, 200)
        self.assertGreaterEqual(clarification_decision.evaluation_history_count, 1)
        self.assertFalse(clarification_decision.can_autonomously_dispatch)
        self.assertIsNone(clarification_decision.proposed_dispatch_payload)
        self.assertEqual(actions[clarification_decision.task_id].action_status, "clarification_required")

    def test_cycle_can_trigger_bounded_redispatch_for_retryable_failure(self) -> None:
        retry_payload = {"request": to_jsonable(build_demo_request("blocked_insufficient_evidence"))}
        retry_payload["request"]["runtime_facts"] = {
            "executor_reported_failure": True,
            "attempt_count": 1,
            "latest_attempt_outcome": "failed",
        }
        create_status, create_payload = self._request_json("POST", "/evaluate", retry_payload)
        self.assertEqual(create_status, 200)
        task_id = create_payload["task_envelope"]["id"]

        supervisor = OpenClawHarnessSupervisor(self.base_url)
        cycle = supervisor.run_cycle(allow_redispatch=True, executor="codex")
        decisions = {decision.task_id: decision for decision in cycle.decisions}
        actions = {result.task_id: result for result in cycle.action_results}

        retry_decision = decisions[task_id]
        self.assertEqual(retry_decision.attention_type, "retryable_failure")
        self.assertEqual(retry_decision.suggested_action, "retry_or_redispatch")
        self.assertTrue(retry_decision.can_autonomously_dispatch)
        self.assertIsNotNone(retry_decision.proposed_dispatch_payload)
        self.assertEqual(
            retry_decision.proposed_dispatch_payload["request"]["dispatch_trigger"],
            "openclaw_supervision_loop",
        )

        retry_action = actions[task_id]
        self.assertEqual(retry_action.action_status, "redispatch_triggered")
        self.assertEqual(retry_action.http_status, 200)
        self.assertIsNotNone(retry_action.action)
        self.assertIn(retry_action.resulting_task_status, {"blocked", "completed", "failed", "in_review"})

    def test_cycle_can_trigger_github_sync_for_sync_required_attention(self) -> None:
        submit_status, submit_payload = self.client.submit_task(
            intent=self._intent("task-openclaw-supervisor-sync-1"),
            context=self._context(),
        )
        self.assertEqual(submit_status, 200)
        task_id = submit_payload["task_envelope"]["id"]

        stored_task = self.service.store.get_task(task_id)
        stored_task["status"] = "assigned"
        stored_task["assigned_executor"] = {
            "executor_type": "codex",
            "executor_id": "executor-openclaw-supervisor-sync-1",
            "assignment_reason": "Exercise supervisor GitHub sync.",
        }
        stored_task["artifacts"]["completion_evidence"]["required_artifact_types"] = ["pull_request", "commit"]
        self.service.store.update_task(stored_task)

        claim_status, claim_payload = self._request_json(
            "POST",
            f"/tasks/{task_id}/completion-claims",
            {
                "request": {
                    "completion_claim": {
                        "claim_id": "claim-openclaw-supervisor-sync-1",
                        "reported_at": "2026-04-13T10:00:00Z",
                        "reported_by": "codex",
                        "reason": "Executor reported completion",
                        "metadata": {"attempt_id": "attempt-openclaw-supervisor-sync-1"},
                    },
                    "execution_attempt": {
                        "attempt_id": "attempt-openclaw-supervisor-sync-1",
                        "recorded_at": "2026-04-13T10:00:05Z",
                        "status": "succeeded",
                        "reported_by": "codex",
                        "artifact_references": [
                            {
                                "reference_id": "attempt-openclaw-supervisor-sync-1:pr",
                                "artifact_type": "pull_request",
                                "location": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/pull/123",
                                "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                                "metadata": {
                                    "repository_host": "github.com",
                                    "repository_owner": "KnoxAnalytics",
                                    "repository_name": "HARNESS-DRYRUN",
                                    "branch_name": "codex/e2e-test",
                                    "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                                    "pull_request_number": 123,
                                    "state": "open",
                                },
                            },
                            {
                                "reference_id": "attempt-openclaw-supervisor-sync-1:commit",
                                "artifact_type": "commit",
                                "location": (
                                    "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/commit/"
                                    "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705"
                                ),
                                "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                                "metadata": {
                                    "repository_host": "github.com",
                                    "repository_owner": "KnoxAnalytics",
                                    "repository_name": "HARNESS-DRYRUN",
                                    "branch_name": "codex/e2e-test",
                                    "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                                },
                            },
                        ],
                        "metadata": {"executor_run_id": "stub-run-sync-1"},
                    },
                    "runtime_facts": {
                        "executor_reported_success": True,
                        "attempt_count": 1,
                    },
                }
            },
        )
        self.assertEqual(claim_status, 200)
        self.assertEqual(claim_payload["action"], "reconciliation_blocked")

        supervisor = OpenClawHarnessSupervisor(self.base_url)
        cycle = supervisor.run_cycle(allow_sync=True)
        decisions = {decision.task_id: decision for decision in cycle.decisions}
        actions = {result.task_id: result for result in cycle.action_results}

        sync_decision = decisions[task_id]
        self.assertEqual(sync_decision.attention_type, "github_sync_required")
        self.assertTrue(sync_decision.can_autonomously_sync)
        self.assertIsNotNone(sync_decision.proposed_sync_payload)
        self.assertEqual(sync_decision.proposed_sync_payload["task_id"], task_id)

        sync_action = actions[task_id]
        self.assertEqual(sync_action.action_status, "github_sync_triggered")
        self.assertEqual(sync_action.http_status, 200)
        self.assertEqual(sync_action.action, "no_op")
        self.assertEqual(sync_action.resulting_task_status, "blocked")

        follow_up_cycle = supervisor.run_cycle()
        follow_up_decisions = {decision.task_id: decision for decision in follow_up_cycle.decisions}
        self.assertNotEqual(
            follow_up_decisions.get(task_id).attention_type if task_id in follow_up_decisions else None,
            "github_sync_required",
        )


if __name__ == "__main__":
    unittest.main()
