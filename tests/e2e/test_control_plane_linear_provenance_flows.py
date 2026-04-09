from __future__ import annotations

from copy import deepcopy

from tests.e2e.runtime_harness import RuntimeApiTestCase
from tests.e2e.scenario_builders import (
    build_create_task_payload,
    build_evaluate_payload,
    build_happy_path_overlays,
    build_linear_facts,
    build_review_required_payload,
)


class ControlPlaneLinearProvenanceFlowTests(RuntimeApiTestCase):
    def _assert_task_absent(self, task_id: str) -> None:
        task_status, task_payload = self.get_json(f"/tasks/{task_id}")
        history_status, history_payload = self.get_json(f"/tasks/{task_id}/evaluations")

        self.assertEqual(task_status, 404)
        self.assertIn("not found", task_payload["error"].lower())
        self.assertEqual(history_status, 404)
        self.assertIn("not found", history_payload["error"].lower())

    def test_review_required_linear_facts_with_omitted_workflow_are_accepted(self) -> None:
        payload = build_review_required_payload(
            build_create_task_payload("e2e-linear-review-required")["request"]["task_envelope"]
        )

        scenario = self.create_evaluate_scenario(payload)

        self.assertEqual(scenario.created.response["action"], "review_required")
        self.assertEqual(scenario.created.task["status"], "in_review")
        self.assertFalse(scenario.created.task["coordination"]["linear"]["record_found"])
        self.assertEqual(
            scenario.created.read_model["task"]["coordination_summary"]["linear"]["record_found"],
            False,
        )
        self.assertTrue(
            any(
                event["event_type"] == "linear_linkage_recorded"
                and event["details"]["record_found"] is False
                for event in scenario.created.timeline["timeline"]
            )
        )

    def test_record_found_linear_facts_without_workflow_are_rejected_without_persisting_task(self) -> None:
        task_id = "e2e-linear-invalid-workflow"
        task_envelope = build_create_task_payload(task_id)["request"]["task_envelope"]
        overlays = build_happy_path_overlays()
        external_facts = deepcopy(overlays["external_facts"])
        del external_facts["linear_facts"]["workflow"]

        status, response = self.post_json(
            "/evaluate",
            build_evaluate_payload(
                task_envelope,
                linked_artifacts=overlays["linked_artifacts"],
                completion_evidence=overlays["completion_evidence"],
                external_facts=external_facts,
                runtime_facts=overlays["runtime_facts"],
            ),
        )

        self.assertEqual(status, 400)
        self.assertTrue(response["invalid_input"])
        self.assertIn("Invalid external_facts.linear_facts.workflow", response["error"])
        self._assert_task_absent(task_id)

    def test_external_facts_arrival_updates_linear_provenance_on_reevaluation(self) -> None:
        task_id = "e2e-linear-provenance-arrival"
        initial_payload = build_create_task_payload(task_id)
        overlays = build_happy_path_overlays()
        initial_evaluate_payload = build_evaluate_payload(
            initial_payload["request"]["task_envelope"],
            linked_artifacts=overlays["linked_artifacts"],
            completion_evidence=overlays["completion_evidence"],
            external_facts=None,
            runtime_facts=overlays["runtime_facts"],
            claimed_completion=True,
            acceptance_criteria_satisfied=True,
        )
        scenario = self.create_evaluate_scenario(initial_evaluate_payload)

        self.assertEqual(scenario.created.task["status"], "blocked")
        self.assertIsNone((scenario.created.task.get("coordination") or {}).get("linear"))

        overlays = build_happy_path_overlays()
        reevaluated = scenario.reevaluate(
            {
                "request": {
                    "external_facts": deepcopy(overlays["external_facts"]),
                    "claimed_completion": True,
                    "acceptance_criteria_satisfied": True,
                    "runtime_facts": deepcopy(overlays["runtime_facts"]),
                }
            }
        )

        self.assertEqual(reevaluated.task["status"], "completed")
        self.assertEqual(
            reevaluated.task["coordination"]["linear"]["provenance"]["source"],
            "reevaluation_request.external_facts",
        )
        self.assertEqual(
            reevaluated.read_model["task"]["coordination_summary"]["linear"]["provenance"]["source"],
            "reevaluation_request.external_facts",
        )
        linear_events = [
            event for event in reevaluated.timeline["timeline"] if event["event_type"] == "linear_linkage_recorded"
        ]
        self.assertTrue(linear_events)
        self.assertEqual(
            linear_events[-1]["details"]["provenance"]["source"],
            "reevaluation_request.external_facts",
        )

    def test_linear_coordination_persists_missing_record_then_conflicting_state_across_reevaluations(self) -> None:
        task_id = "e2e-linear-provenance-conflict"
        scenario = self.create_evaluate_scenario(
            build_evaluate_payload(
                build_create_task_payload(task_id)["request"]["task_envelope"],
                linked_artifacts=build_happy_path_overlays()["linked_artifacts"],
                completion_evidence=build_happy_path_overlays()["completion_evidence"],
                external_facts=build_happy_path_overlays()["external_facts"],
                runtime_facts=build_happy_path_overlays()["runtime_facts"],
            )
        )

        missing_record = scenario.reevaluate(
            {
                "request": {
                    "external_facts": {
                        "linear_facts": {
                            "record_found": False,
                            "reasons": ["Linear record was not found during sync."],
                        }
                    },
                    "claimed_completion": True,
                    "acceptance_criteria_satisfied": True,
                    "runtime_facts": deepcopy(build_happy_path_overlays()["runtime_facts"]),
                }
            }
        )

        self.assertFalse(missing_record.task["coordination"]["linear"]["record_found"])
        self.assertEqual(
            missing_record.task["coordination"]["linear"]["provenance"]["source"],
            "reevaluation_request.external_facts",
        )
        self.assertEqual(
            missing_record.read_model["task"]["coordination_summary"]["linear"]["record_found"],
            False,
        )

        conflicting_linear_facts = build_linear_facts(
            record_found=True,
            state="in_progress",
            workflow_name="In Progress",
            workflow_state_type="started",
            reasons=["Linear state lags behind GitHub completion evidence."],
        )
        stale_record = scenario.reevaluate(
            {
                "request": {
                    "external_facts": {"linear_facts": conflicting_linear_facts},
                    "claimed_completion": True,
                    "acceptance_criteria_satisfied": True,
                    "runtime_facts": deepcopy(build_happy_path_overlays()["runtime_facts"]),
                }
            }
        )

        self.assertEqual(stale_record.task["coordination"]["linear"]["state"], "in_progress")
        self.assertTrue(stale_record.task["coordination"]["linear"]["record_found"])
        self.assertEqual(
            stale_record.task["coordination"]["linear"]["provenance"]["source"],
            "reevaluation_request.external_facts",
        )
        self.assertEqual(
            stale_record.read_model["task"]["coordination_summary"]["linear"]["state"],
            "in_progress",
        )
        linear_events = [
            event for event in stale_record.timeline["timeline"] if event["event_type"] == "linear_linkage_recorded"
        ]
        self.assertTrue(linear_events)
        self.assertEqual(linear_events[-1]["details"]["state"], "in_progress")
        self.assertEqual(len(stale_record.history["evaluations"]), 3)
