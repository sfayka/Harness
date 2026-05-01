from __future__ import annotations

import ssl
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from modules.hosted_dryrun_flow import (
    DryRunFlowError,
    DryRunSession,
    GitHubChangedFile,
    GitHubCommitSnapshot,
    GitHubPullRequestSnapshot,
    build_codex_cloud_prompt,
    build_completion_claim_request,
    build_github_sync_request,
    build_linear_ingress_payload,
    build_operator_summary,
    _build_ssl_context,
    ensure_expected_file_present,
    ensure_pull_request_matches_session,
    parse_github_pull_request_url,
    summarize_pull_request_review_decision,
)


class HostedDryRunFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session = DryRunSession(
            task_id="dryrun-kno-185-20260415T191500Z",
            linear_issue_id="issue-uuid-1",
            linear_issue_identifier="KNO-185",
            linear_issue_title="Add dry-run proof doc for Harness end-to-end validation",
            linear_issue_description="Create a small proof artifact in the dry-run repository.",
        )
        self.pull_request = GitHubPullRequestSnapshot(
            owner="sfayka",
            repo="HARNESS-DRYRUN",
            number=12,
            url="https://github.com/sfayka/HARNESS-DRYRUN/pull/12",
            state="open",
            merged=False,
            branch_name="codex/dryrun-proof",
            base_branch="main",
            commit_sha="8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
            repository_node_id="R_kgDORxZwNg",
            review_decision="approved",
        )
        self.commit = GitHubCommitSnapshot(
            sha="8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
            html_url="https://github.com/sfayka/HARNESS-DRYRUN/commit/8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
            message="docs: add dry run proof",
        )

    def test_build_codex_cloud_prompt_requires_preflight_and_final_artifacts(self) -> None:
        prompt = build_codex_cloud_prompt(self.session)

        self.assertIn("`pwd`", prompt)
        self.assertIn("`git remote -v`", prompt)
        self.assertIn("`cat .codex-bootstrap-proof`", prompt)
        self.assertIn("git fetch origin --prune", prompt)
        self.assertIn("git checkout main", prompt)
        self.assertIn("git pull --ff-only origin main", prompt)
        self.assertIn("git checkout -b codex/dryrun-kno-185", prompt)
        self.assertIn("The run is invalid if the final PR head branch is `work`", prompt)
        self.assertIn("Final proof is invalid unless `Branch:` is `codex/dryrun-kno-185`", prompt)
        self.assertIn(f"Repository: {self.session.github_owner}/{self.session.github_repo}", prompt)
        self.assertIn("Commit SHA: <40-char-sha>", prompt)
        self.assertIn(self.session.target_file, prompt)

    def test_build_linear_ingress_payload_keeps_ingress_non_completion_shaped(self) -> None:
        issue = type(
            "Issue",
            (),
            {
                "issue_id": "issue-uuid-1",
                "identifier": "KNO-185",
                "title": "Dry run",
                "description": "Run the dry-run flow.",
                "priority": 2,
                "state": {"id": "wf-1", "name": "Backlog", "type": "unstarted"},
                "project": {"id": "proj-1", "name": "HARNESS-DRYRUN"},
            },
        )()

        payload = build_linear_ingress_payload(
            issue,
            task_id=self.session.task_id,
            github_owner=self.session.github_owner,
            github_repo=self.session.github_repo,
        )

        self.assertEqual(payload["task_status"], "dispatch_ready")
        self.assertFalse(payload["claimed_completion"])
        self.assertFalse(payload["acceptance_criteria_satisfied"])
        self.assertEqual(payload["external_facts"]["expected_code_context"]["repository_name"], "HARNESS-DRYRUN")

    def test_parse_github_pull_request_url_rejects_non_numeric_urls(self) -> None:
        owner, repo, number = parse_github_pull_request_url(
            "https://github.com/sfayka/HARNESS-DRYRUN/pull/12"
        )
        self.assertEqual((owner, repo, number), ("sfayka", "HARNESS-DRYRUN", 12))

        with self.assertRaises(DryRunFlowError):
            parse_github_pull_request_url("https://github.com/sfayka/HARNESS-DRYRUN/compare/main...work")

    def test_completion_claim_request_carries_current_run_branch_identity(self) -> None:
        payload = build_completion_claim_request(self.session, self.pull_request, self.commit)
        request = payload["request"]

        self.assertTrue(request["runtime_facts"]["executor_reported_success"])
        self.assertEqual(
            request["external_facts"]["expected_code_context"]["branch_name"],
            "codex/dryrun-proof",
        )
        artifact_ref = request["execution_attempt"]["artifact_references"][0]
        self.assertEqual(artifact_ref["artifact_type"], "commit")
        self.assertEqual(artifact_ref["metadata"]["branch_name"], "codex/dryrun-proof")

    def test_github_sync_request_uses_pr_commit_and_changed_files(self) -> None:
        changed_files = (
            GitHubChangedFile(
                filename="docs/dry-run-proof.md",
                status="added",
                additions=9,
                deletions=0,
            ),
        )

        payload = build_github_sync_request(
            self.session,
            self.pull_request,
            self.commit,
            changed_files,
        )

        self.assertEqual(payload["github"]["pull_request"]["reviewDecision"], "approved")
        self.assertEqual(payload["github"]["branch"]["name"], "codex/dryrun-proof")
        self.assertEqual(payload["github"]["files"][0]["filename"], "docs/dry-run-proof.md")

    def test_operator_summary_promotes_completion_validation_verdict(self) -> None:
        completion_validation = {
            "status": "accepted",
            "completion_claimed": True,
            "completion_accepted": True,
            "intent_status": "matched",
            "evidence_status": "sufficient",
        }

        summary = build_operator_summary(
            self.session,
            read_model={"task": {"completion_validation_summary": completion_validation}},
            timeline={"timeline": []},
            evaluations={"evaluations": []},
        )

        self.assertEqual(summary["completion_validation_summary"], completion_validation)
        self.assertEqual(
            summary["completion_validation_summary"],
            summary["read_model"]["task"]["completion_validation_summary"],
        )

    def test_expected_file_presence_check_fails_fast(self) -> None:
        with self.assertRaises(DryRunFlowError):
            ensure_expected_file_present(
                (
                    GitHubChangedFile(
                        filename="README.md",
                        status="modified",
                        additions=1,
                        deletions=0,
                    ),
                ),
                expected_path="docs/dry-run-proof.md",
            )

    def test_pull_request_match_rejects_reserved_work_branch(self) -> None:
        reserved_branch_pr = GitHubPullRequestSnapshot(
            owner=self.pull_request.owner,
            repo=self.pull_request.repo,
            number=self.pull_request.number,
            url=self.pull_request.url,
            state=self.pull_request.state,
            merged=self.pull_request.merged,
            branch_name="work",
            base_branch=self.pull_request.base_branch,
            commit_sha=self.pull_request.commit_sha,
            repository_node_id=self.pull_request.repository_node_id,
            review_decision=self.pull_request.review_decision,
        )

        with self.assertRaises(DryRunFlowError) as raised:
            ensure_pull_request_matches_session(self.session, reserved_branch_pr)

        self.assertIn("reserved", str(raised.exception))

    def test_review_decision_summary_prefers_changes_requested(self) -> None:
        reviews = [
            {"user": {"id": 1}, "state": "APPROVED"},
            {"user": {"id": 2}, "state": "CHANGES_REQUESTED"},
        ]
        self.assertEqual(summarize_pull_request_review_decision(reviews), "changes_requested")

        self.assertEqual(
            summarize_pull_request_review_decision(
                [
                    {"user": {"id": 1}, "state": "APPROVED"},
                    {"user": {"id": 2}, "state": "APPROVED"},
                ]
            ),
            "approved",
        )

    def test_ssl_context_uses_certifi_when_available(self) -> None:
        sentinel = ssl.create_default_context()
        with (
            patch.dict(sys.modules, {"certifi": SimpleNamespace(where=lambda: "/tmp/certifi.pem")}),
            patch("modules.hosted_dryrun_flow.ssl.create_default_context", return_value=sentinel) as factory,
        ):
            context = _build_ssl_context()

        self.assertIs(context, sentinel)
        self.assertEqual(factory.call_args_list[-1].kwargs, {"cafile": "/tmp/certifi.pem"})
        self.assertEqual(factory.call_count, 2)

    def test_ssl_context_falls_back_to_default_store_without_certifi(self) -> None:
        sentinel = ssl.create_default_context()
        with (
            patch.dict(sys.modules, {"certifi": None}),
            patch("modules.hosted_dryrun_flow.ssl.create_default_context", return_value=sentinel) as factory,
        ):
            context = _build_ssl_context()

        self.assertIs(context, sentinel)
        factory.assert_called_once_with()
