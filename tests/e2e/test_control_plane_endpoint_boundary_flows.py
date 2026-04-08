from __future__ import annotations

from copy import deepcopy

from tests.e2e.runtime_harness import RuntimeApiTestCase, RuntimeTaskSnapshot
from tests.e2e.scenario_builders import (
    build_completion_claim_request,
    build_create_task_payload,
    build_evaluate_payload,
    build_happy_path_overlays,
    build_reevaluate_payload,
)


class ControlPlaneEndpointBoundaryFlowTests(RuntimeApiTestCase):
    def _assert_snapshot_preserved(
        self,
        before: RuntimeTaskSnapshot,
        after: RuntimeTaskSnapshot,
    ) -> None:
        self.assertEqual(after.task_fetch_status, before.task_fetch_status)
        self.assertEqual(after.task_fetch_response["task"]["status"], before.task_fetch_response["task"]["status"])
        self.assertEqual(
            after.read_model_response["task"]["current_status"],
            before.read_model_response["task"]["current_status"],
        )
        self.assertEqual(
            after.task_fetch_response["task"]["artifacts"]["items"],
            before.task_fetch_response["task"]["artifacts"]["items"],
        )
        self.assertEqual(
            len(after.history_response["evaluations"]),
            len(before.history_response["evaluations"]),
        )
        self.assertEqual(
            len(after.timeline_response["timeline"]),
            len(before.timeline_response["timeline"]),
        )

    def test_existing_task_evaluate_rejects_top_level_overlays_without_mutating_canonical_task(self) -> None:
        scenario = self.create_task_scenario(
            build_create_task_payload(
                "e2e-control-evaluate-existing-boundary",
                title="Existing tasks must reevaluate rather than re-submit overlays",
            )
        )
        overlays = build_happy_path_overlays()
        payload = build_evaluate_payload(
            scenario.created.task,
            linked_artifacts=overlays["linked_artifacts"],
            completion_evidence=overlays["completion_evidence"],
            external_facts=overlays["external_facts"],
            runtime_facts=overlays["runtime_facts"],
        )
        payload["request"]["assigned_executor"] = {
            "executor_type": "codex",
            "executor_id": "executor-e2e-boundary-1",
            "assignment_reason": "Boundary-flow test payload.",
        }

        status, response = self.post_json("/evaluate", payload)
        after = self.snapshot_task(scenario.task_id)

        self.assertEqual(status, 400)
        self.assertTrue(response["invalid_input"])
        self.assertIn(f"/tasks/{scenario.task_id}/reevaluate", response["error"])
        self.assertEqual(
            {violation["source"] for violation in response["violations"]},
            {
                "request.assigned_executor",
                "request.linked_artifacts",
                "request.completion_evidence",
            },
        )
        self._assert_snapshot_preserved(scenario.created.snapshot, after)

    def test_reevaluate_rejects_code_execution_artifacts_and_preserves_task_truth(self) -> None:
        scenario = self.create_task_scenario(
            build_create_task_payload(
                "e2e-control-reevaluate-execution-boundary",
                title="Reevaluation must not accept code execution artifacts",
            )
        )
        overlays = build_happy_path_overlays()

        rejected = scenario.reevaluate(
            build_reevaluate_payload(
                new_artifacts=overlays["linked_artifacts"],
                completion_evidence=overlays["completion_evidence"],
                external_facts=overlays["external_facts"],
                runtime_facts=overlays["runtime_facts"],
                claimed_completion=True,
                acceptance_criteria_satisfied=True,
            )
        )

        self.assertEqual(rejected.status, 400)
        self.assertTrue(rejected.response["invalid_input"])
        self.assertEqual(
            rejected.response["completion_claim_path"],
            f"/tasks/{scenario.task_id}/completion-claims",
        )
        self.assertTrue(
            any(
                violation["rule"] == "reevaluation_execution_artifact_not_allowed"
                for violation in rejected.response["violations"]
            )
        )
        self._assert_snapshot_preserved(scenario.created.snapshot, rejected.snapshot)

    def test_reevaluate_rejects_submission_style_mutation_fields_without_persisting_changes(self) -> None:
        scenario = self.create_task_scenario(
            build_create_task_payload(
                "e2e-control-reevaluate-mutation-boundary",
                title="Reevaluation must reject submission-style mutation fields",
            )
        )
        overlays = build_happy_path_overlays()

        rejected = scenario.reevaluate(
            {
                "request": {
                    "task_envelope": deepcopy(scenario.created.task),
                    "task_status": "completed",
                    "assigned_executor": {
                        "executor_type": "codex",
                        "executor_id": "executor-e2e-bad-reevaluate-1",
                    },
                    "linked_artifacts": deepcopy(overlays["linked_artifacts"]),
                }
            }
        )

        self.assertEqual(rejected.status, 400)
        self.assertTrue(rejected.response["invalid_input"])
        self.assertIn(f"/tasks/{scenario.task_id}/reevaluate", rejected.response["error"])
        self.assertEqual(
            {violation["source"] for violation in rejected.response["violations"]},
            {
                "request.task_envelope",
                "request.task_status",
                "request.assigned_executor",
                "request.linked_artifacts",
            },
        )
        self._assert_snapshot_preserved(scenario.created.snapshot, rejected.snapshot)

    def test_reevaluate_rejects_pre_satisfied_completion_evidence_without_completion_claim(self) -> None:
        scenario = self.create_task_scenario(
            build_create_task_payload(
                "e2e-control-reevaluate-evidence-boundary",
                title="Reevaluation must not pre-satisfy evidence without a completion claim",
            )
        )
        overlays = build_happy_path_overlays()

        rejected = scenario.reevaluate(
            build_reevaluate_payload(
                completion_evidence=overlays["completion_evidence"],
                external_facts=overlays["external_facts"],
                runtime_facts=overlays["runtime_facts"],
                claimed_completion=False,
                acceptance_criteria_satisfied=False,
            )
        )

        self.assertEqual(rejected.status, 400)
        self.assertTrue(rejected.response["invalid_input"])
        self.assertIn("claimed_completion", rejected.response["error"])
        self._assert_snapshot_preserved(scenario.created.snapshot, rejected.snapshot)

    def test_completion_claim_rejects_submission_style_mutation_fields_without_mutating_task(self) -> None:
        scenario = self.create_task_scenario(
            build_create_task_payload(
                "e2e-control-completion-claim-mutation-boundary",
                title="Completion claims must reject submission-style mutation fields",
            )
        )
        overlays = build_happy_path_overlays()
        payload = build_completion_claim_request(claim_id="claim-boundary-1", attempt_id="attempt-boundary-1")
        payload["request"]["task_envelope"] = deepcopy(scenario.created.task)
        payload["request"]["task_status"] = "completed"
        payload["request"]["assigned_executor"] = {
            "executor_type": "codex",
            "executor_id": "executor-e2e-bad-claim-1",
        }
        payload["request"]["linked_artifacts"] = deepcopy(overlays["linked_artifacts"])

        rejected = scenario.completion_claim(payload)

        self.assertEqual(rejected.status, 400)
        self.assertTrue(rejected.response["invalid_input"])
        self.assertIn(f"/tasks/{scenario.task_id}/completion-claims", rejected.response["error"])
        self.assertEqual(
            {violation["source"] for violation in rejected.response["violations"]},
            {
                "request.task_envelope",
                "request.task_status",
                "request.assigned_executor",
                "request.linked_artifacts",
            },
        )
        self._assert_snapshot_preserved(scenario.created.snapshot, rejected.snapshot)
