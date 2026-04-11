from __future__ import annotations

import io
import unittest
from unittest.mock import patch
from urllib import error

from modules.intake import create_task_envelope
from modules.reconciliation_runtime import (
    GitHubRestPullRequestGateway,
    ReconciliationRuntimeError,
    RetryableReconciliationRuntimeError,
    _context_from_artifacts,
    _current_execution_attempt,
    _context_from_execution_attempt,
    _resolved_code_context,
)


class GitHubRestPullRequestGatewayTests(unittest.TestCase):
    def test_branch_exists_raises_retryable_error_on_http_500(self) -> None:
        gateway = GitHubRestPullRequestGateway(token="test-token")
        http_error = error.HTTPError(
            url="https://api.github.com/repos/KnoxAnalytics/HARNESS-DRYRUN/branches/codex%2Fe2e-test",
            code=500,
            msg="Server Error",
            hdrs=None,
            fp=io.BytesIO(b'{"message":"bad gateway"}'),
        )

        with patch("modules.reconciliation_runtime.request.urlopen", side_effect=http_error):
            with self.assertRaises(RetryableReconciliationRuntimeError) as captured:
                gateway.branch_exists(
                    owner="KnoxAnalytics",
                    repo="HARNESS-DRYRUN",
                    branch_name="codex/e2e-test",
                )

        self.assertIn("HTTP 500", str(captured.exception))

    def test_branch_exists_raises_retryable_error_on_transport_failure(self) -> None:
        gateway = GitHubRestPullRequestGateway(token="test-token")

        with patch(
            "modules.reconciliation_runtime.request.urlopen",
            side_effect=error.URLError("timed out"),
        ):
            with self.assertRaises(RetryableReconciliationRuntimeError) as captured:
                gateway.branch_exists(
                    owner="KnoxAnalytics",
                    repo="HARNESS-DRYRUN",
                    branch_name="codex/e2e-test",
                )

        self.assertIn("timed out", str(captured.exception))

    def test_branch_head_commit_sha_reads_branch_head_from_github(self) -> None:
        gateway = GitHubRestPullRequestGateway(token="test-token")
        with patch.object(
            gateway,
            "_request_json",
            return_value={"commit": {"sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705"}},
        ):
            sha = gateway.branch_head_commit_sha(
                owner="KnoxAnalytics",
                repo="HARNESS-DRYRUN",
                branch_name="codex/e2e-test",
            )

        self.assertEqual(sha, "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705")


class ResolveCodeContextTests(unittest.TestCase):
    def test_ignores_non_code_artifacts_when_deriving_context_from_locations(self) -> None:
        task = create_task_envelope(
            {
                "id": "task-non-code-artifact-context-1",
                "title": "Ignore non-code artifact context",
                "description": "Non-code artifacts must not seed reconciliation code context.",
                "origin": {
                    "source_system": "openclaw",
                    "source_type": "ingress_request",
                    "source_id": "req-non-code-artifact-context-1",
                },
                "acceptance_criteria": [
                    {
                        "id": "ac-1",
                        "description": "Only code execution artifacts contribute to reconciliation code context.",
                        "required": True,
                    }
                ],
            },
            now="2026-04-07T09:00:00Z",
        )
        task["artifacts"]["items"] = [
            {
                "id": "artifact-note-1",
                "type": "review_note",
                "location": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/tree/codex/not-real",
                "repository": {
                    "host": "github.com",
                    "owner": "KnoxAnalytics",
                    "name": "HARNESS-DRYRUN",
                },
            }
        ]

        context = _context_from_artifacts(task)

        self.assertIsNone(context)

    def test_resolves_branch_context_even_when_commit_sha_is_missing(self) -> None:
        task = create_task_envelope(
            {
                "id": "task-context-missing-commit-1",
                "title": "Resolve branch context without commit",
                "description": "Exercise missing commit fallback readiness.",
                "origin": {
                    "source_system": "openclaw",
                    "source_type": "ingress_request",
                    "source_id": "req-context-missing-commit-1",
                },
                "acceptance_criteria": [
                    {
                        "id": "ac-1",
                        "description": "Harness resolves branch context before commit fallback.",
                        "required": True,
                    }
                ],
            },
            now="2026-04-06T09:00:00Z",
        )
        external_facts = {
            "expected_code_context": {
                "repository_host": "github.com",
                "repository_owner": "KnoxAnalytics",
                "repository_name": "HARNESS-DRYRUN",
                "branch_name": "codex/e2e-test",
                "base_branch": "main",
            },
            "github_facts": {
                "repository": {
                    "host": "github.com",
                    "owner": "KnoxAnalytics",
                    "name": "HARNESS-DRYRUN",
                },
                "branch": {
                    "name": "codex/e2e-test",
                    "base_branch": "main",
                    "head_commit_sha": None,
                },
                "commit": {
                    "sha": None,
                },
            },
        }

        context, sources, selected = _resolved_code_context(task, external_facts=external_facts)

        self.assertEqual(context.repository_owner, "KnoxAnalytics")
        self.assertEqual(context.repository_name, "HARNESS-DRYRUN")
        self.assertEqual(context.branch_name, "codex/e2e-test")
        self.assertEqual(context.commit_sha, "")
        self.assertEqual(selected, "external_facts")
        self.assertIn("external_facts", sources)

    def test_does_not_backfill_commit_from_artifacts_when_non_artifact_context_is_missing_commit(self) -> None:
        task = create_task_envelope(
            {
                "id": "task-context-artifact-commit-backfill-1",
                "title": "Avoid artifact-only commit backfill",
                "description": "Artifact commits must not silently backfill execution context from another source.",
                "origin": {
                    "source_system": "openclaw",
                    "source_type": "ingress_request",
                    "source_id": "req-context-artifact-commit-backfill-1",
                },
                "acceptance_criteria": [
                    {
                        "id": "ac-1",
                        "description": "Harness prefers missing commit identity over stale artifact backfill.",
                        "required": True,
                    }
                ],
            },
            now="2026-04-06T09:00:00Z",
        )
        task["artifacts"]["items"] = [
            {
                "id": "artifact-commit-1",
                "type": "commit",
                "location": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/commit/8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
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
            }
        ]
        external_facts = {
            "expected_code_context": {
                "repository_host": "github.com",
                "repository_owner": "KnoxAnalytics",
                "repository_name": "HARNESS-DRYRUN",
                "branch_name": "codex/e2e-test",
                "base_branch": "main",
            },
            "github_facts": {
                "repository": {
                    "host": "github.com",
                    "owner": "KnoxAnalytics",
                    "name": "HARNESS-DRYRUN",
                },
                "branch": {
                    "name": "codex/e2e-test",
                    "base_branch": "main",
                    "head_commit_sha": None,
                },
                "commit": {
                    "sha": None,
                },
            },
        }

        context, _, selected = _resolved_code_context(task, external_facts=external_facts)

        self.assertEqual(selected, "merged")
        self.assertEqual(context.branch_name, "codex/e2e-test")
        self.assertEqual(context.commit_sha, "")

    def test_rejects_conflicting_sources_instead_of_picking_first_available(self) -> None:
        task = create_task_envelope(
            {
                "id": "task-context-conflict-1",
                "title": "Reject conflicting reconciliation context",
                "description": "Exercise conflict detection across reconciliation context sources.",
                "origin": {
                    "source_system": "openclaw",
                    "source_type": "ingress_request",
                    "source_id": "req-context-conflict-1",
                },
                "acceptance_criteria": [
                    {
                        "id": "ac-1",
                        "description": "Harness rejects conflicting reconciliation context.",
                        "required": True,
                    }
                ],
            },
            now="2026-04-05T10:00:00Z",
        )
        task["artifacts"]["items"] = [
            {
                "id": "artifact-commit-1",
                "type": "commit",
                "location": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/commit/8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
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
            }
        ]
        external_facts = {
            "expected_code_context": {
                "repository_host": "github.com",
                "repository_owner": "KnoxAnalytics",
                "repository_name": "HARNESS-DRYRUN",
                "branch_name": "codex/conflicting-branch",
                "base_branch": "main",
            },
            "github_facts": {
                "repository": {
                    "host": "github.com",
                    "owner": "KnoxAnalytics",
                    "name": "HARNESS-DRYRUN",
                },
                "branch": {
                    "name": "codex/conflicting-branch",
                    "base_branch": "main",
                    "head_commit_sha": "1111111111111111111111111111111111111111",
                },
                "commit": {
                    "sha": "1111111111111111111111111111111111111111",
                },
            },
        }

        with self.assertRaises(ReconciliationRuntimeError) as captured:
            _resolved_code_context(task, external_facts=external_facts)

        self.assertIn("Conflicting reconciliation code context across sources", str(captured.exception))

    def test_does_not_fill_execution_attempt_commit_from_external_facts(self) -> None:
        task = create_task_envelope(
            {
                "id": "task-context-execution-attempt-commit-fill-1",
                "title": "Do not fill execution-attempt commit from external facts",
                "description": "Execution-attempt branch context should not inherit commit identity from another source.",
                "origin": {
                    "source_system": "openclaw",
                    "source_type": "ingress_request",
                    "source_id": "req-context-execution-attempt-commit-fill-1",
                },
                "acceptance_criteria": [
                    {
                        "id": "ac-1",
                        "description": "Harness keeps commit identity empty when execution metadata did not prove it.",
                        "required": True,
                    }
                ],
            },
            now="2026-04-07T09:00:00Z",
        )
        task["observability"]["execution_metadata"]["execution_attempts"] = [
            {
                "attempt_id": "attempt-1",
                "artifact_references": [
                    {
                        "reference_id": "attempt-1-ref-1",
                        "artifact_type": "branch",
                        "location": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/tree/codex/e2e-test",
                        "metadata": {
                            "repository_host": "github.com",
                            "repository_owner": "KnoxAnalytics",
                            "repository_name": "HARNESS-DRYRUN",
                            "branch_name": "codex/e2e-test",
                            "base_branch": "main",
                            "commit_sha": None,
                        },
                    }
                ],
            }
        ]
        external_facts = {
            "expected_code_context": {
                "repository_host": "github.com",
                "repository_owner": "KnoxAnalytics",
                "repository_name": "HARNESS-DRYRUN",
                "branch_name": "codex/e2e-test",
                "base_branch": "main",
            },
            "github_facts": {
                "repository": {
                    "host": "github.com",
                    "owner": "KnoxAnalytics",
                    "name": "HARNESS-DRYRUN",
                },
                "branch": {
                    "name": "codex/e2e-test",
                    "base_branch": "main",
                    "head_commit_sha": "1111111111111111111111111111111111111111",
                },
                "commit": {
                    "sha": "1111111111111111111111111111111111111111",
                },
            },
        }

        execution_context = _context_from_execution_attempt(task)
        context, _, selected = _resolved_code_context(task, external_facts=external_facts)

        self.assertIsNotNone(execution_context)
        self.assertEqual(execution_context.commit_sha, "")
        self.assertEqual(selected, "merged")
        self.assertEqual(context.branch_name, "codex/e2e-test")
        self.assertEqual(context.commit_sha, "")

    def test_allows_execution_attempt_commit_to_complete_external_facts_branch_context(self) -> None:
        task = create_task_envelope(
            {
                "id": "task-context-execution-attempt-commit-authority-1",
                "title": "Allow execution-attempt commit authority",
                "description": "Execution-attempt commit identity can complete matching branch context from external facts.",
                "origin": {
                    "source_system": "openclaw",
                    "source_type": "ingress_request",
                    "source_id": "req-context-execution-attempt-commit-authority-1",
                },
                "acceptance_criteria": [
                    {
                        "id": "ac-1",
                        "description": "Harness can use execution-attempt commit proof for the current branch.",
                        "required": True,
                    }
                ],
            },
            now="2026-04-07T09:00:00Z",
        )
        task["observability"]["execution_metadata"]["execution_attempts"] = [
            {
                "attempt_id": "attempt-1",
                "artifact_references": [
                    {
                        "reference_id": "attempt-1-ref-1",
                        "artifact_type": "commit",
                        "location": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/commit/8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                        "metadata": {
                            "repository_host": "github.com",
                            "repository_owner": "KnoxAnalytics",
                            "repository_name": "HARNESS-DRYRUN",
                            "branch_name": "codex/e2e-test",
                            "base_branch": "main",
                            "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                        },
                    }
                ],
            }
        ]
        external_facts = {
            "expected_code_context": {
                "repository_host": "github.com",
                "repository_owner": "KnoxAnalytics",
                "repository_name": "HARNESS-DRYRUN",
                "branch_name": "codex/e2e-test",
                "base_branch": "main",
            },
            "github_facts": {
                "repository": {
                    "host": "github.com",
                    "owner": "KnoxAnalytics",
                    "name": "HARNESS-DRYRUN",
                },
                "branch": {
                    "name": "codex/e2e-test",
                    "base_branch": "main",
                    "head_commit_sha": None,
                },
                "commit": {
                    "sha": None,
                },
            },
        }

        context, _, selected = _resolved_code_context(task, external_facts=external_facts)

        self.assertEqual(selected, "merged")
        self.assertEqual(context.branch_name, "codex/e2e-test")
        self.assertEqual(context.commit_sha, "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705")

    def test_current_execution_attempt_uses_newest_recorded_attempt_when_attempts_are_out_of_order(self) -> None:
        task = create_task_envelope(
            {
                "id": "task-current-execution-attempt-ordering-1",
                "title": "Current execution attempt follows recorded_at",
                "description": "Current attempt binding should not trust raw append order.",
                "origin": {
                    "source_system": "openclaw",
                    "source_type": "ingress_request",
                    "source_id": "req-current-execution-attempt-ordering-1",
                },
                "acceptance_criteria": [
                    {
                        "id": "ac-1",
                        "description": "Current attempt falls back to the newest recorded attempt.",
                        "required": True,
                    }
                ],
            },
            now="2026-04-11T09:00:00Z",
        )
        execution_metadata = task["observability"]["execution_metadata"]
        execution_metadata["advisory_completion_claims"] = [
            {
                "claim_id": "claim-newer",
                "reported_at": "2026-04-11T09:10:00Z",
                "reported_by": "codex",
                "reason": "newer historical claim",
                "metadata": {"attempt_id": "attempt-newer"},
            },
            {
                "claim_id": "claim-current",
                "reported_at": "2026-04-11T09:15:00Z",
                "reported_by": "codex",
                "reason": "current completion claim without explicit attempt binding",
                "metadata": {},
            },
        ]
        execution_metadata["execution_attempts"] = [
            {
                "attempt_id": "attempt-newer",
                "recorded_at": "2026-04-11T09:10:05Z",
                "status": "completed",
                "reported_by": "codex",
                "completion_claim_id": "claim-newer",
                "artifact_references": [],
                "metadata": {"executor_run_id": "run-attempt-newer"},
                "reevaluation": {},
            },
            {
                "attempt_id": "attempt-older",
                "recorded_at": "2026-04-11T09:05:05Z",
                "status": "failed",
                "reported_by": "codex",
                "completion_claim_id": "claim-older",
                "artifact_references": [],
                "metadata": {"executor_run_id": "run-attempt-older"},
                "reevaluation": {},
            },
        ]

        attempt = _current_execution_attempt(task)

        self.assertIsNotNone(attempt)
        self.assertEqual(attempt["attempt_id"], "attempt-newer")

    def test_execution_attempt_context_uses_newest_recorded_attempt_when_attempts_are_out_of_order(self) -> None:
        task = create_task_envelope(
            {
                "id": "task-context-execution-attempt-ordering-1",
                "title": "Execution attempt context follows recorded_at",
                "description": "Reconciliation context should bind to the newest recorded execution attempt.",
                "origin": {
                    "source_system": "openclaw",
                    "source_type": "ingress_request",
                    "source_id": "req-context-execution-attempt-ordering-1",
                },
                "acceptance_criteria": [
                    {
                        "id": "ac-1",
                        "description": "Execution-attempt context comes from the newest recorded attempt.",
                        "required": True,
                    }
                ],
            },
            now="2026-04-11T09:00:00Z",
        )
        task["observability"]["execution_metadata"]["execution_attempts"] = [
            {
                "attempt_id": "attempt-newer",
                "recorded_at": "2026-04-11T09:10:05Z",
                "artifact_references": [
                    {
                        "reference_id": "attempt-newer-ref-1",
                        "artifact_type": "branch",
                        "location": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/tree/codex/e2e-test-newer",
                        "metadata": {
                            "repository_host": "github.com",
                            "repository_owner": "KnoxAnalytics",
                            "repository_name": "HARNESS-DRYRUN",
                            "branch_name": "codex/e2e-test-newer",
                            "base_branch": "main",
                            "commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                        },
                    }
                ],
            },
            {
                "attempt_id": "attempt-older",
                "recorded_at": "2026-04-11T09:05:05Z",
                "artifact_references": [
                    {
                        "reference_id": "attempt-older-ref-1",
                        "artifact_type": "branch",
                        "location": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/tree/codex/e2e-test-older",
                        "metadata": {
                            "repository_host": "github.com",
                            "repository_owner": "KnoxAnalytics",
                            "repository_name": "HARNESS-DRYRUN",
                            "branch_name": "codex/e2e-test-older",
                            "base_branch": "main",
                            "commit_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                        },
                    }
                ],
            },
        ]

        context = _context_from_execution_attempt(task)

        self.assertIsNotNone(context)
        self.assertEqual(context.branch_name, "codex/e2e-test-newer")
        self.assertEqual(context.commit_sha, "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")

    def test_ignores_support_artifact_references_in_execution_attempt_context(self) -> None:
        task = create_task_envelope(
            {
                "id": "task-context-execution-attempt-support-reference-1",
                "title": "Ignore support artifact references",
                "description": "Support artifact references must not seed reconciliation execution context.",
                "origin": {
                    "source_system": "openclaw",
                    "source_type": "ingress_request",
                    "source_id": "req-context-execution-attempt-support-reference-1",
                },
                "acceptance_criteria": [
                    {
                        "id": "ac-1",
                        "description": "Only code execution artifact references contribute to execution-attempt context.",
                        "required": True,
                    }
                ],
            },
            now="2026-04-07T09:00:00Z",
        )
        task["observability"]["execution_metadata"]["execution_attempts"] = [
            {
                "attempt_id": "attempt-1",
                "artifact_references": [
                    {
                        "reference_id": "attempt-1-ref-1",
                        "artifact_type": "review_note",
                        "location": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/tree/codex/not-real",
                        "metadata": {
                            "repository_host": "github.com",
                            "repository_owner": "KnoxAnalytics",
                            "repository_name": "HARNESS-DRYRUN",
                            "branch_name": "codex/not-real",
                            "base_branch": "main",
                            "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                        },
                    }
                ],
            }
        ]

        context = _context_from_execution_attempt(task)

        self.assertIsNone(context)
