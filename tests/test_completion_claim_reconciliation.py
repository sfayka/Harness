from __future__ import annotations

import tempfile
import unittest

from modules.api import HarnessApiService, _requires_missing_pr_reconciliation, parse_completion_claim_request
from modules.reconciliation_runtime import (
    GitHubPullRequestRecord,
    ReconciliationFailureType,
    ReconciliationHandlerRegistry,
    RetryableReconciliationRuntimeError,
    _current_completion_claim,
    _current_execution_attempt,
    build_default_reconciliation_registry,
)
from modules.intake import create_task_envelope
from modules.store import FileBackedHarnessStore


_USE_CREATED_RESPONSE = object()


class _FakeGitHubGateway:
    def __init__(
        self,
        *,
        branch_exists: bool = True,
        branch_head_commit_sha: str | None = "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
        commit_exists: bool = True,
        existing_branch_prs: tuple[GitHubPullRequestRecord, ...] = (),
        existing_commit_prs: tuple[GitHubPullRequestRecord, ...] = (),
        created_pr: GitHubPullRequestRecord | None = None,
        persisted_created_pr: GitHubPullRequestRecord | object | None = _USE_CREATED_RESPONSE,
        default_branch: str = "main",
        branch_exists_error: Exception | None = None,
        commit_exists_error: Exception | None = None,
        create_pull_request_error: Exception | None = None,
    ) -> None:
        self._branch_exists = branch_exists
        self._branch_head_commit_sha = branch_head_commit_sha
        self._commit_exists = commit_exists
        self._existing_branch_prs = existing_branch_prs
        self._existing_commit_prs = existing_commit_prs
        self._branch_exists_error = branch_exists_error
        self._commit_exists_error = commit_exists_error
        self._create_pull_request_error = create_pull_request_error
        self._created_pr = created_pr or GitHubPullRequestRecord(
            number=401,
            url="https://github.com/KnoxAnalytics/HARNESS-DRYRUN/pull/401",
            state="open",
            repository_owner="KnoxAnalytics",
            repository_name="HARNESS-DRYRUN",
            head_branch="codex/e2e-test",
            head_sha="8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
            base_branch="main",
        )
        self._default_branch = default_branch
        self.create_calls = 0
        self.last_create_pull_request: dict[str, str] | None = None
        self.get_pull_request_calls = 0
        self._persisted_created_pr = persisted_created_pr

    def branch_exists(self, *, owner: str, repo: str, branch_name: str) -> bool:
        del owner, repo, branch_name
        if self._branch_exists_error is not None:
            raise self._branch_exists_error
        return self._branch_exists

    def branch_head_commit_sha(self, *, owner: str, repo: str, branch_name: str) -> str | None:
        del owner, repo, branch_name
        if self._branch_exists_error is not None:
            raise self._branch_exists_error
        return self._branch_head_commit_sha

    def commit_exists(self, *, owner: str, repo: str, commit_sha: str) -> bool:
        del owner, repo, commit_sha
        if self._commit_exists_error is not None:
            raise self._commit_exists_error
        return self._commit_exists

    def default_branch(self, *, owner: str, repo: str) -> str | None:
        del owner, repo
        return self._default_branch

    def find_pull_requests_by_branch(
        self,
        *,
        owner: str,
        repo: str,
        branch_name: str,
    ) -> tuple[GitHubPullRequestRecord, ...]:
        del owner, repo, branch_name
        return self._existing_branch_prs

    def find_pull_requests_by_commit(
        self,
        *,
        owner: str,
        repo: str,
        commit_sha: str,
    ) -> tuple[GitHubPullRequestRecord, ...]:
        del owner, repo, commit_sha
        return self._existing_commit_prs

    def create_pull_request(
        self,
        *,
        owner: str,
        repo: str,
        title: str,
        body: str,
        head: str,
        base: str,
    ) -> GitHubPullRequestRecord:
        if self._create_pull_request_error is not None:
            raise self._create_pull_request_error
        self.create_calls += 1
        self.last_create_pull_request = {
            "owner": owner,
            "repo": repo,
            "title": title,
            "body": body,
            "head": head,
            "base": base,
        }
        return GitHubPullRequestRecord(
            number=self._created_pr.number,
            url=self._created_pr.url,
            state=self._created_pr.state,
            review_state=self._created_pr.review_state,
            merged=self._created_pr.merged,
            repository_owner=owner,
            repository_name=repo,
            head_branch=head,
            head_sha=self._created_pr.head_sha,
            base_branch=base,
            title=title,
            body=body,
        )

    def get_pull_request(
        self,
        *,
        owner: str,
        repo: str,
        number: int,
    ) -> GitHubPullRequestRecord | None:
        del owner, repo
        self.get_pull_request_calls += 1
        if self._persisted_created_pr is _USE_CREATED_RESPONSE:
            if self.last_create_pull_request is None:
                return None
            return GitHubPullRequestRecord(
                number=self._created_pr.number,
                url=self._created_pr.url,
                state=self._created_pr.state,
                review_state=self._created_pr.review_state,
                merged=self._created_pr.merged,
                repository_owner=self.last_create_pull_request["owner"],
                repository_name=self.last_create_pull_request["repo"],
                head_branch=self.last_create_pull_request["head"],
                head_sha=self._created_pr.head_sha,
                base_branch=self.last_create_pull_request["base"],
                title=self.last_create_pull_request["title"],
                body=self.last_create_pull_request["body"],
            )
        if self._persisted_created_pr is None:
            return None
        if self._persisted_created_pr.number != number:
            return None
        return self._persisted_created_pr


def _registry_with_gateway(gateway: _FakeGitHubGateway) -> ReconciliationHandlerRegistry:
    registry = build_default_reconciliation_registry()
    missing_pr_handler = registry.get(ReconciliationFailureType.MISSING_PR_AFTER_EXECUTION)
    missing_commit_handler = registry.get(ReconciliationFailureType.MISSING_COMMIT_AFTER_EXECUTION)
    registry.register(
        ReconciliationFailureType.MISSING_PR_AFTER_EXECUTION,
        missing_pr_handler.__class__(github=gateway),
    )
    registry.register(
        ReconciliationFailureType.MISSING_COMMIT_AFTER_EXECUTION,
        missing_commit_handler.__class__(github=gateway),
    )
    return registry


def _pull_request(
    *,
    number: int,
    state: str = "open",
    merged: bool = False,
    head_branch: str = "codex/e2e-test",
    head_sha: str | None = "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
    repository_owner: str = "KnoxAnalytics",
    repository_name: str = "HARNESS-DRYRUN",
    title: str | None = "Reconcile missing pull request",
    body: str | None = "Task task-pr-reconcile-1",
) -> GitHubPullRequestRecord:
    return GitHubPullRequestRecord(
        number=number,
        url=f"https://github.com/{repository_owner}/{repository_name}/pull/{number}",
        state=state,
        merged=merged,
        repository_owner=repository_owner,
        repository_name=repository_name,
        head_branch=head_branch,
        head_sha=head_sha,
        base_branch="main",
        title=title,
        body=body,
    )


def _run_linkage_markers(
    *,
    task_id: str,
    attempt_id: str,
    claim_id: str,
    branch_name: str = "codex/e2e-test",
    commit_sha: str = "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
) -> str:
    return "\n".join(
        [
            f"Harness-Task-ID: {task_id}",
            f"Harness-Attempt-ID: {attempt_id}",
            f"Harness-Completion-Claim-ID: {claim_id}",
            f"Harness-Branch: {branch_name}",
            f"Harness-Commit-SHA: {commit_sha}",
        ]
    )


def _task_envelope(task_id: str = "task-pr-reconcile-1") -> dict:
    task = create_task_envelope(
        {
            "id": task_id,
            "title": "Reconcile missing pull request",
            "description": "Exercise post-execution PR reconciliation.",
            "origin": {
                "source_system": "openclaw",
                "source_type": "ingress_request",
                "source_id": f"req-{task_id}",
            },
            "acceptance_criteria": [
                {
                    "id": "ac-1",
                    "description": "Harness can reconcile a missing PR after execution.",
                    "required": True,
                }
            ],
        },
        now="2026-04-04T12:00:00Z",
    )
    task["status"] = "executing"
    task["assigned_executor"] = {
        "executor_type": "codex",
        "executor_id": "executor-1",
        "assignment_reason": "Runtime coverage for reconciliation.",
    }
    task["artifacts"]["items"] = [
        {
            "id": "artifact-commit-1",
            "type": "commit",
            "title": None,
            "description": None,
            "location": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/commit/8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
            "content_type": None,
            "external_id": "commit-8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
            "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
            "pull_request_number": None,
            "review_state": None,
            "provenance": {
                "source_system": "github",
                "source_type": "api",
                "source_id": "commit/8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                "captured_by": "github-sync",
            },
            "verification_status": "verified",
            "repository": {
                "host": "github.com",
                "owner": "KnoxAnalytics",
                "name": "HARNESS-DRYRUN",
                "external_id": "repo-dryrun-1",
            },
            "branch": {
                "name": "codex/e2e-test",
                "base_branch": "main",
                "head_commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
            },
            "changed_files": [],
            "external_refs": [],
            "captured_at": "2026-04-04T12:01:00Z",
            "metadata": {},
        }
    ]
    task["artifacts"]["completion_evidence"] = {
        "policy": "required",
        "status": "satisfied",
        "required_artifact_types": ["commit"],
        "validated_artifact_ids": ["artifact-commit-1"],
        "validation_method": "external_reconciliation",
        "validated_at": "2026-04-04T12:01:30Z",
        "validator": {
            "source_system": "harness",
            "source_type": "verification",
            "source_id": "verification-existing-1",
            "captured_by": "github-sync",
        },
        "notes": None,
    }
    return task


def _with_pull_request_artifact(
    task: dict,
    *,
    number: int,
    branch_name: str = "codex/e2e-test",
    head_sha: str = "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
    verification_status: str = "verified",
) -> dict:
    task["artifacts"]["items"].append(
        {
            "id": f"artifact-pr-{number}",
            "type": "pull_request",
            "title": "Existing PR artifact",
            "description": "Pre-attached PR artifact for completion-claim reconciliation tests.",
            "location": f"https://github.com/KnoxAnalytics/HARNESS-DRYRUN/pull/{number}",
            "content_type": None,
            "external_id": f"PR-{number}",
            "commit_sha": None,
            "pull_request_number": number,
            "review_state": "approved",
            "provenance": {
                "source_system": "github",
                "source_type": "api",
                "source_id": f"pull/{number}",
                "captured_by": "github-sync",
            },
            "verification_status": verification_status,
            "repository": {
                "host": "github.com",
                "owner": "KnoxAnalytics",
                "name": "HARNESS-DRYRUN",
                "external_id": "repo-dryrun-1",
            },
            "branch": {
                "name": branch_name,
                "base_branch": "main",
                "head_commit_sha": head_sha,
            },
            "changed_files": [],
            "external_refs": [],
            "captured_at": "2026-04-04T12:01:15Z",
            "metadata": {
                "attached_by": "test",
                "pull_request_state": "open",
            },
        }
    )
    return task


def _without_commit_artifact(task: dict) -> dict:
    task["artifacts"]["items"] = [
        artifact
        for artifact in task["artifacts"]["items"]
        if not (isinstance(artifact, dict) and artifact.get("type") == "commit")
    ]
    completion_evidence = task["artifacts"]["completion_evidence"]
    completion_evidence["required_artifact_types"] = ["pull_request", "commit"]
    completion_evidence["validated_artifact_ids"] = [
        artifact["id"]
        for artifact in task["artifacts"]["items"]
        if isinstance(artifact, dict) and artifact.get("type") == "pull_request"
    ]
    return task


def _completion_claim_payload(claim_id: str = "claim-1") -> dict:
    return {
        "request": {
            "completion_claim": {
                "claim_id": claim_id,
                "reported_at": "2026-04-04T12:02:00Z",
                "reported_by": "codex",
                "reason": "Execution completed successfully.",
                "metadata": {"attempt_id": f"{claim_id}:attempt"},
            },
            "execution_attempt": {
                "attempt_id": f"{claim_id}:attempt",
                "recorded_at": "2026-04-04T12:02:05Z",
                "status": "completed",
                "reported_by": "codex",
                "artifact_references": [
                    {
                        "reference_id": f"{claim_id}:attempt:log",
                        "artifact_type": "execution_log",
                        "location": "stub://attempts/log",
                    }
                ],
                "metadata": {"executor_run_id": f"run-{claim_id}"},
            },
            "acceptance_criteria_satisfied": True,
            "runtime_facts": {
                "executor_reported_success": True,
                "attempt_count": 1,
                "latest_attempt_outcome": "completed",
            },
            "external_facts": {
                "expected_code_context": {
                    "repository_host": "github.com",
                    "repository_owner": "KnoxAnalytics",
                    "repository_name": "HARNESS-DRYRUN",
                    "branch_name": "codex/e2e-test",
                    "base_branch": "main",
                },
                "github_facts": {
                    "artifact_found": True,
                    "repository": {
                        "host": "github.com",
                        "owner": "KnoxAnalytics",
                        "name": "HARNESS-DRYRUN",
                    },
                    "branch": {
                        "name": "codex/e2e-test",
                        "base_branch": "main",
                        "head_commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                    },
                    "commit": {
                        "sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                    },
                },
                "linear_facts": {
                    "record_found": True,
                    "issue_id": "lin-1",
                    "issue_key": "HAR-1",
                    "state": "completed",
                    "workflow": {
                        "workflow_id": "workflow-completed",
                        "workflow_name": "completed",
                        "state_type": "completed",
                    },
                },
            },
        }
    }


def _latest_reconciliation_attempt(task_envelope: dict) -> dict:
    return task_envelope["reconciliation"]["attempts"][-1]


def _record_execution_attempt(
    task: dict,
    *,
    claim_id: str,
    attempt_id: str,
    status: str,
    recorded_at: str,
) -> dict:
    execution_metadata = task.setdefault("observability", {}).setdefault("execution_metadata", {})
    advisory_claims = execution_metadata.setdefault("advisory_completion_claims", [])
    execution_attempts = execution_metadata.setdefault("execution_attempts", [])
    advisory_claims.append(
        {
            "claim_id": claim_id,
            "reported_at": recorded_at,
            "reported_by": "codex",
            "reason": f"Historical attempt {attempt_id}",
            "metadata": {"attempt_id": attempt_id},
        }
    )
    execution_attempts.append(
        {
            "attempt_id": attempt_id,
            "recorded_at": recorded_at,
            "status": status,
            "reported_by": "codex",
            "completion_claim_id": claim_id,
            "artifact_references": [],
            "metadata": {"executor_run_id": f"run-{attempt_id}"},
            "reevaluation": {},
        }
    )
    return task


def _remove_commit_context(payload: dict) -> dict:
    request = payload["request"]
    request["external_facts"].pop("github_facts", None)
    return payload


def _prepare_branch_only_reconciliation_task(task: dict) -> dict:
    task["artifacts"]["items"] = []
    task["artifacts"]["completion_evidence"] = {
        "policy": "not_applicable",
        "status": "not_applicable",
        "required_artifact_types": [],
        "validated_artifact_ids": [],
        "validation_method": "none",
        "validated_at": None,
        "validator": None,
        "notes": None,
    }
    return task


class CompletionClaimReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_current_completion_claim_uses_newest_reported_at_when_claims_are_out_of_order(self) -> None:
        task = _task_envelope(task_id="task-current-claim-order")
        task = _record_execution_attempt(
            task,
            claim_id="claim-newer",
            attempt_id="attempt-newer",
            status="completed",
            recorded_at="2026-04-11T09:10:05Z",
        )
        task = _record_execution_attempt(
            task,
            claim_id="claim-older",
            attempt_id="attempt-older",
            status="failed",
            recorded_at="2026-04-11T09:05:05Z",
        )

        claim = _current_completion_claim(task)

        self.assertIsNotNone(claim)
        self.assertEqual(claim["claim_id"], "claim-newer")

    def test_current_execution_attempt_uses_attempt_for_newest_claim_when_claims_are_out_of_order(self) -> None:
        task = _task_envelope(task_id="task-current-attempt-order")
        task = _record_execution_attempt(
            task,
            claim_id="claim-newer",
            attempt_id="attempt-newer",
            status="completed",
            recorded_at="2026-04-11T09:10:05Z",
        )
        task = _record_execution_attempt(
            task,
            claim_id="claim-older",
            attempt_id="attempt-older",
            status="failed",
            recorded_at="2026-04-11T09:05:05Z",
        )

        attempt = _current_execution_attempt(task)

        self.assertIsNotNone(attempt)
        self.assertEqual(attempt["attempt_id"], "attempt-newer")

    def test_submit_completion_claim_attaches_existing_open_pr_with_matching_branch_and_sha(self) -> None:
        gateway = _FakeGitHubGateway(
            existing_branch_prs=(_pull_request(number=77),),
        )
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_gateway(gateway),
        )
        task = _task_envelope()
        service.store.create_task(task)

        status, payload = service.submit_completion_claim(task["id"], _completion_claim_payload())
        timeline_status, timeline_payload = service.get_task_timeline(task["id"])

        self.assertEqual(status, 200)
        self.assertEqual(payload["task_envelope"]["status"], "completed")
        self.assertEqual(payload["action"], "transition_applied")
        self.assertTrue(payload["accepted_completion"])
        self.assertEqual(gateway.create_calls, 0)
        self.assertTrue(
            any(item["type"] == "pull_request" for item in payload["task_envelope"]["artifacts"]["items"])
        )
        attempt = _latest_reconciliation_attempt(payload["task_envelope"])
        self.assertEqual(attempt["details"]["pull_request_candidates"][0]["validation"]["matched_by"], ["head_sha_match", "task_linkage"])
        self.assertEqual(payload["task_envelope"]["reconciliation"]["status"], "resolved")
        self.assertEqual(payload["task_envelope"]["status_history"][-2]["to_status"], "reconciling")
        self.assertEqual(payload["task_envelope"]["status_history"][-1]["to_status"], "completed")
        self.assertEqual(timeline_status, 200)
        self.assertTrue(
            any(event["event_type"] == "reconciliation_attempt_recorded" for event in timeline_payload["timeline"])
        )

    def test_submit_completion_claim_skips_reconciliation_for_valid_current_run_pr_artifact(self) -> None:
        gateway = _FakeGitHubGateway()
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_gateway(gateway),
        )
        task = _with_pull_request_artifact(_task_envelope(task_id="task-pr-artifact-valid"), number=120)
        service.store.create_task(task)

        status, payload = service.submit_completion_claim(task["id"], _completion_claim_payload("claim-artifact-valid"))

        self.assertEqual(status, 200)
        self.assertEqual(payload["task_envelope"]["status"], "completed")
        self.assertEqual(gateway.create_calls, 0)
        self.assertEqual(payload["task_envelope"]["reconciliation"]["attempts"], [])
        self.assertEqual(
            len([item for item in payload["task_envelope"]["artifacts"]["items"] if item["type"] == "pull_request"]),
            1,
        )

    def test_submit_completion_claim_does_not_skip_reconciliation_for_stale_attached_pr_artifact(self) -> None:
        created_pr = _pull_request(number=404)
        gateway = _FakeGitHubGateway(created_pr=created_pr)
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_gateway(gateway),
        )
        task = _with_pull_request_artifact(
            _task_envelope(task_id="task-pr-artifact-stale"),
            number=121,
            head_sha="1111111111111111111111111111111111111111",
        )
        service.store.create_task(task)

        status, payload = service.submit_completion_claim(task["id"], _completion_claim_payload("claim-artifact-stale"))

        self.assertEqual(status, 200)
        self.assertEqual(payload["task_envelope"]["status"], "completed")
        self.assertEqual(gateway.create_calls, 1)
        self.assertEqual(gateway.get_pull_request_calls, 1)
        attempt = _latest_reconciliation_attempt(payload["task_envelope"])
        self.assertEqual(attempt["details"]["final_decision"]["result"], "created_new")
        self.assertTrue(attempt["details"]["created_pull_request_revalidated"])
        self.assertEqual(payload["task_envelope"]["reconciliation"]["last_pr_url"], gateway._created_pr.url)
        self.assertEqual(
            len([item for item in payload["task_envelope"]["artifacts"]["items"] if item["type"] == "pull_request"]),
            2,
        )

    def test_submit_completion_claim_rejects_closed_pr_from_prior_run_and_creates_new_pr(self) -> None:
        gateway = _FakeGitHubGateway(
            existing_branch_prs=(
                _pull_request(
                    number=78,
                    state="closed",
                    merged=False,
                    head_sha="1111111111111111111111111111111111111111",
                ),
            ),
            created_pr=_pull_request(number=401),
        )
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_gateway(gateway),
        )
        task = _task_envelope(task_id="task-pr-reconcile-closed")
        service.store.create_task(task)

        status, payload = service.submit_completion_claim(task["id"], _completion_claim_payload("claim-closed"))

        self.assertEqual(status, 200)
        self.assertEqual(payload["task_envelope"]["status"], "completed")
        self.assertEqual(gateway.create_calls, 1)
        attempt = _latest_reconciliation_attempt(payload["task_envelope"])
        candidate_details = attempt["details"]["pull_request_candidates"]
        self.assertEqual(candidate_details[0]["number"], 78)
        self.assertFalse(candidate_details[0]["validation"]["accepted"])
        self.assertIn("closed_pr_not_allowed", candidate_details[0]["validation"]["reasons"])
        self.assertIn("head_sha_mismatch", candidate_details[0]["validation"]["reasons"])
        self.assertEqual(attempt["details"]["pull_request_lookup"]["number"], 401)
        self.assertEqual(payload["task_envelope"]["reconciliation"]["last_pr_url"], gateway._created_pr.url)

    def test_submit_completion_claim_rejects_merged_pr_with_wrong_sha_and_creates_new_pr(self) -> None:
        gateway = _FakeGitHubGateway(
            existing_branch_prs=(
                _pull_request(
                    number=79,
                    state="closed",
                    merged=True,
                    head_sha="2222222222222222222222222222222222222222",
                ),
            ),
            created_pr=_pull_request(number=402),
        )
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_gateway(gateway),
        )
        task = _task_envelope(task_id="task-pr-reconcile-merged")
        service.store.create_task(task)

        status, payload = service.submit_completion_claim(task["id"], _completion_claim_payload("claim-merged"))

        self.assertEqual(status, 200)
        self.assertEqual(payload["task_envelope"]["status"], "completed")
        self.assertEqual(gateway.create_calls, 1)
        attempt = _latest_reconciliation_attempt(payload["task_envelope"])
        stale_candidate = attempt["details"]["pull_request_candidates"][0]
        self.assertEqual(stale_candidate["number"], 79)
        self.assertIn("merged_pr_not_allowed", stale_candidate["validation"]["reasons"])
        self.assertIn("head_sha_mismatch", stale_candidate["validation"]["reasons"])
        self.assertEqual(attempt["details"]["pull_request_lookup"]["number"], 402)

    def test_submit_completion_claim_rejects_branch_only_candidate_without_current_commit_evidence(self) -> None:
        gateway = _FakeGitHubGateway(
            existing_branch_prs=(
                _pull_request(number=80, head_sha=None, body="Historical PR without current commit evidence"),
            ),
            created_pr=_pull_request(number=403),
        )
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_gateway(gateway),
        )
        task = _task_envelope(task_id="task-pr-reconcile-branch-only")
        service.store.create_task(task)

        status, payload = service.submit_completion_claim(task["id"], _completion_claim_payload("claim-branch-only"))

        self.assertEqual(status, 200)
        self.assertEqual(payload["task_envelope"]["status"], "completed")
        self.assertEqual(gateway.create_calls, 1)
        attempt = _latest_reconciliation_attempt(payload["task_envelope"])
        stale_candidate = attempt["details"]["pull_request_candidates"][0]
        self.assertIn("missing_head_sha", stale_candidate["validation"]["reasons"])
        self.assertEqual(attempt["details"]["final_decision"]["result"], "created_new")

    def test_submit_completion_claim_resolves_missing_commit_from_branch_head_before_reconciliation(self) -> None:
        resolved_sha = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        created_pr = _pull_request(number=409, head_sha=resolved_sha)
        gateway = _FakeGitHubGateway(
            branch_head_commit_sha=resolved_sha,
            created_pr=created_pr,
        )
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_gateway(gateway),
        )
        task = _prepare_branch_only_reconciliation_task(
            _task_envelope(task_id="task-pr-reconcile-missing-commit-fallback")
        )
        service.store.create_task(task)

        payload = _remove_commit_context(_completion_claim_payload("claim-missing-commit-fallback"))
        status, response = service.submit_completion_claim(task["id"], payload)

        self.assertEqual(status, 200)
        self.assertEqual(response["action"], "transition_applied")
        self.assertEqual(response["task_envelope"]["reconciliation"]["status"], "resolved")
        attempts = response["task_envelope"]["reconciliation"]["attempts"]
        self.assertEqual(
            [attempt["failure_type"] for attempt in attempts[-2:]],
            ["missing_pr_after_execution", "missing_commit_after_execution"],
        )
        pr_attempt, commit_attempt = attempts[-2:]
        self.assertEqual(pr_attempt["status"], "resolved")
        self.assertEqual(pr_attempt["details"]["branch_head_commit_sha"], resolved_sha)
        self.assertEqual(pr_attempt["details"]["commit_sha"], resolved_sha)
        self.assertTrue(pr_attempt["details"]["created_pull_request_revalidated"])
        self.assertEqual(pr_attempt["details"]["final_decision"]["result"], "created_new")
        self.assertEqual(commit_attempt["status"], "resolved")
        self.assertEqual(commit_attempt["details"]["commit_sha"], resolved_sha)
        self.assertEqual(commit_attempt["details"]["final_decision"]["result"], "attached_commit_artifact")

    def test_submit_completion_claim_escalates_when_missing_commit_cannot_be_resolved_from_branch_head(self) -> None:
        gateway = _FakeGitHubGateway(
            branch_head_commit_sha=None,
        )
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_gateway(gateway),
        )
        task = _prepare_branch_only_reconciliation_task(
            _task_envelope(task_id="task-pr-reconcile-missing-commit-unresolved")
        )
        service.store.create_task(task)

        payload = _remove_commit_context(_completion_claim_payload("claim-missing-commit-unresolved"))
        status, response = service.submit_completion_claim(task["id"], payload)

        self.assertEqual(status, 200)
        self.assertEqual(response["action"], "reconciliation_terminal_failed")
        self.assertEqual(response["task_envelope"]["status"], "failed")
        self.assertFalse(response["requires_review"])
        attempt = response["reconciliation_attempt"]
        self.assertEqual(attempt["details"]["branch_head_commit_sha"], None)
        self.assertEqual(attempt["details"]["error_disposition"], "terminal_failed")
        self.assertEqual(
            attempt["details"]["error"],
            "Commit SHA is required for missing_pr_after_execution reconciliation and could not be resolved from the branch head",
        )

    def test_submit_completion_claim_creates_pr_once_and_is_idempotent_on_repeat(self) -> None:
        created_pr = _pull_request(number=401)
        gateway = _FakeGitHubGateway(created_pr=created_pr)
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_gateway(gateway),
        )
        task = _task_envelope(task_id="task-pr-reconcile-repeat")
        service.store.create_task(task)

        first_status, first_payload = service.submit_completion_claim(
            task["id"], _completion_claim_payload("claim-repeat-1")
        )
        second_status, second_payload = service.submit_completion_claim(
            task["id"], _completion_claim_payload("claim-repeat-2")
        )

        self.assertEqual(first_status, 200)
        self.assertEqual(second_status, 200)
        self.assertEqual(gateway.create_calls, 1)
        self.assertEqual(gateway.get_pull_request_calls, 1)
        self.assertEqual(first_payload["task_envelope"]["reconciliation"]["last_pr_url"], gateway._created_pr.url)
        self.assertEqual(second_payload["task_envelope"]["reconciliation"]["last_pr_url"], gateway._created_pr.url)
        self.assertEqual(
            len([item for item in second_payload["task_envelope"]["artifacts"]["items"] if item["type"] == "pull_request"]),
            1,
        )

    def test_submit_completion_claim_escalates_when_multiple_valid_candidates_are_found(self) -> None:
        gateway = _FakeGitHubGateway(
            existing_branch_prs=(
                _pull_request(number=81),
                _pull_request(number=82),
            ),
        )
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_gateway(gateway),
        )
        task = _task_envelope(task_id="task-pr-reconcile-ambiguous")
        service.store.create_task(task)

        status, payload = service.submit_completion_claim(task["id"], _completion_claim_payload("claim-ambiguous"))

        self.assertEqual(status, 200)
        self.assertEqual(payload["action"], "reconciliation_failed")
        self.assertEqual(payload["task_envelope"]["status"], "in_review")
        self.assertEqual(gateway.create_calls, 0)
        self.assertTrue(payload["reconciliation_attempt"]["details"]["pull_request_lookup"]["ambiguous"])
        self.assertEqual(
            payload["reconciliation_attempt"]["details"]["final_decision"]["result"],
            "ambiguous_existing_candidates",
        )

    def test_submit_completion_claim_attaches_valid_pr_found_by_commit_association_when_head_sha_matches(self) -> None:
        task_id = "task-pr-reconcile-commit"
        claim_id = "claim-commit"
        attempt_id = f"{claim_id}:attempt"
        gateway = _FakeGitHubGateway(
            existing_commit_prs=(
                _pull_request(
                    number=83,
                    head_sha="8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                    body=_run_linkage_markers(task_id=task_id, attempt_id=attempt_id, claim_id=claim_id),
                ),
            ),
        )
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_gateway(gateway),
        )
        task = _task_envelope(task_id=task_id)
        service.store.create_task(task)

        status, payload = service.submit_completion_claim(task["id"], _completion_claim_payload(claim_id))

        self.assertEqual(status, 200)
        self.assertEqual(payload["task_envelope"]["status"], "completed")
        self.assertEqual(gateway.create_calls, 0)
        attempt = _latest_reconciliation_attempt(payload["task_envelope"])
        candidate = attempt["details"]["pull_request_candidates"][0]
        self.assertTrue(candidate["validation"]["accepted"])
        self.assertIn("head_sha_match", candidate["validation"]["matched_by"])
        self.assertIn("commit_association_match", candidate["validation"]["matched_by"])
        self.assertEqual(candidate["head"]["sha"], "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705")

    def test_submit_completion_claim_rejects_commit_association_candidate_without_run_linkage(self) -> None:
        gateway = _FakeGitHubGateway(
            existing_commit_prs=(
                _pull_request(
                    number=85,
                    head_sha="3333333333333333333333333333333333333333",
                    body="Task task-pr-reconcile-commit-run-linkage",
                ),
            ),
            created_pr=_pull_request(number=405),
        )
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_gateway(gateway),
        )
        task = _task_envelope(task_id="task-pr-reconcile-commit-run-linkage")
        service.store.create_task(task)

        status, payload = service.submit_completion_claim(task["id"], _completion_claim_payload("claim-commit-run-linkage"))

        self.assertEqual(status, 200)
        self.assertEqual(payload["task_envelope"]["status"], "completed")
        self.assertEqual(gateway.create_calls, 1)
        attempt = _latest_reconciliation_attempt(payload["task_envelope"])
        rejected_candidate = attempt["details"]["pull_request_candidates"][0]
        self.assertEqual(rejected_candidate["number"], 85)
        self.assertIn("commit_association_match", rejected_candidate["validation"]["matched_by"])
        self.assertIn(
            "commit_association_without_current_head_evidence",
            rejected_candidate["validation"]["reasons"],
        )
        self.assertNotIn("run_linkage_missing", rejected_candidate["validation"]["reasons"])
        self.assertEqual(
            rejected_candidate["validation"]["signals"]["linkage_policy"]["reasons"],
            [],
        )

    def test_submit_completion_claim_rejects_non_head_commit_association_candidate_even_with_run_linkage(self) -> None:
        task_id = "task-pr-reconcile-commit-run-linkage-valid"
        claim_id = "claim-commit-run-linkage-valid"
        attempt_id = f"{claim_id}:attempt"
        gateway = _FakeGitHubGateway(
            existing_commit_prs=(
                _pull_request(
                    number=86,
                    head_sha="3333333333333333333333333333333333333333",
                    body=_run_linkage_markers(task_id=task_id, attempt_id=attempt_id, claim_id=claim_id),
                ),
            ),
        )
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_gateway(gateway),
        )
        task = _task_envelope(task_id=task_id)
        service.store.create_task(task)

        status, payload = service.submit_completion_claim(task["id"], _completion_claim_payload(claim_id))

        self.assertEqual(status, 200)
        self.assertEqual(payload["task_envelope"]["status"], "completed")
        self.assertEqual(gateway.create_calls, 1)
        candidate = _latest_reconciliation_attempt(payload["task_envelope"])["details"]["pull_request_candidates"][0]
        self.assertFalse(candidate["validation"]["accepted"])
        self.assertIn("commit_association_match", candidate["validation"]["matched_by"])
        self.assertIn(
            "commit_association_without_current_head_evidence",
            candidate["validation"]["reasons"],
        )
        self.assertIn("attempt_linkage", candidate["validation"]["matched_by"])
        self.assertIn("completion_claim_linkage", candidate["validation"]["matched_by"])

    def test_submit_completion_claim_requires_run_linkage_when_multiple_attempts_exist(self) -> None:
        gateway = _FakeGitHubGateway(
            existing_branch_prs=(
                _pull_request(number=87, body="Task task-pr-reconcile-multiple-attempts"),
            ),
            created_pr=_pull_request(number=406),
        )
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_gateway(gateway),
        )
        task = _task_envelope(task_id="task-pr-reconcile-multiple-attempts")
        task = _record_execution_attempt(
            task,
            claim_id="historical-claim-1",
            attempt_id="historical-attempt-1",
            status="completed",
            recorded_at="2026-04-04T12:01:45Z",
        )
        service.store.create_task(task)

        status, payload = service.submit_completion_claim(task["id"], _completion_claim_payload("claim-multiple-attempts"))

        self.assertEqual(status, 200)
        self.assertEqual(payload["task_envelope"]["status"], "completed")
        self.assertEqual(gateway.create_calls, 1)
        attempt = _latest_reconciliation_attempt(payload["task_envelope"])
        rejected_candidate = attempt["details"]["pull_request_candidates"][0]
        self.assertIn("head_sha_match", rejected_candidate["validation"]["matched_by"])
        self.assertIn("run_linkage_missing", rejected_candidate["validation"]["reasons"])
        self.assertEqual(
            rejected_candidate["validation"]["signals"]["linkage_policy"]["reasons"],
            ["multiple_execution_attempts"],
        )
        self.assertEqual(attempt["details"]["final_decision"]["result"], "created_new")
        self.assertIsNotNone(gateway.last_create_pull_request)
        self.assertIn("Harness-Attempt-ID: claim-multiple-attempts:attempt", gateway.last_create_pull_request["body"])
        self.assertIn(
            "Harness-Completion-Claim-ID: claim-multiple-attempts",
            gateway.last_create_pull_request["body"],
        )

    def test_submit_completion_claim_requires_persisted_created_pr_to_validate_before_attachment(self) -> None:
        created_pr = _pull_request(number=407)
        gateway = _FakeGitHubGateway(created_pr=created_pr, persisted_created_pr=None)
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_gateway(gateway),
        )
        task = _task_envelope(task_id="task-pr-reconcile-create-readback-missing")
        service.store.create_task(task)

        status, payload = service.submit_completion_claim(task["id"], _completion_claim_payload("claim-create-readback-missing"))

        self.assertEqual(status, 200)
        self.assertEqual(payload["action"], "reconciliation_failed")
        self.assertEqual(payload["task_envelope"]["status"], "in_review")
        self.assertEqual(gateway.create_calls, 1)
        self.assertEqual(gateway.get_pull_request_calls, 1)
        attempt = payload["reconciliation_attempt"]
        self.assertEqual(attempt["details"]["final_decision"]["result"], "created_pull_request_revalidation_failed")
        self.assertEqual(
            attempt["details"]["final_decision"]["reason"],
            "created_pull_request_not_visible_after_create",
        )
        self.assertFalse(attempt["details"]["created_pull_request_revalidated"])

    def test_submit_completion_claim_rejects_persisted_created_pr_that_fails_validation(self) -> None:
        created_pr = _pull_request(number=408)
        persisted_created_pr = _pull_request(
            number=408,
            head_sha="1111111111111111111111111111111111111111",
        )
        gateway = _FakeGitHubGateway(created_pr=created_pr, persisted_created_pr=persisted_created_pr)
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_gateway(gateway),
        )
        task = _task_envelope(task_id="task-pr-reconcile-create-readback-invalid")
        service.store.create_task(task)

        status, payload = service.submit_completion_claim(task["id"], _completion_claim_payload("claim-create-readback-invalid"))

        self.assertEqual(status, 200)
        self.assertEqual(payload["action"], "reconciliation_failed")
        self.assertEqual(payload["task_envelope"]["status"], "in_review")
        self.assertEqual(gateway.create_calls, 1)
        self.assertEqual(gateway.get_pull_request_calls, 1)
        attempt = payload["reconciliation_attempt"]
        self.assertEqual(attempt["details"]["final_decision"]["result"], "created_pull_request_revalidation_failed")
        self.assertEqual(
            attempt["details"]["final_decision"]["reason"],
            "persisted_pull_request_failed_validation",
        )
        created_candidates = attempt["details"]["pull_request_candidates"]
        self.assertEqual(created_candidates[0]["lookup_sources"], ["created_response"])
        self.assertEqual(created_candidates[1]["lookup_sources"], ["created_persisted"])
        self.assertIn("head_sha_mismatch", created_candidates[1]["validation"]["reasons"])

    def test_submit_completion_claim_accepts_existing_candidate_with_matching_run_linkage_when_multiple_attempts_exist(self) -> None:
        task_id = "task-pr-reconcile-multiple-attempts-valid"
        claim_id = "claim-multiple-attempts-valid"
        attempt_id = f"{claim_id}:attempt"
        gateway = _FakeGitHubGateway(
            existing_branch_prs=(
                _pull_request(
                    number=88,
                    body=_run_linkage_markers(task_id=task_id, attempt_id=attempt_id, claim_id=claim_id),
                ),
            ),
        )
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_gateway(gateway),
        )
        task = _task_envelope(task_id=task_id)
        task = _record_execution_attempt(
            task,
            claim_id="historical-claim-1",
            attempt_id="historical-attempt-1",
            status="completed",
            recorded_at="2026-04-04T12:01:45Z",
        )
        service.store.create_task(task)

        status, payload = service.submit_completion_claim(task["id"], _completion_claim_payload(claim_id))

        self.assertEqual(status, 200)
        self.assertEqual(payload["task_envelope"]["status"], "completed")
        self.assertEqual(gateway.create_calls, 0)
        candidate = _latest_reconciliation_attempt(payload["task_envelope"])["details"]["pull_request_candidates"][0]
        self.assertTrue(candidate["validation"]["accepted"])
        self.assertIn("head_sha_match", candidate["validation"]["matched_by"])
        self.assertIn("attempt_linkage", candidate["validation"]["matched_by"])
        self.assertIn("completion_claim_linkage", candidate["validation"]["matched_by"])

    def test_submit_completion_claim_moves_task_to_in_review_when_reconciliation_fails(self) -> None:
        gateway = _FakeGitHubGateway(branch_exists=False)
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_gateway(gateway),
        )
        task = _task_envelope(task_id="task-pr-reconcile-fail")
        service.store.create_task(task)

        status, payload = service.submit_completion_claim(task["id"], _completion_claim_payload("claim-fail"))
        stored_status, stored_payload = service.get_task(task["id"])

        self.assertEqual(status, 200)
        self.assertEqual(payload["action"], "reconciliation_terminal_failed")
        self.assertEqual(payload["task_envelope"]["status"], "failed")
        self.assertFalse(payload["requires_review"])
        self.assertEqual(payload["task_envelope"]["reconciliation"]["status"], "failed")
        self.assertEqual(payload["task_envelope"]["reconciliation"]["active_failure_type"], "missing_pr_after_execution")
        self.assertEqual(payload["task_envelope"]["status_history"][-2]["to_status"], "reconciling")
        self.assertEqual(payload["task_envelope"]["status_history"][-1]["to_status"], "failed")
        self.assertEqual(stored_status, 200)
        self.assertEqual(stored_payload["task"]["status"], "failed")

    def test_submit_completion_claim_moves_task_to_blocked_for_retryable_provider_failure(self) -> None:
        gateway = _FakeGitHubGateway(
            branch_exists_error=RetryableReconciliationRuntimeError(
                "GitHub API request failed for /repos/KnoxAnalytics/HARNESS-DRYRUN/branches/codex%2Fe2e-test: HTTP 502 bad gateway"
            )
        )
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_gateway(gateway),
        )
        task = _task_envelope(task_id="task-pr-reconcile-provider-blocked")
        service.store.create_task(task)

        status, payload = service.submit_completion_claim(task["id"], _completion_claim_payload("claim-provider-blocked"))
        stored_status, stored_payload = service.get_task(task["id"])

        self.assertEqual(status, 200)
        self.assertEqual(payload["action"], "reconciliation_blocked")
        self.assertEqual(payload["task_envelope"]["status"], "blocked")
        self.assertFalse(payload["requires_review"])
        self.assertEqual(payload["target_status"], "blocked")
        self.assertEqual(payload["reconciliation_attempt"]["details"]["error_disposition"], "blocked_retryable")
        self.assertEqual(payload["task_envelope"]["status_history"][-2]["to_status"], "reconciling")
        self.assertEqual(payload["task_envelope"]["status_history"][-1]["to_status"], "blocked")
        self.assertEqual(stored_status, 200)
        self.assertEqual(stored_payload["task"]["status"], "blocked")

    def test_submit_completion_claim_rejects_conflicting_code_context_sources(self) -> None:
        gateway = _FakeGitHubGateway()
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_gateway(gateway),
        )
        task = _task_envelope(task_id="task-pr-reconcile-context-conflict")
        service.store.create_task(task)

        payload = _completion_claim_payload("claim-context-conflict")
        payload["request"]["external_facts"]["expected_code_context"]["branch_name"] = "codex/conflicting-branch"
        payload["request"]["external_facts"]["github_facts"]["branch"]["name"] = "codex/conflicting-branch"
        payload["request"]["external_facts"]["github_facts"]["branch"]["head_commit_sha"] = (
            "1111111111111111111111111111111111111111"
        )
        payload["request"]["external_facts"]["github_facts"]["commit"]["sha"] = (
            "1111111111111111111111111111111111111111"
        )

        status, response = service.submit_completion_claim(task["id"], payload)
        stored_status, stored_payload = service.get_task(task["id"])

        self.assertEqual(status, 200)
        self.assertEqual(response["action"], "reconciliation_failed")
        self.assertEqual(response["task_envelope"]["status"], "in_review")
        self.assertEqual(gateway.create_calls, 0)
        self.assertEqual(
            response["reconciliation_attempt"]["details"]["final_decision"]["result"],
            "context_resolution_failed",
        )
        conflict_fields = {
            item["field"]
            for item in response["reconciliation_attempt"]["details"]["context_resolution"]["conflicts"]
        }
        self.assertIn("branch_name", conflict_fields)
        self.assertIn("commit_sha", conflict_fields)
        self.assertIn("external_facts", response["reconciliation_attempt"]["details"]["context_resolution"]["sources"])
        self.assertIn("artifacts", response["reconciliation_attempt"]["details"]["context_resolution"]["sources"])
        self.assertEqual(response["task_envelope"]["status_history"][-1]["to_status"], "in_review")
        self.assertEqual(stored_status, 200)
        self.assertEqual(stored_payload["task"]["status"], "in_review")

    def test_submit_completion_claim_attaches_missing_commit_artifact_when_verified_pr_proof_exists(self) -> None:
        gateway = _FakeGitHubGateway()
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_gateway(gateway),
        )
        task = _without_commit_artifact(_with_pull_request_artifact(_task_envelope(task_id="task-missing-commit-reconcile"), number=77))
        service.store.create_task(task)

        status, payload = service.submit_completion_claim(task["id"], _completion_claim_payload("claim-missing-commit"))

        self.assertEqual(status, 200)
        self.assertEqual(payload["task_envelope"]["status"], "completed")
        attempt = _latest_reconciliation_attempt(payload["task_envelope"])
        self.assertEqual(attempt["failure_type"], "missing_commit_after_execution")
        self.assertEqual(attempt["details"]["final_decision"]["result"], "attached_commit_artifact")
        self.assertTrue(attempt["details"]["created_commit_artifact"])
        commit_artifacts = [
            artifact
            for artifact in payload["task_envelope"]["artifacts"]["items"]
            if isinstance(artifact, dict) and artifact.get("type") == "commit"
        ]
        self.assertEqual(len(commit_artifacts), 1)
        self.assertEqual(
            commit_artifacts[0]["location"],
            "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/commit/8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
        )
        self.assertIn(commit_artifacts[0]["id"], payload["task_envelope"]["artifacts"]["completion_evidence"]["validated_artifact_ids"])

    def test_submit_completion_claim_terminally_fails_missing_commit_reconciliation_when_branch_is_missing(self) -> None:
        gateway = _FakeGitHubGateway(branch_exists=False)
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_gateway(gateway),
        )
        task = _without_commit_artifact(
            _with_pull_request_artifact(_task_envelope(task_id="task-missing-commit-branch-missing"), number=79)
        )
        service.store.create_task(task)

        status, payload = service.submit_completion_claim(task["id"], _completion_claim_payload("claim-missing-commit-branch"))

        self.assertEqual(status, 200)
        self.assertEqual(payload["action"], "reconciliation_terminal_failed")
        self.assertEqual(payload["task_envelope"]["status"], "failed")
        self.assertFalse(payload["requires_review"])
        attempt = _latest_reconciliation_attempt(payload["task_envelope"])
        self.assertEqual(attempt["failure_type"], "missing_commit_after_execution")
        self.assertEqual(attempt["details"]["error_disposition"], "terminal_failed")
        self.assertEqual(attempt["details"]["final_decision"]["result"], "terminal_failed")


    def test_submit_completion_claim_reconciles_against_explicitly_claimed_attempt_not_latest_attempt(self) -> None:
        gateway = _FakeGitHubGateway(
            existing_branch_prs=(
                _pull_request(
                    number=84,
                    body=_run_linkage_markers(
                        task_id="task-pr-reconcile-explicit-attempt",
                        attempt_id="attempt-success-1",
                        claim_id="historical-claim-success",
                    ),
                ),
            )
        )
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_gateway(gateway),
        )
        task = _task_envelope(task_id="task-pr-reconcile-explicit-attempt")
        task = _record_execution_attempt(
            task,
            claim_id="historical-claim-success",
            attempt_id="attempt-success-1",
            status="completed",
            recorded_at="2026-04-04T12:01:45Z",
        )
        task = _record_execution_attempt(
            task,
            claim_id="historical-claim-latest",
            attempt_id="attempt-latest-2",
            status="failed",
            recorded_at="2026-04-04T12:01:55Z",
        )
        service.store.create_task(task)

        payload = _completion_claim_payload("claim-existing-attempt")
        del payload["request"]["execution_attempt"]
        payload["request"]["completion_claim"]["metadata"]["attempt_id"] = "attempt-success-1"

        status, response = service.submit_completion_claim(task["id"], payload)

        self.assertEqual(status, 200)
        self.assertEqual(response["task_envelope"]["status"], "completed")
        self.assertEqual(gateway.create_calls, 0)
        attempt = _latest_reconciliation_attempt(response["task_envelope"])
        self.assertEqual(attempt["details"]["final_decision"]["result"], "attached_existing")
        execution_attempts = response["task_envelope"]["observability"]["execution_metadata"]["execution_attempts"]
        linked_attempt = next(item for item in execution_attempts if item["attempt_id"] == "attempt-success-1")
        untouched_attempt = next(item for item in execution_attempts if item["attempt_id"] == "attempt-latest-2")
        self.assertEqual(linked_attempt["reevaluation"]["evaluation_id"], response["evaluation_record"]["evaluation_id"])
        self.assertEqual(untouched_attempt["reevaluation"], {})

    def test_claimed_attempt_must_resolve_before_missing_pr_reconciliation_can_run(self) -> None:
        task = _task_envelope(task_id="task-pr-reconcile-missing-attempt")
        task = _record_execution_attempt(
            task,
            claim_id="historical-claim-success",
            attempt_id="attempt-success-1",
            status="completed",
            recorded_at="2026-04-04T12:01:45Z",
        )

        payload = _completion_claim_payload("claim-missing-attempt")
        del payload["request"]["execution_attempt"]
        payload["request"]["completion_claim"]["metadata"]["attempt_id"] = "attempt-does-not-exist"

        request = parse_completion_claim_request(task, payload)

        self.assertFalse(_requires_missing_pr_reconciliation(request))


if __name__ == "__main__":
    unittest.main()
