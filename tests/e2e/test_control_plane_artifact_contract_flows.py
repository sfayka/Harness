from __future__ import annotations

from copy import deepcopy

from tests.e2e.runtime_harness import RuntimeApiTestCase
from tests.e2e.scenario_builders import (
    build_completion_claim_request,
    build_create_task_payload,
    build_execution_attempt_payload,
    build_happy_path_overlays,
)


class ControlPlaneArtifactContractFlowTests(RuntimeApiTestCase):
    def _mark_task_assigned(self, task_id: str, *, executor_id: str) -> None:
        self.service.store.update_task(
            {
                **deepcopy(self.service.store.get_task(task_id)),
                "status": "assigned",
                "assigned_executor": {
                    "executor_type": "codex",
                    "executor_id": executor_id,
                    "assignment_reason": "Seed assigned state for artifact-contract flow coverage.",
                },
            }
        )

    def _assert_contract_violation(self, claimed, *, expected_rule: str) -> None:
        self.assertEqual(claimed.response["action"], "contract_violation_failed")
        self.assertEqual(claimed.task["status"], "failed")
        self.assertEqual(claimed.read_model["task"]["current_status"], "failed")
        self.assertEqual(claimed.read_model["task"]["failure_summary"]["failure_type"], "contract_violation")
        failed_rules = {
            item["rule"] for item in claimed.response["contract_violation"]["validation"]["rule_failures"]
        }
        self.assertIn(expected_rule, failed_rules)
        timeline_attempts = [
            event for event in claimed.timeline["timeline"] if event["event_type"] == "execution_attempt_recorded"
        ]
        self.assertTrue(timeline_attempts)

    def test_missing_branch_identity_fails_end_to_end(self) -> None:
        scenario = self.create_task_scenario(
            build_create_task_payload(
                "e2e-artifact-missing-branch",
                title="Missing branch identity should fail the execution contract",
            )
        )
        self._mark_task_assigned(scenario.task_id, executor_id="executor-artifact-missing-branch-1")

        attempt = build_execution_attempt_payload(attempt_id="attempt-missing-branch-1")
        attempt["execution_attempt"]["artifact_references"] = [
            {
                "reference_id": "attempt-missing-branch-1:commit",
                "artifact_type": "commit",
                "location": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/commit/8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                "metadata": {
                    "repository_host": "github.com",
                    "repository_owner": "KnoxAnalytics",
                    "repository_name": "HARNESS-DRYRUN",
                    "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                },
            }
        ]
        overlays = build_happy_path_overlays()
        external_facts = deepcopy(overlays["external_facts"])
        external_facts["expected_code_context"].pop("branch_name", None)
        external_facts["github_facts"].pop("branch", None)

        claimed = scenario.completion_claim(
            build_completion_claim_request(
                claim_id="claim-missing-branch-1",
                attempt_id="attempt-missing-branch-1",
                execution_attempt=attempt,
                external_facts=external_facts,
                runtime_facts={"executor_reported_success": True, "attempt_count": 1},
            )
        )

        self._assert_contract_violation(claimed, expected_rule="missing_branch_identity")

    def test_missing_pull_request_url_fails_end_to_end(self) -> None:
        scenario = self.create_task_scenario(
            build_create_task_payload(
                "e2e-artifact-missing-pr-url",
                title="Missing PR URL should fail the execution contract",
            )
        )
        self._mark_task_assigned(scenario.task_id, executor_id="executor-artifact-missing-pr-url-1")

        overlays = build_happy_path_overlays()
        new_artifacts = deepcopy(overlays["linked_artifacts"])
        new_artifacts[0]["location"] = None

        claimed = scenario.completion_claim(
            build_completion_claim_request(
                claim_id="claim-missing-pr-url-1",
                attempt_id="attempt-missing-pr-url-1",
                execution_attempt=build_execution_attempt_payload(attempt_id="attempt-missing-pr-url-1"),
                new_artifacts=new_artifacts,
                completion_evidence=overlays["completion_evidence"],
                external_facts=overlays["external_facts"],
                runtime_facts={"executor_reported_success": True, "attempt_count": 1},
            )
        )

        self._assert_contract_violation(claimed, expected_rule="missing_pr_url")

    def test_invalid_non_numeric_pull_request_url_fails_end_to_end(self) -> None:
        scenario = self.create_task_scenario(
            build_create_task_payload(
                "e2e-artifact-invalid-pr-url",
                title="Invalid PR URL should fail the execution contract",
            )
        )
        self._mark_task_assigned(scenario.task_id, executor_id="executor-artifact-invalid-pr-url-1")

        overlays = build_happy_path_overlays()
        new_artifacts = deepcopy(overlays["linked_artifacts"])
        new_artifacts[0]["location"] = "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/compare/main...work"
        external_facts = deepcopy(overlays["external_facts"])
        external_facts["github_facts"]["pull_request"]["url"] = (
            "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/pull/new/work"
        )

        claimed = scenario.completion_claim(
            build_completion_claim_request(
                claim_id="claim-invalid-pr-url-1",
                attempt_id="attempt-invalid-pr-url-1",
                execution_attempt=build_execution_attempt_payload(attempt_id="attempt-invalid-pr-url-1"),
                new_artifacts=new_artifacts,
                completion_evidence=overlays["completion_evidence"],
                external_facts=external_facts,
                runtime_facts={"executor_reported_success": True, "attempt_count": 1},
            )
        )

        self._assert_contract_violation(claimed, expected_rule="invalid_pr_url")

    def test_closed_pull_request_fails_end_to_end(self) -> None:
        scenario = self.create_task_scenario(
            build_create_task_payload(
                "e2e-artifact-closed-pr",
                title="Closed PR proof should fail the execution contract",
            )
        )
        self._mark_task_assigned(scenario.task_id, executor_id="executor-artifact-closed-pr-1")

        overlays = build_happy_path_overlays()
        new_artifacts = deepcopy(overlays["linked_artifacts"])
        new_artifacts[0]["metadata"]["pull_request_state"] = "closed"
        external_facts = deepcopy(overlays["external_facts"])
        external_facts["github_facts"]["pull_request"]["state"] = "closed"

        claimed = scenario.completion_claim(
            build_completion_claim_request(
                claim_id="claim-closed-pr-1",
                attempt_id="attempt-closed-pr-1",
                execution_attempt=build_execution_attempt_payload(attempt_id="attempt-closed-pr-1"),
                new_artifacts=new_artifacts,
                completion_evidence=overlays["completion_evidence"],
                external_facts=external_facts,
                runtime_facts={"executor_reported_success": True, "attempt_count": 1},
            )
        )

        self._assert_contract_violation(claimed, expected_rule="stale_pull_request_not_allowed")

    def test_unknown_pull_request_state_fails_end_to_end(self) -> None:
        scenario = self.create_task_scenario(
            build_create_task_payload(
                "e2e-artifact-unknown-pr-state",
                title="Unknown PR state should fail the execution contract",
            )
        )
        self._mark_task_assigned(scenario.task_id, executor_id="executor-artifact-unknown-pr-state-1")

        overlays = build_happy_path_overlays()
        new_artifacts = deepcopy(overlays["linked_artifacts"])
        new_artifacts[0]["metadata"].pop("pull_request_state", None)
        external_facts = deepcopy(overlays["external_facts"])
        external_facts["github_facts"]["pull_request"]["state"] = None

        claimed = scenario.completion_claim(
            build_completion_claim_request(
                claim_id="claim-unknown-pr-state-1",
                attempt_id="attempt-unknown-pr-state-1",
                execution_attempt=build_execution_attempt_payload(attempt_id="attempt-unknown-pr-state-1"),
                new_artifacts=new_artifacts,
                completion_evidence=overlays["completion_evidence"],
                external_facts=external_facts,
                runtime_facts={"executor_reported_success": True, "attempt_count": 1},
            )
        )

        self._assert_contract_violation(claimed, expected_rule="unknown_pull_request_state")
