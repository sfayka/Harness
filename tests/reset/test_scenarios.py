from __future__ import annotations

import unittest

from modules.reset.scenarios import (
    SimulatedGitHubState,
    SimulatedResetScenario,
    build_worker_proof_output,
    run_simulated_reset_scenario,
)


class SimulatedResetScenarioTests(unittest.TestCase):
    def test_happy_path_verifies_without_babysitting(self) -> None:
        scenario = SimulatedResetScenario(
            name="happy_path",
            contract_id="contract-happy",
            linear_issue_id="KNO-999",
            linear_issue_title="Happy path",
            repository_owner="sfayka",
            repository_name="HARNESS-DRYRUN",
            branch_name="codex/kno-999-happy-path",
            required_changed_path="proofs/kno-999.md",
            worker_output=build_worker_proof_output(
                repository="sfayka/HARNESS-DRYRUN",
                branch="codex/kno-999-happy-path",
                commit_sha="1234567890abcdef1234567890abcdef12345678",
                pull_request_url="https://github.com/sfayka/HARNESS-DRYRUN/pull/42",
            ),
            github_state=SimulatedGitHubState(
                branch_exists=True,
                commit_exists=True,
                pull_request_payload={
                    "number": 42,
                    "html_url": "https://github.com/sfayka/HARNESS-DRYRUN/pull/42",
                    "state": "open",
                    "merged_at": None,
                    "head": {
                        "ref": "codex/kno-999-happy-path",
                        "sha": "1234567890abcdef1234567890abcdef12345678",
                        "repo": {"owner": {"login": "sfayka"}, "name": "HARNESS-DRYRUN"},
                    },
                },
            ),
        )

        result = run_simulated_reset_scenario(scenario)

        self.assertEqual(result.claim_status, 200)
        self.assertEqual(result.claim_verdict, "verified_done")
        self.assertEqual(result.final_contract["harness_status"], "verified")
        self.assertEqual(result.linear_actions[-1][:3], ("KNO-999", "Done", "verified"))
        self.assertEqual(result.repair_requests, [])
        self.assertIsNone(result.proof_error)
        self.assertEqual(result.tick_verdicts, ())
        self.assertIn("PR URL:", result.prompt)

    def test_missing_pr_url_times_out_and_requests_repair(self) -> None:
        scenario = SimulatedResetScenario(
            name="missing_pr_url",
            contract_id="contract-missing-url",
            linear_issue_id="KNO-1000",
            linear_issue_title="Missing PR URL",
            repository_owner="sfayka",
            repository_name="HARNESS-DRYRUN",
            branch_name="codex/kno-1000-missing-url",
            required_changed_path="proofs/kno-1000.md",
            worker_output="""
            Repository: sfayka/HARNESS-DRYRUN
            Branch: codex/kno-1000-missing-url
            Commit SHA: 1234567890abcdef1234567890abcdef12345678
            """,
            claim_timeout_seconds=1,
            tick_count=1,
        )

        result = run_simulated_reset_scenario(scenario)

        self.assertIsNone(result.claim_status)
        self.assertIsNone(result.claim_verdict)
        self.assertIsNotNone(result.proof_error)
        self.assertEqual(result.tick_verdicts, ("retryable_invalid_proof",))
        self.assertEqual(result.final_contract["harness_status"], "retrying")
        self.assertEqual(result.linear_actions[-1][:3], ("KNO-1000", "In Progress", "retrying"))
        self.assertEqual(len(result.repair_requests), 1)
        self.assertIn("no completion claim", result.repair_requests[0][1])

    def test_wrong_sha_claim_enters_retrying_with_real_repair_request(self) -> None:
        scenario = SimulatedResetScenario(
            name="wrong_sha",
            contract_id="contract-wrong-sha",
            linear_issue_id="KNO-1001",
            linear_issue_title="Wrong SHA",
            repository_owner="sfayka",
            repository_name="HARNESS-DRYRUN",
            branch_name="codex/kno-1001-wrong-sha",
            required_changed_path="proofs/kno-1001.md",
            worker_output=build_worker_proof_output(
                repository="sfayka/HARNESS-DRYRUN",
                branch="codex/kno-1001-wrong-sha",
                commit_sha="deadbeef90abcdef1234567890abcdef12345678",
                pull_request_url="https://github.com/sfayka/HARNESS-DRYRUN/pull/41",
            ),
            github_state=SimulatedGitHubState(
                branch_exists=True,
                commit_exists=False,
                pull_request_payload={
                    "number": 41,
                    "html_url": "https://github.com/sfayka/HARNESS-DRYRUN/pull/41",
                    "state": "open",
                    "merged_at": None,
                    "head": {
                        "ref": "codex/kno-1001-wrong-sha",
                        "sha": "1234567890abcdef1234567890abcdef12345678",
                        "repo": {"owner": {"login": "sfayka"}, "name": "HARNESS-DRYRUN"},
                    },
                },
            ),
        )

        result = run_simulated_reset_scenario(scenario)

        self.assertEqual(result.claim_status, 200)
        self.assertEqual(result.claim_verdict, "retryable_invalid_proof")
        self.assertEqual(result.final_contract["harness_status"], "retrying")
        self.assertEqual(result.linear_actions[-1][:3], ("KNO-1001", "In Progress", "retrying"))
        self.assertEqual(len(result.repair_requests), 1)
        self.assertIn("commit sha", result.repair_requests[0][1])

    def test_wrong_repository_claim_is_rejected_before_github_lookup(self) -> None:
        scenario = SimulatedResetScenario(
            name="wrong_repository",
            contract_id="contract-wrong-repo",
            linear_issue_id="KNO-1002",
            linear_issue_title="Wrong repository",
            repository_owner="sfayka",
            repository_name="HARNESS-DRYRUN",
            branch_name="codex/kno-1002-wrong-repo",
            required_changed_path="proofs/kno-1002.md",
            worker_output=build_worker_proof_output(
                repository="someone-else/HARNESS-DRYRUN",
                branch="codex/kno-1002-wrong-repo",
                commit_sha="1234567890abcdef1234567890abcdef12345678",
                pull_request_url="https://github.com/someone-else/HARNESS-DRYRUN/pull/55",
            ),
        )

        result = run_simulated_reset_scenario(scenario)

        self.assertEqual(result.claim_status, 200)
        self.assertEqual(result.claim_verdict, "retryable_invalid_proof")
        self.assertEqual(result.final_contract["harness_status"], "retrying")
        self.assertEqual(len(result.repair_requests), 1)
        self.assertIn("repository owner", result.repair_requests[0][1])

    def test_missing_pull_request_object_requests_repair(self) -> None:
        scenario = SimulatedResetScenario(
            name="missing_pr_object",
            contract_id="contract-missing-pr",
            linear_issue_id="KNO-1003",
            linear_issue_title="Missing pull request object",
            repository_owner="sfayka",
            repository_name="HARNESS-DRYRUN",
            branch_name="codex/kno-1003-missing-pr",
            required_changed_path="proofs/kno-1003.md",
            worker_output=build_worker_proof_output(
                repository="sfayka/HARNESS-DRYRUN",
                branch="codex/kno-1003-missing-pr",
                commit_sha="1234567890abcdef1234567890abcdef12345678",
                pull_request_url="https://github.com/sfayka/HARNESS-DRYRUN/pull/56",
            ),
            github_state=SimulatedGitHubState(
                branch_exists=True,
                commit_exists=True,
                pull_request_payload=None,
            ),
        )

        result = run_simulated_reset_scenario(scenario)

        self.assertEqual(result.claim_status, 200)
        self.assertEqual(result.claim_verdict, "retryable_invalid_proof")
        self.assertEqual(result.final_contract["harness_status"], "retrying")
        self.assertEqual(len(result.repair_requests), 1)
        self.assertIn("pull request does not exist", result.repair_requests[0][1])

    def test_closed_unmerged_pull_request_requests_repair(self) -> None:
        scenario = SimulatedResetScenario(
            name="closed_unmerged_pr",
            contract_id="contract-closed-pr",
            linear_issue_id="KNO-1004",
            linear_issue_title="Closed unmerged pull request",
            repository_owner="sfayka",
            repository_name="HARNESS-DRYRUN",
            branch_name="codex/kno-1004-closed-pr",
            required_changed_path="proofs/kno-1004.md",
            worker_output=build_worker_proof_output(
                repository="sfayka/HARNESS-DRYRUN",
                branch="codex/kno-1004-closed-pr",
                commit_sha="1234567890abcdef1234567890abcdef12345678",
                pull_request_url="https://github.com/sfayka/HARNESS-DRYRUN/pull/57",
            ),
            github_state=SimulatedGitHubState(
                branch_exists=True,
                commit_exists=True,
                pull_request_payload={
                    "number": 57,
                    "html_url": "https://github.com/sfayka/HARNESS-DRYRUN/pull/57",
                    "state": "closed",
                    "merged_at": None,
                    "head": {
                        "ref": "codex/kno-1004-closed-pr",
                        "sha": "1234567890abcdef1234567890abcdef12345678",
                        "repo": {"owner": {"login": "sfayka"}, "name": "HARNESS-DRYRUN"},
                    },
                },
            ),
        )

        result = run_simulated_reset_scenario(scenario)

        self.assertEqual(result.claim_status, 200)
        self.assertEqual(result.claim_verdict, "retryable_invalid_proof")
        self.assertEqual(result.final_contract["harness_status"], "retrying")
        self.assertEqual(len(result.repair_requests), 1)
        self.assertIn("closed without being merged", result.repair_requests[0][1])

    def test_retry_budget_exhaustion_escalates_to_review(self) -> None:
        scenario = SimulatedResetScenario(
            name="retry_budget_exhaustion",
            contract_id="contract-retry-budget",
            linear_issue_id="KNO-1005",
            linear_issue_title="Retry budget exhaustion",
            repository_owner="sfayka",
            repository_name="HARNESS-DRYRUN",
            branch_name="codex/kno-1005-retry-budget",
            required_changed_path="proofs/kno-1005.md",
            worker_output=build_worker_proof_output(
                repository="sfayka/HARNESS-DRYRUN",
                branch="codex/kno-1005-retry-budget",
                commit_sha="deadbeef90abcdef1234567890abcdef12345678",
                pull_request_url="https://github.com/sfayka/HARNESS-DRYRUN/pull/58",
            ),
            github_state=SimulatedGitHubState(
                branch_exists=True,
                commit_exists=False,
                pull_request_payload={
                    "number": 58,
                    "html_url": "https://github.com/sfayka/HARNESS-DRYRUN/pull/58",
                    "state": "open",
                    "merged_at": None,
                    "head": {
                        "ref": "codex/kno-1005-retry-budget",
                        "sha": "1234567890abcdef1234567890abcdef12345678",
                        "repo": {"owner": {"login": "sfayka"}, "name": "HARNESS-DRYRUN"},
                    },
                },
            ),
            retry_budget=1,
            tick_count=1,
        )

        result = run_simulated_reset_scenario(scenario)

        self.assertEqual(result.claim_status, 200)
        self.assertEqual(result.claim_verdict, "retryable_invalid_proof")
        self.assertEqual(result.tick_verdicts, ("needs_review",))
        self.assertEqual(result.final_contract["harness_status"], "needs_review")
        self.assertEqual(result.linear_actions[-1][:3], ("KNO-1005", "In Review", "needs_review"))
