from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
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
from modules.supervision import HarnessSupervisionService
from tests.test_api import (
    _registry_with_current_run_pull_request_gateway,
    _registry_with_no_create_pull_request_gateway,
)


class OpenClawHarnessSupervisorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_no_create_pull_request_gateway(),
        )
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
        self.assertFalse(review_decision.can_request_execution_substrate)
        self.assertIsNone(review_decision.proposed_execution_substrate_intent)
        self.assertEqual(actions[review_decision.task_id].action_status, "manual_review_required")

        clarification_decision = decisions["task-openclaw-supervisor-clarification-1"]
        self.assertEqual(clarification_decision.attention_type, "clarification_required")
        self.assertEqual(clarification_decision.suggested_action, "collect_clarification")
        self.assertEqual(clarification_decision.read_model_status, 200)
        self.assertEqual(clarification_decision.timeline_status, 200)
        self.assertGreaterEqual(clarification_decision.evaluation_history_count, 1)
        self.assertFalse(clarification_decision.can_autonomously_dispatch)
        self.assertIsNone(clarification_decision.proposed_dispatch_payload)
        self.assertFalse(clarification_decision.can_request_execution_substrate)
        self.assertIsNone(clarification_decision.proposed_execution_substrate_intent)
        self.assertEqual(actions[clarification_decision.task_id].action_status, "clarification_required")

    def test_cycle_emits_substrate_intent_for_retryable_failure_by_default(self) -> None:
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
        self.assertTrue(retry_decision.can_request_execution_substrate)
        self.assertEqual(
            retry_decision.proposed_execution_substrate_intent["intent_type"],
            "retry_execution",
        )
        self.assertEqual(
            retry_decision.proposed_execution_substrate_intent["events_endpoint"],
            f"/tasks/{task_id}/execution-substrate-events",
        )
        self.assertEqual(
            retry_decision.proposed_execution_substrate_intent["completion_authority"],
            "harness_verification",
        )

        retry_action = actions[task_id]
        self.assertEqual(retry_action.action_status, "execution_substrate_dispatch_intent")
        self.assertIsNone(retry_action.http_status)
        self.assertEqual(retry_action.action, "submit_to_execution_substrate")
        self.assertEqual(retry_action.resulting_task_status, "blocked")

    def test_cycle_emits_substrate_intent_for_stale_active_task_by_default(self) -> None:
        self.service.supervision_service = HarnessSupervisionService(
            store=self.service.store,
            now_provider=lambda: "2026-04-16T12:00:00Z",
        )
        submit_status, submit_payload = self.client.submit_task(
            intent=self._intent("task-openclaw-supervisor-stale-1"),
            context=self._context(),
        )
        self.assertEqual(submit_status, 200)
        task_id = submit_payload["task_envelope"]["id"]

        stored_task = self.service.store.get_task(task_id)
        stored_task["status"] = "assigned"
        stored_task["assigned_executor"] = {
            "executor_type": "codex",
            "executor_id": "executor-openclaw-supervisor-stale-1",
            "assignment_reason": "Exercise supervisor stale-task redispatch.",
        }
        stored_task["timestamps"]["updated_at"] = "2026-04-01T10:03:00Z"
        stored_task["timestamps"]["created_at"] = "2026-04-01T10:03:00Z"
        timeline = stored_task.get("timeline")
        if isinstance(timeline, list):
            for event in timeline:
                if isinstance(event, dict):
                    event["occurred_at"] = "2026-04-01T10:03:00Z"
        self.service.store.update_task(stored_task)
        evaluation_records = self.service.store.list_evaluation_records(task_id)
        for record in evaluation_records:
            evaluation_path = Path(self.temp_dir.name) / "evaluations" / task_id / f"{record.evaluation_id}.json"
            evaluation_payload = json.loads(evaluation_path.read_text(encoding="utf-8"))
            evaluation_payload["recorded_at"] = "2026-04-01T10:03:00Z"
            evaluation_path.write_text(json.dumps(evaluation_payload, indent=2, sort_keys=True), encoding="utf-8")

        supervisor = OpenClawHarnessSupervisor(self.base_url)
        cycle = supervisor.run_cycle(allow_redispatch=True, executor="codex")
        decisions = {decision.task_id: decision for decision in cycle.decisions}
        actions = {result.task_id: result for result in cycle.action_results}

        stale_decision = decisions[task_id]
        self.assertEqual(stale_decision.attention_type, "stale_active_task")
        self.assertEqual(stale_decision.suggested_action, "investigate_staleness")
        self.assertTrue(stale_decision.can_autonomously_dispatch)
        self.assertIsNotNone(stale_decision.proposed_dispatch_payload)
        self.assertEqual(
            stale_decision.proposed_dispatch_payload["request"]["dispatch_trigger"],
            "openclaw_supervision_loop",
        )
        self.assertTrue(stale_decision.can_request_execution_substrate)
        self.assertEqual(
            stale_decision.proposed_execution_substrate_intent["intent_type"],
            "investigate_or_restart_execution",
        )
        self.assertEqual(
            stale_decision.proposed_execution_substrate_intent["completion_authority"],
            "harness_verification",
        )

        stale_action = actions[task_id]
        self.assertEqual(stale_action.action_status, "execution_substrate_dispatch_intent")
        self.assertIsNone(stale_action.http_status)
        self.assertEqual(stale_action.action, "submit_to_execution_substrate")
        self.assertEqual(stale_action.resulting_task_status, "assigned")

    def test_cycle_can_still_use_legacy_direct_dispatch_when_explicitly_enabled(self) -> None:
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
        cycle = supervisor.run_cycle(
            allow_redispatch=True,
            allow_legacy_direct_dispatch=True,
            executor="codex",
        )
        actions = {result.task_id: result for result in cycle.action_results}

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
        stored_task["artifacts"]["completion_evidence"]["status"] = "deferred"
        execution_metadata = stored_task["observability"]["execution_metadata"]
        execution_metadata["advisory_completion_claims"] = [
            {
                "claim_id": "claim-openclaw-supervisor-sync-1",
                "reported_at": "2026-04-13T10:00:00Z",
                "reported_by": "codex",
                "reason": "Executor reported completion pending GitHub reconciliation.",
                "metadata": {"attempt_id": "attempt-openclaw-supervisor-sync-1"},
            }
        ]
        execution_metadata["execution_attempts"] = [
            {
                "attempt_id": "attempt-openclaw-supervisor-sync-1",
                "recorded_at": "2026-04-13T10:00:05Z",
                "status": "succeeded",
                "reported_by": "codex",
                "completion_claim_id": "claim-openclaw-supervisor-sync-1",
                "artifact_references": [
                    {
                        "reference_id": "attempt-openclaw-supervisor-sync-1:pr",
                        "artifact_type": "pull_request",
                        "location": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/pull/2",
                        "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                        "metadata": {
                            "repository_host": "github.com",
                            "repository_owner": "KnoxAnalytics",
                            "repository_name": "HARNESS-DRYRUN",
                            "branch_name": "codex/e2e-test",
                            "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                            "pull_request_number": 2,
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
                "metadata": {
                    "executor_run_id": "stub-run-sync-1",
                    "attempt_validation": {
                        "status": "valid",
                        "validated_at": "2026-04-13T10:00:06Z",
                    },
                },
            }
        ]
        self.service.store.update_task(stored_task)
        reevaluate_status, _ = self._request_json(
            "POST",
            f"/tasks/{task_id}/reevaluate",
            {"request": {"acceptance_criteria_satisfied": True}},
        )
        self.assertEqual(reevaluate_status, 200)

        self.service.reconciliation_registry = _registry_with_current_run_pull_request_gateway()

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
        self.assertEqual(sync_action.action, "transition_applied")
        self.assertEqual(sync_action.resulting_task_status, "completed")

        follow_up_cycle = supervisor.run_cycle()
        follow_up_decisions = {decision.task_id: decision for decision in follow_up_cycle.decisions}
        self.assertNotIn(task_id, follow_up_decisions)


if __name__ == "__main__":
    unittest.main()
