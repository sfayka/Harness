from __future__ import annotations

from copy import deepcopy

from tests.e2e.runtime_harness import RuntimeApiTestCase
from tests.e2e.scenario_builders import (
    build_completion_evidence,
    build_create_task_payload,
    build_evaluate_payload,
    build_github_facts,
    build_happy_path_overlays,
    build_linked_artifacts,
    build_linear_facts,
    build_mismatch_overlays,
    build_reevaluate_payload,
    build_review_decision,
    build_review_required_overlays,
    build_review_required_payload,
    build_top_level_overlay_happy_path_payload,
    build_expected_code_context,
)


class TaskEvaluationRuntimeScenarioTests(RuntimeApiTestCase):
    def test_happy_path_create_fetch_evaluate_fetch_final(self) -> None:
        create_payload = build_create_task_payload("e2e-happy-path")
        flow = self.run_create_fetch_evaluate_fetch(
            create_payload=create_payload,
            evaluate_payload_builder=build_top_level_overlay_happy_path_payload,
        )

        verification = flow.evaluate_response["enforcement_result"]["verification_result"]

        self.assertEqual(flow.create_status, 200)
        self.assertEqual(flow.initial_fetch_status, 200)
        self.assertEqual(flow.evaluate_status, 200)
        self.assertEqual(flow.final_fetch_status, 200)
        self.assertTrue(flow.evaluate_response["accepted_completion"])
        self.assertEqual(verification["outcome"], "accepted_completion")
        self.assertEqual(flow.final_fetch_response["task"]["status"], "completed")

    def test_mismatch_create_fetch_evaluate_fetch_final(self) -> None:
        create_payload = build_create_task_payload("e2e-mismatch")

        def build_payload(task: dict) -> dict:
            overlays = build_mismatch_overlays()
            return build_evaluate_payload(
                task,
                linked_artifacts=overlays["linked_artifacts"],
                completion_evidence=overlays["completion_evidence"],
                external_facts=overlays["external_facts"],
                runtime_facts=overlays["runtime_facts"],
            )

        flow = self.run_create_fetch_evaluate_fetch(
            create_payload=create_payload,
            evaluate_payload_builder=build_payload,
        )

        verification = flow.evaluate_response["enforcement_result"]["verification_result"]
        reconciliation = flow.evaluate_response["enforcement_result"]["reconciliation_result"]

        self.assertEqual(flow.evaluate_status, 200)
        self.assertFalse(flow.evaluate_response["accepted_completion"])
        self.assertEqual(reconciliation["status"], "mismatch")
        self.assertEqual(verification["outcome"], "terminal_invalid")
        self.assertEqual(flow.final_fetch_response["task"]["status"], "failed")

    def test_review_required_create_fetch_evaluate_fetch_final(self) -> None:
        create_payload = build_create_task_payload("e2e-review-required")
        flow = self.run_create_fetch_evaluate_fetch(
            create_payload=create_payload,
            evaluate_payload_builder=build_review_required_payload,
        )

        verification = flow.evaluate_response["enforcement_result"]["verification_result"]

        self.assertEqual(flow.evaluate_status, 200)
        self.assertFalse(flow.evaluate_response["accepted_completion"])
        self.assertTrue(flow.evaluate_response["requires_review"])
        self.assertEqual(verification["outcome"], "review_required")
        self.assertEqual(flow.final_fetch_response["task"]["status"], "in_review")

    def test_existing_stored_task_evaluate_rejects_top_level_overlays(self) -> None:
        create_payload = build_create_task_payload("e2e-existing-overlays")
        create_status, create_response = self.post_json("/tasks", create_payload)
        task_id = create_response["task_envelope"]["id"]
        initial_fetch_status, initial_fetch_response = self.get_json(f"/tasks/{task_id}")

        evaluate_status, evaluate_response = self.post_json(
            "/evaluate",
            build_top_level_overlay_happy_path_payload(initial_fetch_response["task"]),
        )
        final_fetch_status, final_fetch_response = self.get_json(f"/tasks/{task_id}")

        self.assertEqual(create_status, 200)
        self.assertEqual(initial_fetch_status, 200)
        self.assertEqual(initial_fetch_response["task"]["status"], "intake_ready")
        self.assertEqual(evaluate_status, 400)
        self.assertTrue(evaluate_response["invalid_input"])
        self.assertEqual(evaluate_response["reevaluate_path"], f"/tasks/{task_id}/reevaluate")
        violation_sources = {violation["source"] for violation in evaluate_response["violations"]}
        self.assertEqual(
            violation_sources,
            {
                "request.linked_artifacts",
                "request.completion_evidence",
            },
        )
        self.assertEqual(final_fetch_status, 200)
        self.assertEqual(final_fetch_response["task"]["status"], "intake_ready")

    def test_reevaluate_fresh_stored_task_later_accumulates_sufficient_evidence(self) -> None:
        create_payload = build_create_task_payload("e2e-reevaluate-happy")
        happy_overlays = build_happy_path_overlays()
        flow = self.run_create_fetch_reevaluate_fetch(
            create_payload=create_payload,
            reevaluate_payload_builder=lambda _task: build_reevaluate_payload(
                new_artifacts=happy_overlays["linked_artifacts"],
                completion_evidence=happy_overlays["completion_evidence"],
                external_facts=happy_overlays["external_facts"],
                runtime_facts=happy_overlays["runtime_facts"],
            ),
        )

        self.assertEqual(flow.initial_fetch_response["task"]["status"], "intake_ready")
        self.assertEqual(flow.reevaluate_status, 200)
        self.assertTrue(flow.reevaluate_response["accepted_completion"])
        self.assertEqual(flow.final_fetch_response["task"]["status"], "completed")

    def test_reevaluate_normalizes_github_and_linear_vendor_shaped_facts(self) -> None:
        create_payload = build_create_task_payload("e2e-reevaluate-normalized-facts")
        happy_overlays = build_happy_path_overlays()
        flow = self.run_create_fetch_reevaluate_fetch(
            create_payload=create_payload,
            reevaluate_payload_builder=lambda _task: build_reevaluate_payload(
                new_artifacts=happy_overlays["linked_artifacts"],
                completion_evidence=happy_overlays["completion_evidence"],
                external_facts={
                    "expected_code_context": build_expected_code_context(),
                    "github_facts": {
                        "repository": {"full_name": "KnoxAnalytics/HARNESS-DRYRUN"},
                        "branch": {"ref": "codex/e2e-test", "baseRefName": "main"},
                        "commit": {"sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705"},
                        "pull_request": {"number": 2, "reviewDecision": "approved"},
                    },
                    "linear_facts": {
                        "issue": {"id": "lin_42", "identifier": "HAR-42"},
                        "state": {"id": "workflow_done", "name": "completed", "type": "completed"},
                    },
                },
                runtime_facts=happy_overlays["runtime_facts"],
            ),
        )

        self.assertEqual(flow.reevaluate_status, 200)
        self.assertTrue(flow.reevaluate_response["accepted_completion"])
        self.assertEqual(flow.final_fetch_response["task"]["status"], "completed")

    def test_valid_but_insufficient_evidence_emits_concrete_reason(self) -> None:
        create_payload = build_create_task_payload("e2e-insufficient-valid")

        def build_payload(task: dict) -> dict:
            overlays = build_happy_path_overlays()
            completion_evidence = build_completion_evidence(
                required_artifact_types=["pull_request", "commit", "review_note"],
            )
            return build_evaluate_payload(
                task,
                linked_artifacts=overlays["linked_artifacts"],
                completion_evidence=completion_evidence,
                external_facts=overlays["external_facts"],
                runtime_facts=overlays["runtime_facts"],
            )

        flow = self.run_create_fetch_evaluate_fetch(
            create_payload=create_payload,
            evaluate_payload_builder=build_payload,
        )

        verification = flow.evaluate_response["enforcement_result"]["verification_result"]
        reasons = tuple(verification["reasons"])
        evidence = flow.evaluate_response["enforcement_result"]["evidence_result"]

        self.assertEqual(verification["outcome"], "insufficient_evidence")
        self.assertIn("Completion evidence is missing required artifact types: review_note", reasons)
        self.assertEqual(evidence["missing_required_artifact_types"], ["review_note"])
        self.assertEqual(flow.final_fetch_response["task"]["status"], "blocked")

    def test_required_artifact_types_missing_are_reported(self) -> None:
        create_payload = build_create_task_payload("e2e-missing-required-types")

        def build_payload(task: dict) -> dict:
            overlays = build_happy_path_overlays()
            completion_evidence = build_completion_evidence(
                required_artifact_types=["pull_request", "commit", "review_note"],
            )
            return build_evaluate_payload(
                task,
                linked_artifacts=overlays["linked_artifacts"],
                completion_evidence=completion_evidence,
                external_facts=overlays["external_facts"],
                runtime_facts=overlays["runtime_facts"],
            )

        flow = self.run_create_fetch_evaluate_fetch(
            create_payload=create_payload,
            evaluate_payload_builder=build_payload,
        )
        evidence = flow.evaluate_response["enforcement_result"]["evidence_result"]

        self.assertEqual(evidence["missing_required_artifact_types"], ["review_note"])

    def test_validated_artifact_ids_must_match_linked_artifacts(self) -> None:
        create_payload = build_create_task_payload("e2e-unknown-validated-id")

        def build_payload(task: dict) -> dict:
            overlays = build_happy_path_overlays()
            completion_evidence = build_completion_evidence(
                validated_artifact_ids=["artifact-pr-1", "artifact-missing-99"],
            )
            return build_evaluate_payload(
                task,
                linked_artifacts=overlays["linked_artifacts"],
                completion_evidence=completion_evidence,
                external_facts=overlays["external_facts"],
                runtime_facts=overlays["runtime_facts"],
            )

        flow = self.run_create_fetch_evaluate_fetch(
            create_payload=create_payload,
            evaluate_payload_builder=build_payload,
        )

        self.assertEqual(flow.evaluate_status, 400)
        self.assertTrue(flow.evaluate_response["invalid_input"])
        self.assertEqual(flow.evaluate_response["error"], "Task evidence is structurally invalid")
        self.assertEqual(flow.final_fetch_response["task"]["status"], "intake_ready")

    def test_satisfied_completion_evidence_without_linked_artifacts_is_invalid(self) -> None:
        create_payload = build_create_task_payload("e2e-satisfied-without-artifacts")

        def build_payload(task: dict) -> dict:
            overlays = build_happy_path_overlays()
            return build_evaluate_payload(
                task,
                linked_artifacts=[],
                completion_evidence=overlays["completion_evidence"],
                external_facts=overlays["external_facts"],
                runtime_facts=overlays["runtime_facts"],
            )

        flow = self.run_create_fetch_evaluate_fetch(
            create_payload=create_payload,
            evaluate_payload_builder=build_payload,
        )

        self.assertEqual(flow.evaluate_status, 400)
        self.assertTrue(flow.evaluate_response["invalid_input"])
        self.assertEqual(flow.final_fetch_response["task"]["status"], "intake_ready")

    def test_top_level_overlays_win_when_nested_task_evidence_is_deferred(self) -> None:
        create_payload = build_create_task_payload("e2e-overlay-wins")
        flow = self.run_create_fetch_evaluate_fetch(
            create_payload=create_payload,
            evaluate_payload_builder=build_top_level_overlay_happy_path_payload,
        )

        verification = flow.evaluate_response["enforcement_result"]["verification_result"]
        self.assertEqual(
            flow.evaluate_payload["request"]["task_envelope"]["artifacts"]["completion_evidence"]["status"],
            "deferred",
        )
        self.assertTrue(verification["evidence_is_sufficient"])
        self.assertEqual(flow.final_fetch_response["task"]["status"], "completed")

    def test_intake_ready_can_complete_via_verification_driven_acceptance(self) -> None:
        create_payload = build_create_task_payload("e2e-intake-ready-completion")
        flow = self.run_create_fetch_evaluate_fetch(
            create_payload=create_payload,
            evaluate_payload_builder=build_top_level_overlay_happy_path_payload,
        )

        self.assertEqual(flow.initial_fetch_response["task"]["status"], "intake_ready")
        self.assertEqual(flow.final_fetch_response["task"]["status"], "completed")

    def test_intake_ready_can_enter_in_review_via_review_required_evaluation(self) -> None:
        create_payload = build_create_task_payload("e2e-intake-ready-review")
        flow = self.run_create_fetch_evaluate_fetch(
            create_payload=create_payload,
            evaluate_payload_builder=build_review_required_payload,
        )

        self.assertEqual(flow.initial_fetch_response["task"]["status"], "intake_ready")
        self.assertEqual(flow.evaluate_response["action"], "review_required")
        self.assertEqual(flow.final_fetch_response["task"]["status"], "in_review")

    def test_review_gate_is_sticky_for_automatic_reevaluation(self) -> None:
        create_payload = build_create_task_payload("e2e-sticky-review")
        initial = self.run_create_fetch_evaluate_fetch(
            create_payload=create_payload,
            evaluate_payload_builder=build_review_required_payload,
        )
        task_id = initial.task_id
        happy_overlays = build_happy_path_overlays()

        reevaluate_status, reevaluate_response = self.post_json(
            f"/tasks/{task_id}/reevaluate",
            build_reevaluate_payload(
                external_facts=happy_overlays["external_facts"],
                runtime_facts=happy_overlays["runtime_facts"],
            ),
        )
        final_fetch_status, final_fetch_response = self.get_json(f"/tasks/{task_id}")

        self.assertEqual(reevaluate_status, 200)
        self.assertEqual(reevaluate_response["action"], "review_required")
        self.assertEqual(reevaluate_response["task_envelope"]["status"], "in_review")
        self.assertEqual(final_fetch_status, 200)
        self.assertEqual(final_fetch_response["task"]["status"], "in_review")

    def test_completed_task_is_not_auto_reopened_into_review(self) -> None:
        create_payload = build_create_task_payload("e2e-completed-not-reopened")
        happy = self.run_create_fetch_evaluate_fetch(
            create_payload=create_payload,
            evaluate_payload_builder=build_top_level_overlay_happy_path_payload,
        )
        review_overlays = build_review_required_overlays(happy.task_id)

        status, response = self.post_json(
            f"/tasks/{happy.task_id}/reevaluate",
            build_reevaluate_payload(
                external_facts=review_overlays["external_facts"],
                runtime_facts=review_overlays["runtime_facts"],
                review_request=review_overlays["review_request"],
            ),
        )
        final_fetch_status, final_fetch_response = self.get_json(f"/tasks/{happy.task_id}")

        self.assertEqual(status, 200)
        self.assertEqual(response["action"], "transition_rejected")
        self.assertEqual(response["error"], "Forbidden lifecycle transition completed -> in_review")
        self.assertEqual(final_fetch_status, 200)
        self.assertEqual(final_fetch_response["task"]["status"], "completed")

    def test_failed_and_canceled_tasks_do_not_auto_complete(self) -> None:
        for terminal_status in ("failed", "canceled"):
            with self.subTest(terminal_status=terminal_status):
                initial_payload = build_create_task_payload(f"e2e-terminal-{terminal_status}")
                initial_payload["request"]["task_envelope"]["status"] = terminal_status
                initial_payload["request"]["task_envelope"]["timestamps"]["completed_at"] = "2026-04-01T10:05:00Z"
                initial_status, initial_response = self.post_json("/evaluate", initial_payload)
                task_id = initial_response["task_envelope"]["id"]

                evaluate_status, evaluate_response = self.post_json(
                    f"/tasks/{task_id}/reevaluate",
                    self._canonicalize_existing_task_update_payload(
                        build_top_level_overlay_happy_path_payload(initial_response["task_envelope"])
                    ),
                )
                final_fetch_status, final_fetch_response = self.get_json(f"/tasks/{task_id}")

                self.assertEqual(initial_status, 200)
                self.assertEqual(evaluate_status, 200)
                self.assertEqual(evaluate_response["action"], "transition_rejected")
                self.assertEqual(
                    evaluate_response["error"],
                    f"Forbidden lifecycle transition {terminal_status} -> completed",
                )
                self.assertEqual(final_fetch_status, 200)
                self.assertEqual(final_fetch_response["task"]["status"], terminal_status)

    def test_github_aligned_linear_missing_is_review_required(self) -> None:
        create_payload = build_create_task_payload("e2e-linear-missing")
        flow = self.run_create_fetch_evaluate_fetch(
            create_payload=create_payload,
            evaluate_payload_builder=build_review_required_payload,
        )
        reconciliation = flow.evaluate_response["enforcement_result"]["reconciliation_result"]

        self.assertEqual(reconciliation["status"], "review_required")
        self.assertIn("linear_record_not_found", reconciliation["mismatch_categories"])
        self.assertEqual(flow.final_fetch_response["task"]["status"], "in_review")

    def test_wrong_repository_becomes_terminal_mismatch_and_fails(self) -> None:
        create_payload = build_create_task_payload("e2e-wrong-repository")

        def build_payload(task: dict) -> dict:
            overlays = build_mismatch_overlays()
            return build_evaluate_payload(
                task,
                linked_artifacts=overlays["linked_artifacts"],
                completion_evidence=overlays["completion_evidence"],
                external_facts=overlays["external_facts"],
                runtime_facts=overlays["runtime_facts"],
            )

        flow = self.run_create_fetch_evaluate_fetch(
            create_payload=create_payload,
            evaluate_payload_builder=build_payload,
        )
        reconciliation = flow.evaluate_response["enforcement_result"]["reconciliation_result"]

        self.assertEqual(reconciliation["outcome"], "wrong_target")
        self.assertEqual(flow.final_fetch_response["task"]["status"], "failed")

    def test_linear_completed_during_claimed_completion_does_not_mismatch(self) -> None:
        create_payload = build_create_task_payload("e2e-linear-completed-claim")

        def build_payload(task: dict) -> dict:
            overlays = build_happy_path_overlays(linear_state="completed")
            return build_evaluate_payload(
                task,
                linked_artifacts=overlays["linked_artifacts"],
                completion_evidence=overlays["completion_evidence"],
                external_facts=overlays["external_facts"],
                runtime_facts=overlays["runtime_facts"],
            )

        flow = self.run_create_fetch_evaluate_fetch(
            create_payload=create_payload,
            evaluate_payload_builder=build_payload,
        )
        reconciliation = flow.evaluate_response["enforcement_result"]["reconciliation_result"]

        self.assertEqual(reconciliation["status"], "passed")
        self.assertEqual(flow.final_fetch_response["task"]["status"], "completed")

    def test_unresolved_external_truth_does_not_silently_pass(self) -> None:
        create_payload = build_create_task_payload("e2e-unresolved-truth")

        def build_payload(task: dict) -> dict:
            overlays = build_happy_path_overlays()
            return build_evaluate_payload(
                task,
                linked_artifacts=overlays["linked_artifacts"],
                completion_evidence=overlays["completion_evidence"],
                external_facts=None,
                runtime_facts=overlays["runtime_facts"],
            )

        flow = self.run_create_fetch_evaluate_fetch(
            create_payload=create_payload,
            evaluate_payload_builder=build_payload,
        )
        verification = flow.evaluate_response["enforcement_result"]["verification_result"]

        self.assertEqual(verification["outcome"], "blocked_unresolved_conditions")
        self.assertIn("Reconciliation is still pending", verification["reasons"])
        self.assertEqual(flow.final_fetch_response["task"]["status"], "blocked")

    def test_lifecycle_transition_rejection_is_assertable_and_explicit(self) -> None:
        create_payload = build_create_task_payload("e2e-lifecycle-rejection")
        create_payload["request"]["task_envelope"]["status"] = "completed"
        create_payload["request"]["task_envelope"]["timestamps"]["completed_at"] = "2026-04-01T10:05:00Z"
        create_status, create_response = self.post_json("/evaluate", create_payload)
        task_id = create_response["task_envelope"]["id"]

        evaluate_status, evaluate_response = self.post_json(
            f"/tasks/{task_id}/reevaluate",
            self._canonicalize_existing_task_update_payload(
                build_review_required_payload(create_response["task_envelope"])
            ),
        )
        final_fetch_status, final_fetch_response = self.get_json(f"/tasks/{task_id}")

        self.assertEqual(create_status, 200)
        self.assertEqual(evaluate_status, 200)
        self.assertEqual(evaluate_response["action"], "transition_rejected")
        self.assertEqual(evaluate_response["error"], "Forbidden lifecycle transition completed -> in_review")
        self.assertEqual(final_fetch_status, 200)
        self.assertEqual(final_fetch_response["task"]["status"], "completed")

    def test_contract_validation_failures_return_structured_errors(self) -> None:
        create_payload = build_create_task_payload("e2e-contract-error")
        task_id = create_payload["request"]["task_envelope"]["id"]
        create_status, _ = self.post_json("/tasks", create_payload)
        fetch_status, fetch_response = self.get_json(f"/tasks/{task_id}")

        payload = build_top_level_overlay_happy_path_payload(fetch_response["task"])
        payload["request"]["external_facts"]["linear_facts"]["workflow"] = {"workflow_id": "workflow-incomplete"}

        evaluate_status, evaluate_response = self.post_json(
            f"/tasks/{task_id}/reevaluate",
            self._canonicalize_existing_task_update_payload(payload),
        )

        self.assertEqual(create_status, 200)
        self.assertEqual(fetch_status, 200)
        self.assertEqual(evaluate_status, 400)
        self.assertTrue(evaluate_response["invalid_input"])
        self.assertEqual(
            evaluate_response["error"],
            "Invalid external_facts.linear_facts.workflow: must be null/omitted when record_found=false, or an object with workflow_id and workflow_name when record_found=true",
        )

    def test_manual_review_decision_resolves_in_review_task(self) -> None:
        create_payload = build_create_task_payload("e2e-review-resolution")
        initial = self.run_create_fetch_evaluate_fetch(
            create_payload=create_payload,
            evaluate_payload_builder=build_review_required_payload,
        )
        task_id = initial.task_id

        status, response = self.post_json(
            f"/tasks/{task_id}/reevaluate",
            build_reevaluate_payload(review_decision=build_review_decision(task_id)),
        )
        final_fetch_status, final_fetch_response = self.get_json(f"/tasks/{task_id}")

        self.assertEqual(status, 200)
        self.assertIn(response["action"], {"transition_applied", "follow_up_authorized"})
        self.assertEqual(response["task_envelope"]["status"], "completed")
        self.assertEqual(final_fetch_status, 200)
        self.assertEqual(final_fetch_response["task"]["status"], "completed")
