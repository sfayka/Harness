from __future__ import annotations

from copy import deepcopy

from tests.e2e.runtime_harness import RuntimeApiTestCase, RuntimeTaskSnapshot
from tests.e2e.scenario_builders import (
    build_completion_claim_request,
    build_create_task_payload,
    build_expected_code_context,
    build_github_facts,
)
from tests.test_completion_claim_reconciliation import (
    _FakeGitHubGateway,
    _registry_with_gateway,
    _task_envelope,
)


class ControlPlaneCompletionReplayFlowTests(RuntimeApiTestCase):
    def _assert_snapshot_equal(self, before: RuntimeTaskSnapshot, after: RuntimeTaskSnapshot) -> None:
        self.assertEqual(after.task_fetch_status, before.task_fetch_status)
        self.assertEqual(after.task_fetch_response, before.task_fetch_response)
        self.assertEqual(after.read_model_status, before.read_model_status)
        self.assertEqual(after.read_model_response, before.read_model_response)
        self.assertEqual(after.timeline_status, before.timeline_status)
        self.assertEqual(after.timeline_response, before.timeline_response)
        self.assertEqual(after.history_status, before.history_status)
        self.assertEqual(after.history_response, before.history_response)

    def test_replayed_completion_claim_is_idempotent_across_canonical_surfaces(self) -> None:
        gateway = _FakeGitHubGateway()
        self.set_reconciliation_registry(_registry_with_gateway(gateway))
        scenario = self.create_task_scenario(
            build_create_task_payload(
                "e2e-control-completion-replay",
                title="Replay identical completion claims without duplicating canonical truth",
            )
        )
        scenario.mutate_task(lambda _: _.update(_task_envelope(task_id=scenario.task_id)))

        claim_payload = build_completion_claim_request(
            claim_id="claim-replay-1",
            attempt_id="attempt-replay-1",
            external_facts={
                "expected_code_context": build_expected_code_context(),
                "github_facts": build_github_facts(),
            },
        )

        first = scenario.completion_claim(claim_payload)
        second = scenario.completion_claim(deepcopy(claim_payload))

        self.assertEqual(first.status, 200)
        self.assertEqual(second.status, 200)
        self.assertEqual(first.task["status"], "completed")
        self.assertEqual(second.task["status"], "completed")
        self.assertEqual(gateway.create_calls, 1)
        self.assertEqual(gateway.get_pull_request_calls, 1)
        self.assertEqual(
            len([artifact for artifact in second.task["artifacts"]["items"] if artifact["type"] == "pull_request"]),
            1,
        )
        self.assertEqual(len(second.task["observability"]["execution_metadata"]["execution_attempts"]), 1)
        self.assertEqual(len(second.task["observability"]["execution_metadata"]["advisory_completion_claims"]), 1)
        self._assert_snapshot_equal(first.snapshot, second.snapshot)
