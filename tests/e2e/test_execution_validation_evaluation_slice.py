from __future__ import annotations

from copy import deepcopy

from modules.adapters import ExecutorDispatchInput, StubExecutorAdapter
from tests.e2e.runtime_harness import RuntimeApiTestCase
from tests.e2e.scenario_builders import (
    build_completion_evidence,
    build_create_task_payload,
    build_happy_path_overlays,
)


class ExecutionValidationEvaluationSliceTests(RuntimeApiTestCase):
    def _dispatch_stub_completion_claim(self, task: dict, *, attempt_id: str) -> dict:
        dispatch_input = ExecutorDispatchInput.from_task_envelope(
            task,
            attempt_id=attempt_id,
            assigned_executor="stub-executor",
        )
        dispatch_output = StubExecutorAdapter(now_provider=lambda: "2026-04-02T00:00:00Z").dispatch(dispatch_input)
        completion_event = dispatch_output.events[-1]
        completion_claim = completion_event.advisory_completion
        assert completion_claim is not None

        return {
            "completion_claim": {
                "claim_id": completion_claim.claim_id,
                "reported_at": completion_event.occurred_at,
                "reported_by": "stub-executor",
                "reason": completion_claim.reason,
                "metadata": deepcopy(completion_claim.metadata),
            },
            "runtime_facts": {
                "executor_reported_success": True,
                "attempt_count": 1,
            },
            "acceptance_criteria_satisfied": True,
        }

    def test_valid_artifacts_accept_completion_and_are_auditable(self) -> None:
        create_payload = build_create_task_payload("e2e-execution-slice-valid")
        create_status, create_response = self.post_json("/tasks", create_payload)
        task_id = create_response["task_envelope"]["id"]

        fetch_status, fetch_response = self.get_json(f"/tasks/{task_id}")
        claim_request = self._dispatch_stub_completion_claim(fetch_response["task"], attempt_id="attempt-valid-1")
        overlays = build_happy_path_overlays()
        claim_request["new_artifacts"] = overlays["linked_artifacts"]
        claim_request["completion_evidence"] = overlays["completion_evidence"]
        claim_request["external_facts"] = overlays["external_facts"]

        claim_status, claim_response = self.post_json(
            f"/tasks/{task_id}/completion-claims",
            {"request": claim_request},
        )
        read_model_status, read_model_response = self.get_json(f"/tasks/{task_id}/read-model")
        timeline_status, timeline_response = self.get_json(f"/tasks/{task_id}/timeline")

        self.assertEqual(create_status, 200)
        self.assertEqual(fetch_status, 200)
        self.assertEqual(claim_status, 200)
        self.assertTrue(claim_response["accepted_completion"])
        self.assertEqual(claim_response["task_envelope"]["status"], "completed")

        self.assertEqual(read_model_status, 200)
        self.assertEqual(read_model_response["task"]["current_status"], "completed")
        self.assertIn(
            "Executor-reported success was treated as advisory input only",
            read_model_response["task"]["verification_summary"]["reasons"],
        )

        self.assertEqual(timeline_status, 200)
        event_types = {event["event_type"] for event in timeline_response["timeline"]}
        self.assertIn("artifact_captured", event_types)
        self.assertIn("evaluation_recorded", event_types)

    def test_advisory_claim_without_artifacts_does_not_complete_task(self) -> None:
        create_payload = build_create_task_payload("e2e-execution-slice-claim-only")
        create_status, create_response = self.post_json("/tasks", create_payload)
        task_id = create_response["task_envelope"]["id"]
        _, fetch_response = self.get_json(f"/tasks/{task_id}")

        claim_request = self._dispatch_stub_completion_claim(fetch_response["task"], attempt_id="attempt-claim-only")
        claim_status, claim_response = self.post_json(
            f"/tasks/{task_id}/completion-claims",
            {"request": claim_request},
        )
        final_status, final_response = self.get_json(f"/tasks/{task_id}")

        self.assertEqual(create_status, 200)
        self.assertEqual(claim_status, 200)
        self.assertFalse(claim_response["accepted_completion"])
        self.assertEqual(final_status, 200)
        self.assertNotEqual(final_response["task"]["status"], "completed")

    def test_missing_required_artifact_blocks_completion_claim(self) -> None:
        create_payload = build_create_task_payload("e2e-execution-slice-missing-artifact")
        create_status, create_response = self.post_json("/tasks", create_payload)
        task_id = create_response["task_envelope"]["id"]
        _, fetch_response = self.get_json(f"/tasks/{task_id}")

        overlays = build_happy_path_overlays()
        claim_request = self._dispatch_stub_completion_claim(fetch_response["task"], attempt_id="attempt-missing-1")
        claim_request["new_artifacts"] = overlays["linked_artifacts"][:1]
        claim_request["completion_evidence"] = build_completion_evidence(
            required_artifact_types=["pull_request", "commit"],
            validated_artifact_ids=["artifact-pr-1"],
        )
        claim_request["external_facts"] = overlays["external_facts"]

        claim_status, claim_response = self.post_json(
            f"/tasks/{task_id}/completion-claims",
            {"request": claim_request},
        )
        final_status, final_response = self.get_json(f"/tasks/{task_id}")

        verification = claim_response["enforcement_result"]["verification_result"]

        self.assertEqual(create_status, 200)
        self.assertEqual(claim_status, 200)
        self.assertFalse(claim_response["accepted_completion"])
        self.assertEqual(verification["outcome"], "insufficient_evidence")
        self.assertIn(
            "Completion evidence is missing required artifact types: commit",
            verification["reasons"],
        )
        self.assertEqual(final_status, 200)
        self.assertEqual(final_response["task"]["status"], "blocked")
