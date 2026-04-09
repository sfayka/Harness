from __future__ import annotations

from copy import deepcopy

from modules.demo_cases import build_demo_request
from tests.e2e.runtime_harness import RuntimeApiTestCase
from tests.e2e.scenario_builders import (
    build_handoff_artifact,
    build_progress_artifact,
    to_jsonable,
)


class ControlPlaneProgressArtifactFlowTests(RuntimeApiTestCase):
    def test_support_artifacts_append_across_reevaluations_without_overwriting_prior_progress(self) -> None:
        initial_payload = {"request": to_jsonable(build_demo_request("blocked_insufficient_evidence"))}
        scenario = self.create_evaluate_scenario(initial_payload)

        self.assertEqual(scenario.created.task["status"], "blocked")
        self.assertEqual(
            scenario.created.task["artifacts"]["completion_evidence"]["validated_artifact_ids"],
            ["artifact-pr-1", "artifact-commit-1"],
        )

        first = scenario.reevaluate(
            {
                "request": {
                    "new_artifacts": [build_progress_artifact()],
                    "external_facts": deepcopy(initial_payload["request"]["external_facts"]),
                    "claimed_completion": True,
                    "acceptance_criteria_satisfied": True,
                    "runtime_facts": deepcopy(initial_payload["request"]["runtime_facts"]),
                }
            }
        )

        self.assertEqual(first.status, 200)
        self.assertEqual(first.task["status"], "blocked")
        self.assertIn(
            "artifact-progress-1",
            [artifact["id"] for artifact in first.task["artifacts"]["items"]],
        )
        self.assertEqual(first.read_model["task"]["evidence_summary"]["artifact_count"], 3)
        self.assertEqual(first.read_model["task"]["evidence_summary"]["artifact_type_counts"]["progress_artifact"], 1)
        self.assertEqual(len(first.history["evaluations"]), 2)

        second = scenario.reevaluate(
            {
                "request": {
                    "new_artifacts": [build_handoff_artifact()],
                    "external_facts": deepcopy(initial_payload["request"]["external_facts"]),
                    "claimed_completion": True,
                    "acceptance_criteria_satisfied": True,
                    "runtime_facts": deepcopy(initial_payload["request"]["runtime_facts"]),
                }
            }
        )

        self.assertEqual(second.status, 200)
        self.assertEqual(second.task["status"], "blocked")
        artifact_ids = [artifact["id"] for artifact in second.task["artifacts"]["items"]]
        self.assertIn("artifact-progress-1", artifact_ids)
        self.assertIn("artifact-handoff-1", artifact_ids)
        self.assertEqual(second.read_model["task"]["evidence_summary"]["artifact_count"], 4)
        self.assertEqual(second.read_model["task"]["evidence_summary"]["artifact_type_counts"]["progress_artifact"], 1)
        self.assertEqual(second.read_model["task"]["evidence_summary"]["artifact_type_counts"]["handoff_artifact"], 1)
        self.assertEqual(
            second.task["artifacts"]["completion_evidence"]["validated_artifact_ids"],
            ["artifact-pr-1", "artifact-commit-1"],
        )
        self.assertEqual(len(second.history["evaluations"]), 3)
        self.assertTrue(
            any(
                event["event_type"] == "evaluation_recorded"
                and event["details"]["evaluation_id"] == second.history["evaluations"][-1]["evaluation_id"]
                for event in second.timeline["timeline"]
            )
        )
