from __future__ import annotations

from copy import deepcopy

from tests.e2e.runtime_harness import RuntimeApiTestCase
from tests.e2e.scenario_builders import (
    build_completion_claim_request,
    build_completion_evidence,
    build_create_task_payload,
    build_evaluate_payload,
    build_reevaluate_payload,
    build_review_note_artifact,
)


class ControlPlaneArtifactTrustFlowTests(RuntimeApiTestCase):
    def _assert_untrusted_review_note(self, task: dict, *, artifact_id: str) -> dict:
        stored_artifact = next(
            artifact for artifact in task["artifacts"]["items"] if artifact["id"] == artifact_id
        )
        self.assertEqual(stored_artifact["verification_status"], "unverified")
        self.assertEqual(stored_artifact["metadata"]["submitted_verification_status"], "verified")
        return stored_artifact

    def _assert_deferred_evidence(self, task: dict) -> None:
        evidence = task["artifacts"]["completion_evidence"]
        self.assertEqual(evidence["validated_artifact_ids"], [])
        self.assertEqual(evidence["status"], "deferred")
        self.assertIsNone(evidence["validated_at"])
        self.assertIsNone(evidence["validator"])
        self.assertEqual(evidence["validation_method"], "deferred")

    def _review_note_task_payload(self, task_id: str, *, now: str = "2026-04-07T21:00:00Z") -> dict:
        payload = build_create_task_payload(task_id, now=now)
        payload["request"]["task_envelope"]["acceptance_criteria"] = [
            {
                "id": "ac-1",
                "description": "Completion requires a verified review note artifact.",
                "required": True,
            }
        ]
        payload["request"]["task_envelope"]["artifacts"]["completion_evidence"] = {
            "policy": "required",
            "status": "deferred",
            "required_artifact_types": ["review_note"],
            "validated_artifact_ids": [],
            "validation_method": "deferred",
            "validated_at": None,
            "validator": None,
            "notes": None,
        }
        return payload

    def test_submit_strips_verified_status_from_initial_support_artifact(self) -> None:
        payload = self._review_note_task_payload("e2e-artifact-trust-submit", now="2026-04-07T22:40:00Z")
        review_note = build_review_note_artifact("artifact-submit-review-note-e2e")
        review_note["provenance"] = {
            "source_system": "codex",
            "source_type": "executor_report",
            "source_id": "submit/self-certified-review-note-e2e",
            "captured_by": "harness-api",
        }
        payload["request"]["task_envelope"]["artifacts"]["items"] = [review_note]

        scenario = self.create_task_scenario(payload)

        self._assert_untrusted_review_note(
            scenario.created.task,
            artifact_id="artifact-submit-review-note-e2e",
        )
        self.assertEqual(len(scenario.created.history["evaluations"]), 1)
        self.assertEqual(scenario.created.read_model["task"]["current_status"], "intake_ready")

    def test_evaluate_strips_verified_status_from_initial_support_artifact(self) -> None:
        payload = self._review_note_task_payload("e2e-artifact-trust-evaluate-initial", now="2026-04-07T22:40:00Z")
        review_note = build_review_note_artifact("artifact-evaluate-initial-review-note-e2e")
        review_note["provenance"] = {
            "source_system": "codex",
            "source_type": "executor_report",
            "source_id": "evaluate/self-certified-initial-review-note-e2e",
            "captured_by": "harness-api",
        }
        payload["request"]["task_envelope"]["artifacts"]["items"] = [review_note]

        scenario = self.create_evaluate_scenario({"request": {"task_envelope": payload["request"]["task_envelope"]}})

        self._assert_untrusted_review_note(
            scenario.created.task,
            artifact_id="artifact-evaluate-initial-review-note-e2e",
        )
        self.assertEqual(len(scenario.created.history["evaluations"]), 1)

    def test_evaluate_prunes_self_certified_support_artifact_evidence(self) -> None:
        payload = self._review_note_task_payload("e2e-artifact-trust-evaluate")
        review_note = build_review_note_artifact("artifact-evaluate-review-note-e2e")
        review_note["provenance"] = {
            "source_system": "codex",
            "source_type": "executor_report",
            "source_id": "evaluate/self-certified-review-note-e2e",
            "captured_by": "harness-api",
        }

        scenario = self.create_evaluate_scenario(
            build_evaluate_payload(
                payload["request"]["task_envelope"],
                linked_artifacts=[review_note],
                completion_evidence={
                    "status": "satisfied",
                    "validated_artifact_ids": [review_note["id"]],
                    "validation_method": "manual_review",
                    "validated_at": "2026-04-07T21:05:00Z",
                    "validator": {
                        "source_system": "harness",
                        "source_type": "verification",
                        "source_id": "verification-evaluate-support-e2e",
                        "captured_by": "operator",
                    },
                },
                claimed_completion=True,
                acceptance_criteria_satisfied=True,
            )
        )

        self.assertFalse(scenario.created.response["accepted_completion"])
        self._assert_untrusted_review_note(
            scenario.created.task,
            artifact_id="artifact-evaluate-review-note-e2e",
        )
        self._assert_deferred_evidence(scenario.created.task)
        self.assertNotEqual(scenario.created.task["status"], "completed")

    def test_reevaluate_prunes_self_certified_support_artifact_evidence(self) -> None:
        scenario = self.create_task_scenario(self._review_note_task_payload("e2e-artifact-trust-reevaluate"))
        review_note = build_review_note_artifact("artifact-reevaluate-review-note-e2e")
        review_note["provenance"] = {
            "source_system": "codex",
            "source_type": "executor_report",
            "source_id": "reevaluate/self-certified-review-note-e2e",
            "captured_by": "harness-api",
        }

        reevaluated = scenario.reevaluate(
            build_reevaluate_payload(
                new_artifacts=[review_note],
                completion_evidence={
                    "status": "satisfied",
                    "validated_artifact_ids": [review_note["id"]],
                    "validation_method": "manual_review",
                    "validated_at": "2026-04-07T21:15:00Z",
                    "validator": {
                        "source_system": "harness",
                        "source_type": "verification",
                        "source_id": "verification-reevaluate-support-e2e",
                        "captured_by": "operator",
                    },
                },
                claimed_completion=True,
                acceptance_criteria_satisfied=True,
            )
        )

        self.assertEqual(reevaluated.status, 200)
        self.assertFalse(reevaluated.response["accepted_completion"])
        self._assert_untrusted_review_note(
            reevaluated.task,
            artifact_id="artifact-reevaluate-review-note-e2e",
        )
        self._assert_deferred_evidence(reevaluated.task)
        self.assertEqual(len(reevaluated.history["evaluations"]), 2)

    def test_completion_claim_prunes_self_certified_support_artifact_evidence(self) -> None:
        scenario = self.create_task_scenario(self._review_note_task_payload("e2e-artifact-trust-completion-claim"))
        review_note = build_review_note_artifact("artifact-claim-review-note-e2e")

        claimed = scenario.completion_claim(
            build_completion_claim_request(
                claim_id="claim-support-review-note-e2e",
                attempt_id="attempt-support-review-note-e2e",
                new_artifacts=[review_note],
                completion_evidence={
                    "status": "satisfied",
                    "validated_artifact_ids": [review_note["id"]],
                    "validation_method": "manual_review",
                    "validated_at": "2026-04-07T18:05:00Z",
                    "validator": {
                        "source_system": "harness",
                        "source_type": "verification",
                        "source_id": "verification-claim-support-e2e",
                        "captured_by": "executor",
                    },
                },
                acceptance_criteria_satisfied=True,
                runtime_facts={"executor_reported_success": True, "attempt_count": 1},
            )
        )

        self.assertEqual(claimed.status, 200)
        self.assertFalse(claimed.response["accepted_completion"])
        self._assert_untrusted_review_note(
            claimed.task,
            artifact_id="artifact-claim-review-note-e2e",
        )
        self._assert_deferred_evidence(claimed.task)
        timeline_attempts = [
            event for event in claimed.timeline["timeline"] if event["event_type"] == "execution_attempt_recorded"
        ]
        self.assertTrue(timeline_attempts)

    def test_reevaluate_rejects_pre_satisfied_completion_evidence_without_claimed_completion(self) -> None:
        scenario = self.create_task_scenario(self._review_note_task_payload("e2e-artifact-trust-pre-satisfied"))
        payload = build_reevaluate_payload(
            completion_evidence=build_completion_evidence(
                required_artifact_types=["review_note"],
                validated_artifact_ids=["artifact-reevaluate-review-note-e2e"],
            ),
            claimed_completion=False,
            acceptance_criteria_satisfied=False,
        )

        rejected = scenario.reevaluate(payload)

        self.assertEqual(rejected.status, 400)
        self.assertTrue(rejected.response["invalid_input"])
        self.assertIn("claimed_completion", rejected.response["error"])
        self.assertEqual(len(rejected.history["evaluations"]), 1)
