from __future__ import annotations

from copy import deepcopy

from modules.demo_cases import build_demo_request
from tests.e2e.runtime_harness import RuntimeApiTestCase
from tests.e2e.scenario_builders import build_review_note_artifact, to_jsonable


class ControlPlaneEvidenceProgressionFlowTests(RuntimeApiTestCase):
    def test_blocked_task_completes_when_external_facts_arrive_on_reevaluation(self) -> None:
        initial_request = to_jsonable(build_demo_request("accepted_completion"))
        initial_request["external_facts"] = None
        scenario = self.create_evaluate_scenario({"request": initial_request})

        reevaluated = scenario.reevaluate(
            {
                "request": {
                    "external_facts": deepcopy(
                        to_jsonable(build_demo_request("accepted_completion"))["external_facts"]
                    ),
                    "claimed_completion": True,
                    "acceptance_criteria_satisfied": True,
                    "runtime_facts": deepcopy(initial_request["runtime_facts"]),
                }
            }
        )

        self.assertEqual(scenario.created.status, 200)
        self.assertEqual(scenario.created.task["status"], "blocked")
        self.assertEqual(
            scenario.created.response["enforcement_result"]["verification_result"]["outcome"],
            "blocked_unresolved_conditions",
        )
        self.assertEqual(reevaluated.status, 200)
        self.assertEqual(reevaluated.response["action"], "transition_applied")
        self.assertEqual(reevaluated.task["status"], "completed")
        self.assertEqual(reevaluated.read_model["task"]["current_status"], "completed")
        self.assertEqual(
            reevaluated.task["coordination"]["linear"]["provenance"]["source"],
            "reevaluation_request.external_facts",
        )
        self.assertEqual(len(reevaluated.history["evaluations"]), 2)
        self.assertTrue(
            any(
                event["event_type"] == "status_transition" and event["details"]["to_status"] == "completed"
                for event in reevaluated.timeline["timeline"]
            )
        )

    def test_support_evidence_note_keeps_blocked_task_blocked_until_real_proof_exists(self) -> None:
        initial_request = {"request": to_jsonable(build_demo_request("blocked_insufficient_evidence"))}
        scenario = self.create_evaluate_scenario(initial_request)

        reevaluated = scenario.reevaluate(
            {
                "request": {
                    "new_artifacts": [build_review_note_artifact()],
                    "completion_evidence": {
                        "validated_artifact_ids": [
                            "artifact-pr-1",
                            "artifact-commit-1",
                            "artifact-review-note-1",
                        ]
                    },
                    "external_facts": deepcopy(
                        to_jsonable(build_demo_request("accepted_completion"))["external_facts"]
                    ),
                    "claimed_completion": True,
                    "acceptance_criteria_satisfied": True,
                    "runtime_facts": deepcopy(initial_request["request"]["runtime_facts"]),
                }
            }
        )

        self.assertEqual(scenario.created.status, 200)
        self.assertEqual(scenario.created.task["status"], "blocked")
        self.assertEqual(reevaluated.status, 200)
        self.assertEqual(reevaluated.response["action"], "no_op")
        self.assertEqual(reevaluated.task["status"], "blocked")
        self.assertEqual(reevaluated.read_model["task"]["current_status"], "blocked")
        self.assertEqual(len(reevaluated.history["evaluations"]), 2)
        self.assertEqual(
            reevaluated.task["artifacts"]["completion_evidence"]["validated_artifact_ids"],
            ["artifact-pr-1", "artifact-commit-1"],
        )
        self.assertTrue(
            any(
                artifact["id"] == "artifact-review-note-1" and artifact["type"] == "review_note"
                for artifact in reevaluated.task["artifacts"]["items"]
            )
        )
        self.assertFalse(
            any(
                event["event_type"] == "status_transition" and event["details"]["to_status"] == "completed"
                for event in reevaluated.timeline["timeline"]
            )
        )
