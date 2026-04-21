from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from modules.adapters.codex_cloud import CodexCloudExecutorAdapter
from modules.adapters.executor_adapter import ExecutorDispatchOutput, StubExecutorAdapter
from modules.api import (
    HarnessApiService,
    _execution_attempt_for_completion_claim,
    _latest_advisory_completion_claim,
    _latest_execution_attempt,
    build_parser,
    evaluate_http_payload,
    run_server,
)
from modules.contracts.execution_advisory import (
    AdvisoryCompletionClaim,
    ArtifactReference,
    ExecutionEvent,
    ExecutionEventType,
    ExecutionProvenance,
)
from modules.reconciliation_runtime import (
    GitHubPullRequestRecord,
    ReconciliationFailureType,
    build_default_reconciliation_registry,
)
from modules.contracts.task_envelope_review import (
    ReviewOutcome,
    ReviewRequest,
    ReviewTrigger,
    ReviewerIdentity,
    resolve_review_request,
)
from modules.demo_cases import build_demo_request
from modules.intake import create_task_envelope
from modules.store import FileBackedHarnessStore, PostgresHarnessStore, SQLiteHarnessStore
from tests.e2e.scenario_builders import build_review_decision_from_request


POSTGRES_TEST_DATABASE_URL = os.environ.get("HARNESS_TEST_DATABASE_URL")


class _FakeCursor:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows
        self._index = 0

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def execute(self, query: str, params: tuple[object, ...]) -> None:
        del query, params

    def fetchone(self) -> tuple[object, ...] | None:
        if self._index >= len(self._rows):
            return None
        row = self._rows[self._index]
        self._index += 1
        return row


class LatestExecutionAttemptTests(unittest.TestCase):
    def test_latest_execution_attempt_uses_newest_recorded_attempt_when_out_of_order(self) -> None:
        task = {
            "observability": {
                "execution_metadata": {
                    "execution_attempts": [
                        {
                            "attempt_id": "attempt-newer",
                            "recorded_at": "2026-04-11T09:10:05Z",
                            "status": "completed",
                        },
                        {
                            "attempt_id": "attempt-older",
                            "recorded_at": "2026-04-11T09:05:05Z",
                            "status": "failed",
                        },
                    ]
                }
            }
        }

        attempt = _latest_execution_attempt(task)

        self.assertIsNotNone(attempt)
        self.assertEqual(attempt["attempt_id"], "attempt-newer")


class LatestAdvisoryCompletionClaimTests(unittest.TestCase):
    def test_latest_advisory_completion_claim_uses_newest_reported_at_when_out_of_order(self) -> None:
        task = {
            "observability": {
                "execution_metadata": {
                    "advisory_completion_claims": [
                        {
                            "claim_id": "claim-newer",
                            "reported_at": "2026-04-11T09:10:05Z",
                            "metadata": {"attempt_id": "attempt-newer"},
                        },
                        {
                            "claim_id": "claim-older",
                            "reported_at": "2026-04-11T09:05:05Z",
                            "metadata": {"attempt_id": "attempt-older"},
                        },
                    ]
                }
            }
        }

        claim = _latest_advisory_completion_claim(task)

        self.assertIsNotNone(claim)
        self.assertEqual(claim["claim_id"], "claim-newer")

    def test_execution_attempt_for_completion_claim_uses_latest_claim_by_reported_at(self) -> None:
        task = {
            "observability": {
                "execution_metadata": {
                    "advisory_completion_claims": [
                        {
                            "claim_id": "claim-newer",
                            "reported_at": "2026-04-11T09:10:05Z",
                            "metadata": {"attempt_id": "attempt-newer"},
                        },
                        {
                            "claim_id": "claim-older",
                            "reported_at": "2026-04-11T09:05:05Z",
                            "metadata": {"attempt_id": "attempt-older"},
                        },
                    ],
                    "execution_attempts": [
                        {
                            "attempt_id": "attempt-newer",
                            "completion_claim_id": "claim-newer",
                            "recorded_at": "2026-04-11T09:10:05Z",
                            "status": "completed",
                        },
                        {
                            "attempt_id": "attempt-older",
                            "completion_claim_id": "claim-older",
                            "recorded_at": "2026-04-11T09:05:05Z",
                            "status": "failed",
                        },
                    ],
                }
            }
        }

        attempt = _execution_attempt_for_completion_claim(task)

        self.assertIsNotNone(attempt)
        self.assertEqual(attempt["attempt_id"], "attempt-newer")


class _FakeConnection:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(list(self._rows))


class _NoCreatePullRequestGateway:
    """Deterministic gateway stub that preserves missing-PR failure behavior."""

    def branch_exists(self, *, owner: str, repo: str, branch_name: str) -> bool:
        del owner, repo, branch_name
        return True

    def branch_head_commit_sha(self, *, owner: str, repo: str, branch_name: str) -> str | None:
        del owner, repo, branch_name
        return "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705"

    def commit_exists(self, *, owner: str, repo: str, commit_sha: str) -> bool:
        del owner, repo, commit_sha
        return True

    def default_branch(self, *, owner: str, repo: str) -> str | None:
        del owner, repo
        return "main"

    def find_pull_requests_by_branch(self, *, owner: str, repo: str, branch_name: str) -> tuple:
        del owner, repo, branch_name
        return ()

    def find_pull_requests_by_commit(self, *, owner: str, repo: str, commit_sha: str) -> tuple:
        del owner, repo, commit_sha
        return ()

    def create_pull_request(self, *, owner: str, repo: str, title: str, body: str, head: str, base: str):
        del owner, repo, title, body, head, base
        raise RuntimeError("PR creation intentionally disabled for deterministic tests")

    def get_pull_request(self, *, owner: str, repo: str, number: int):
        del owner, repo, number
        return None


class _CurrentRunPullRequestGateway(_NoCreatePullRequestGateway):
    """Deterministic gateway stub that exposes one valid current-run PR."""

    def _record(self) -> GitHubPullRequestRecord:
        return GitHubPullRequestRecord(
            number=2,
            url="https://github.com/KnoxAnalytics/HARNESS-DRYRUN/pull/2",
            state="open",
            review_state="approved",
            merged=False,
            repository_owner="KnoxAnalytics",
            repository_name="HARNESS-DRYRUN",
            head_branch="codex/e2e-test",
            head_sha="8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
            base_branch="main",
            title="Harness demo case",
            body="Harness-Task-ID: task-http-happy-overlay-1",
        )

    def find_pull_requests_by_branch(self, *, owner: str, repo: str, branch_name: str) -> tuple:
        del owner, repo
        if branch_name == "codex/e2e-test":
            return (self._record(),)
        return ()

    def find_pull_requests_by_commit(self, *, owner: str, repo: str, commit_sha: str) -> tuple:
        del owner, repo
        if commit_sha == "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705":
            return (self._record(),)
        return ()

    def get_pull_request(self, *, owner: str, repo: str, number: int):
        del owner, repo
        if number == 2:
            return self._record()
        return None


class _TransientMissingBranchGateway(_NoCreatePullRequestGateway):
    """Gateway stub that simulates a transient branch visibility miss."""

    def branch_exists(self, *, owner: str, repo: str, branch_name: str) -> bool:
        del owner, repo, branch_name
        return False


class _OutOfOrderDispatchAdapter:
    """Adapter stub that returns valid events in non-chronological sequence."""

    def dispatch(self, dispatch_input) -> ExecutorDispatchOutput:
        provenance = ExecutionProvenance(
            source_system="stub-executor",
            source_type="adapter",
            source_id=f"{dispatch_input.attempt_id}:dispatch",
            captured_by="stub-executor",
        )
        artifact_reference = ArtifactReference(
            artifact_type="execution_log",
            reference_id=f"{dispatch_input.attempt_id}:log",
            location=f"stub://executions/{dispatch_input.task_id}/{dispatch_input.attempt_id}/log",
            provenance=provenance,
            metadata={"advisory": True},
        )
        return ExecutorDispatchOutput(
            events=(
                ExecutionEvent(
                    event_id=f"{dispatch_input.attempt_id}:completed",
                    task_id=dispatch_input.task_id,
                    attempt_id=dispatch_input.attempt_id,
                    event_type=ExecutionEventType.EXECUTION_SUCCEEDED,
                    occurred_at="2026-04-11T09:10:00Z",
                    provenance=provenance,
                    artifact_references=(artifact_reference,),
                    advisory_completion=AdvisoryCompletionClaim(
                        claim_id=f"{dispatch_input.attempt_id}:claim",
                        reported_complete=True,
                        confidence="low",
                        reason="out-of-order regression coverage",
                        metadata={"advisory_only": True},
                    ),
                    metadata={"adapter": "out-of-order"},
                ),
                ExecutionEvent(
                    event_id=f"{dispatch_input.attempt_id}:started",
                    task_id=dispatch_input.task_id,
                    attempt_id=dispatch_input.attempt_id,
                    event_type=ExecutionEventType.EXECUTION_STARTED,
                    occurred_at="2026-04-11T09:05:00Z",
                    provenance=provenance,
                    metadata={"adapter": "out-of-order"},
                ),
            ),
            artifact_references=(artifact_reference,),
        )


class _FakeCodexCloudRuntimeClient:
    def execute(self, request_payload: dict) -> dict:
        return {
            "run_id": "codex-runtime-run-1",
            "preflight": {
                "pwd": "/workspace/Harness",
                "git_remote_v": (
                    "origin\thttps://github.com/sfayka/Harness.git (fetch)\n"
                    "origin\thttps://github.com/sfayka/Harness.git (push)"
                ),
                "bootstrap_proof": "bootstrap ok",
            },
            "events": [
                {"id": "evt-1", "type": "run_started", "timestamp": "2026-04-12T12:00:00Z"},
                {"id": "evt-2", "type": "run_succeeded", "timestamp": "2026-04-12T12:05:00Z"},
            ],
            "artifacts": [
                {
                    "type": "branch",
                    "id": "branch-1",
                    "external_id": request_payload["task"]["branch_hint"],
                },
                {
                    "type": "commit",
                    "id": "commit-1",
                    "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                },
                {
                    "type": "pull_request",
                    "id": "pr-1",
                    "url": "https://github.com/sfayka/Harness/pull/999",
                },
            ],
            "completion": {
                "reported_complete": True,
                "confidence": "high",
                "reason": "Codex Cloud produced canonical repository artifacts",
            },
        }


def _registry_with_no_create_pull_request_gateway():
    registry = build_default_reconciliation_registry()
    missing_pr_handler = registry.get(ReconciliationFailureType.MISSING_PR_AFTER_EXECUTION)
    missing_commit_handler = registry.get(ReconciliationFailureType.MISSING_COMMIT_AFTER_EXECUTION)
    registry.register(
        ReconciliationFailureType.MISSING_PR_AFTER_EXECUTION,
        missing_pr_handler.__class__(github=_NoCreatePullRequestGateway()),
    )
    registry.register(
        ReconciliationFailureType.MISSING_COMMIT_AFTER_EXECUTION,
        missing_commit_handler.__class__(github=_NoCreatePullRequestGateway()),
    )
    return registry


def _registry_with_current_run_pull_request_gateway():
    registry = build_default_reconciliation_registry()
    missing_pr_handler = registry.get(ReconciliationFailureType.MISSING_PR_AFTER_EXECUTION)
    missing_commit_handler = registry.get(ReconciliationFailureType.MISSING_COMMIT_AFTER_EXECUTION)
    registry.register(
        ReconciliationFailureType.MISSING_PR_AFTER_EXECUTION,
        missing_pr_handler.__class__(github=_CurrentRunPullRequestGateway()),
    )
    registry.register(
        ReconciliationFailureType.MISSING_COMMIT_AFTER_EXECUTION,
        missing_commit_handler.__class__(github=_CurrentRunPullRequestGateway()),
    )
    return registry


def _registry_with_transient_missing_branch_gateway():
    registry = build_default_reconciliation_registry()
    missing_pr_handler = registry.get(ReconciliationFailureType.MISSING_PR_AFTER_EXECUTION)
    missing_commit_handler = registry.get(ReconciliationFailureType.MISSING_COMMIT_AFTER_EXECUTION)
    registry.register(
        ReconciliationFailureType.MISSING_PR_AFTER_EXECUTION,
        missing_pr_handler.__class__(github=_TransientMissingBranchGateway()),
    )
    registry.register(
        ReconciliationFailureType.MISSING_COMMIT_AFTER_EXECUTION,
        missing_commit_handler.__class__(github=_TransientMissingBranchGateway()),
    )
    return registry


def _to_jsonable(value):
    if is_dataclass(value):
        return {key: _to_jsonable(val) for key, val in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _to_jsonable(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    return value


def _request_payload(case_name: str) -> dict:
    return {"request": _to_jsonable(build_demo_request(case_name))}


def _manual_happy_path_overlay_payload() -> dict:
    task_envelope = create_task_envelope(
        {
            "id": "task-http-happy-overlay-1",
            "title": "Dry-run happy path overlay",
            "description": "Exercise /evaluate with top-level evidence overlays.",
            "origin": {
                "source_system": "openclaw",
                "source_type": "ingress_request",
                "source_id": "req-happy-overlay-1",
            },
            "acceptance_criteria": [
                {
                    "id": "ac-1",
                    "description": "Harness accepts a fully reconciled, evidence-backed completion claim.",
                    "required": True,
                }
            ],
        },
        now="2026-03-31T14:30:00Z",
    )

    return {
        "request": {
            "task_envelope": task_envelope,
            "task_status": "executing",
            "assigned_executor": {
                "executor_type": "codex",
                "executor_id": "executor-e2e-1",
                "assignment_reason": "Manual dry-run overlay payload.",
            },
            "linked_artifacts": [
                {
                    "id": "artifact-pr-dryrun-1",
                    "type": "pull_request",
                    "title": "HARNESS-DRYRUN PR",
                    "description": None,
                    "location": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/pull/2",
                    "content_type": None,
                    "external_id": "PR-2",
                    "commit_sha": None,
                    "pull_request_number": 2,
                    "review_state": "approved",
                    "provenance": {
                        "source_system": "github",
                        "source_type": "api",
                        "source_id": "pull/2",
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
                    "captured_at": "2026-03-31T14:31:00Z",
                    "metadata": {
                        "pull_request_state": "open",
                        "pull_request_merged": False,
                    },
                },
                {
                    "id": "artifact-commit-dryrun-1",
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
                    "branch": None,
                    "changed_files": [],
                    "external_refs": [],
                    "captured_at": "2026-03-31T14:31:10Z",
                    "metadata": {},
                },
            ],
            "completion_evidence": {
                "policy": "required",
                "status": "satisfied",
                "required_artifact_types": ["pull_request", "commit"],
                "validated_artifact_ids": ["artifact-pr-dryrun-1", "artifact-commit-dryrun-1"],
                "validation_method": "external_reconciliation",
                "validated_at": "2026-03-31T14:31:30Z",
                "validator": {
                    "source_system": "harness",
                    "source_type": "verification",
                    "source_id": "verification-dryrun-1",
                    "captured_by": "github-sync",
                },
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
                        "external_id": "repo-dryrun-1",
                    },
                    "branch": {
                        "name": "codex/e2e-test",
                        "base_branch": "main",
                        "head_commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                    },
                    "commit": {
                        "sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                    },
                    "pull_request": {
                        "number": 2,
                        "url": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/pull/2",
                        "state": "open",
                        "review_state": "approved",
                    },
                    "changed_files": {
                        "matches_expected_scope": True,
                        "files": [
                            {
                                "path": "modules/api.py",
                                "change_type": "modified",
                            }
                        ],
                    },
                    "reasons": [],
                },
                "linear_facts": {
                    "record_found": True,
                    "issue_id": "lin-dryrun-1",
                    "issue_key": "HAR-2",
                    "state": "completed",
                    "workflow": {
                        "workflow_id": "workflow-completed",
                        "workflow_name": "completed",
                        "state_type": "completed",
                    },
                    "reasons": [],
                },
            },
            "claimed_completion": True,
            "acceptance_criteria_satisfied": True,
            "runtime_facts": {
                "executor_reported_success": True,
                "attempt_count": 1,
            },
        }
    }


def _completion_claim_payload(*, claim_id: str = "claim-1") -> dict:
    return {
        "completion_claim": {
            "claim_id": claim_id,
            "reported_at": "2026-04-01T08:00:00Z",
            "reported_by": "stub-executor",
            "reason": "executor reported completion",
            "metadata": {"attempt_id": "attempt-1"},
        }
    }


def _execution_attempt_payload(*, attempt_id: str = "attempt-1") -> dict:
    return {
        "execution_attempt": {
            "attempt_id": attempt_id,
            "recorded_at": "2026-04-01T08:00:05Z",
            "status": "succeeded",
            "reported_by": "stub-executor",
            "artifact_references": [
                {
                    "reference_id": f"{attempt_id}:log",
                    "artifact_type": "execution_log",
                    "location": "stub://attempts/log",
                }
            ],
            "metadata": {"executor_run_id": f"stub-run-{attempt_id}"},
        }
    }

def _schema_invalid_submission_payload() -> dict:
    payload = {"request": {"task_envelope": deepcopy(_manual_happy_path_overlay_payload()["request"]["task_envelope"])}}
    completion_evidence = payload["request"]["task_envelope"]["artifacts"]["completion_evidence"]
    del completion_evidence["validated_at"]
    del completion_evidence["validation_method"]
    del completion_evidence["validator"]
    return payload


def _linear_ingress_payload(case_name: str, *, task_id: str | None = None) -> dict:
    canonical_request = _request_payload(case_name)["request"]
    task = deepcopy(canonical_request["task_envelope"])
    external_facts = deepcopy(canonical_request.get("external_facts") or {})

    payload = {
        "issue": {
            "id": f"lin-{task['id']}",
            "identifier": f"HAR-{task['id']}",
            "title": task["title"],
            "description": task["description"],
        },
        "state": {
            "id": "workflow_in_progress" if case_name == "accepted_completion" else "workflow_completed",
            "name": "in_progress" if case_name == "accepted_completion" else "completed",
            "type": "started" if case_name == "accepted_completion" else "completed",
        },
        "project": {
            "id": "project-harness",
            "name": "Harness",
        },
        "task_reference": {
            "harness_task_id": task_id or task["id"],
            "external_ref": f"HAR-{task['id']}",
        },
        "labels": ["linear", "ingress"],
        "priority": task.get("priority", "normal"),
        "task_status": "intake_ready",
        "acceptance_criteria": deepcopy(task["acceptance_criteria"]),
        "external_facts": {},
        "claimed_completion": False,
        "acceptance_criteria_satisfied": False,
    }

    if external_facts.get("expected_code_context") is not None:
        payload["external_facts"]["expected_code_context"] = deepcopy(external_facts["expected_code_context"])
    if external_facts.get("github_facts") is not None:
        payload["external_facts"]["github_facts"] = deepcopy(external_facts["github_facts"])

    if case_name == "blocked_insufficient_evidence":
        payload["task_status"] = "dispatch_ready"
        payload["unresolved_conditions"] = ["Need target repository before dispatch can begin."]

    return payload




def _manual_ingress_payload(*, task_id: str | None = None) -> dict:
    payload: dict[str, object] = {
        "task": {
            "title": "Manual canonical ingestion task",
            "description": "Create and persist a manual task through canonical submission.",
            "requested_by": "operator@example.com",
            "ingress_name": "Manual",
            "ingress_id": "KNO-162",
            "acceptance_criteria": [
                {
                    "id": "ac-1",
                    "description": "Task is persisted and queryable via canonical inspection surfaces.",
                    "required": True,
                }
            ],
        },
        "metadata": {"mode": "manual"},
    }
    if task_id is not None:
        payload["task_id"] = task_id
    return payload


def _openclaw_ingress_payload(*, task_id: str | None = None) -> dict:
    payload: dict[str, object] = {
        "context": {
            "conversation_id": "conv-kno-164",
            "message_id": "msg-kno-164-1",
            "channel": "cli",
            "workspace_id": "workspace-harness",
            "user_id": "operator@example.com",
            "agent_id": "openclaw-assistant",
        },
        "task": {
            "title": "OpenClaw canonical ingress task",
            "description": "Create a task through OpenClaw ingress that is persisted by canonical submission.",
            "acceptance_criteria": [
                "Task is persisted in Harness store.",
                "OpenClaw provenance is visible in canonical read surfaces.",
            ],
            "constraints": ["Keep OpenClaw request shape non-canonical."],
            "priority": "high",
        },
        "metadata": {"request_kind": "openclaw"},
        "claimed_completion": False,
        "acceptance_criteria_satisfied": False,
    }
    if task_id is not None:
        payload["task_id"] = task_id
    return payload


def _github_sync_payload(*, task_id: str) -> dict:
    return {
        "task_id": task_id,
        "captured_at": "2026-04-13T15:00:00Z",
        "expected_code_context": {
            "repository_host": "github.com",
            "repository_owner": "KnoxAnalytics",
            "repository_name": "HARNESS-DRYRUN",
            "branch_name": "codex/e2e-test",
            "base_branch": "main",
        },
        "github": {
            "repository": {
                "host": "github.com",
                "owner": "KnoxAnalytics",
                "name": "HARNESS-DRYRUN",
                "node_id": "repo-dryrun-1",
            },
            "branch": {
                "name": "codex/e2e-test",
                "baseRefName": "main",
                "target": {"oid": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705"},
            },
            "commit": {
                "sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                "html_url": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/commit/8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                "commit": {"message": "Attach GitHub sync bridge"},
            },
            "pull_request": {
                "number": 2,
                "state": "open",
                "reviewDecision": "approved",
                "html_url": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/pull/2",
                "merged": False,
            },
            "files": [
                {
                    "filename": "modules/api.py",
                    "status": "modified",
                    "additions": 12,
                    "deletions": 1,
                }
            ],
        },
    }

def _review_note_artifact(artifact_id: str = "artifact-review-note-1") -> dict:
    return {
        "id": artifact_id,
        "type": "review_note",
        "title": "Manual evidence note",
        "description": "Evidence was manually confirmed during reevaluation.",
        "location": None,
        "content_type": "text/plain",
        "external_id": None,
        "commit_sha": None,
        "pull_request_number": None,
        "review_state": None,
        "provenance": {
            "source_system": "harness",
            "source_type": "manual_review",
            "source_id": f"review/{artifact_id}",
            "captured_by": "operator",
        },
        "verification_status": "verified",
        "repository": None,
        "branch": None,
        "changed_files": [],
        "external_refs": [],
        "captured_at": "2026-03-24T17:10:00Z",
        "metadata": {},
    }


def _progress_artifact(artifact_id: str = "artifact-progress-1") -> dict:
    return {
        "id": artifact_id,
        "type": "progress_artifact",
        "title": "Progress snapshot",
        "description": "Progress carried across reevaluations.",
        "location": None,
        "content_type": "application/json",
        "external_id": None,
        "commit_sha": None,
        "pull_request_number": None,
        "review_state": None,
        "provenance": {
            "source_system": "codex",
            "source_type": "executor_report",
            "source_id": f"progress/{artifact_id}",
            "captured_by": "harness-api",
        },
        "verification_status": "informational",
        "repository": None,
        "branch": None,
        "changed_files": [],
        "external_refs": [],
        "captured_at": "2026-03-24T17:15:00Z",
        "metadata": {
            "completed_items": "2",
            "remaining_items": "1",
        },
    }


def _handoff_artifact(artifact_id: str = "artifact-handoff-1") -> dict:
    return {
        "id": artifact_id,
        "type": "handoff_artifact",
        "title": "Session handoff",
        "description": "Resume from external reconciliation on the next session.",
        "location": None,
        "content_type": "application/json",
        "external_id": None,
        "commit_sha": None,
        "pull_request_number": None,
        "review_state": None,
        "provenance": {
            "source_system": "codex",
            "source_type": "executor_report",
            "source_id": f"handoff/{artifact_id}",
            "captured_by": "harness-api",
        },
        "verification_status": "informational",
        "repository": None,
        "branch": None,
        "changed_files": [],
        "external_refs": [],
        "captured_at": "2026-03-24T17:20:00Z",
        "metadata": {
            "from_session_id": "session-1",
            "resume_hint": "Continue verification after the next sync.",
        },
    }


def _changed_file_artifact(artifact_id: str = "artifact-changed-file-1") -> dict:
    return {
        "id": artifact_id,
        "type": "changed_file",
        "title": "Changed file evidence",
        "description": "Executor-reported changed-file proof.",
        "location": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/tree/codex/e2e-test",
        "content_type": None,
        "external_id": None,
        "commit_sha": None,
        "pull_request_number": None,
        "review_state": None,
        "provenance": {
            "source_system": "codex",
            "source_type": "executor_report",
            "source_id": f"changed-file/{artifact_id}",
            "captured_by": "harness-api",
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
        "changed_files": [
            {
                "path": "modules/api.py",
                "change_type": "modified",
            }
        ],
        "external_refs": [],
        "captured_at": "2026-04-07T18:05:00Z",
        "metadata": {},
    }


def _branch_artifact(artifact_id: str = "artifact-branch-1") -> dict:
    return {
        "id": artifact_id,
        "type": "branch",
        "title": "Branch evidence",
        "description": "Executor-reported branch proof.",
        "location": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/tree/codex/e2e-test",
        "content_type": None,
        "external_id": None,
        "commit_sha": None,
        "pull_request_number": None,
        "review_state": None,
        "provenance": {
            "source_system": "codex",
            "source_type": "executor_report",
            "source_id": f"branch/{artifact_id}",
            "captured_by": "harness-api",
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
        "captured_at": "2026-04-07T18:06:00Z",
        "metadata": {},
    }


def _review_decision_payload(
    task_id: str,
    *,
    outcome: ReviewOutcome = ReviewOutcome.ACCEPT_COMPLETION,
    allowed_outcomes: tuple[ReviewOutcome, ...] | None = None,
) -> dict:
    review_request_payload = deepcopy(_request_payload("review_required")["request"]["review_request"])
    review_request_payload["task_id"] = task_id
    review_request = ReviewRequest(
        review_request_id=review_request_payload["review_request_id"],
        task_id=review_request_payload["task_id"],
        requested_at=review_request_payload["requested_at"],
        requested_by=review_request_payload["requested_by"],
        trigger=ReviewTrigger(review_request_payload["trigger"]),
        summary=review_request_payload["summary"],
        presented_sections=tuple(review_request_payload.get("presented_sections", [])),
        allowed_outcomes=allowed_outcomes
        or tuple(ReviewOutcome(item) for item in review_request_payload.get("allowed_outcomes", [])),
        prior_review_ids=tuple(review_request_payload.get("prior_review_ids", [])),
        metadata=dict(review_request_payload.get("metadata", {})),
    )
    review_decision = resolve_review_request(
        review_request,
        review_id="review-api-1",
        reviewer=ReviewerIdentity(
            reviewer_id="operator-1",
            reviewer_name="Casey Reviewer",
            authority_role="operator",
        ),
        outcome=outcome,
        reasoning=(
            "Additional evidence and manual review resolve the remaining uncertainty."
            if outcome == ReviewOutcome.ACCEPT_COMPLETION
            else "Manual review requires another execution attempt."
        ),
    )
    return _to_jsonable(review_decision)


def _tampered_review_decision_payload(
    task_id: str,
    *,
    recommended_target_status: str | None = None,
    authorized_target_status: str | None = None,
    outcome: str | None = None,
    allowed_outcomes: tuple[str, ...] | None = None,
    review_request_id: str | None = None,
    summary: str | None = None,
) -> dict:
    payload = _review_decision_payload(task_id)
    if allowed_outcomes is not None:
        payload["request"]["allowed_outcomes"] = list(allowed_outcomes)
    if summary is not None:
        payload["request"]["summary"] = summary
    if outcome is not None:
        payload["record"]["outcome"] = outcome
    if review_request_id is not None:
        payload["request"]["review_request_id"] = review_request_id
        payload["record"]["review_request_id"] = review_request_id
    if authorized_target_status is not None:
        payload["record"]["authorized_target_status"] = authorized_target_status
    if recommended_target_status is not None:
        payload["recommended_target_status"] = recommended_target_status
    return payload


class HarnessApiPayloadTests(unittest.TestCase):
    def test_accepts_completion_payload(self) -> None:
        status, payload = evaluate_http_payload(_request_payload("accepted_completion"))

        self.assertEqual(status, 200)
        self.assertEqual(payload["action"], "transition_applied")
        self.assertEqual(payload["task_envelope"]["status"], "completed")

    def test_rejects_invalid_input_payload(self) -> None:
        status, payload = evaluate_http_payload(_request_payload("invalid_input"))

        self.assertEqual(status, 400)
        self.assertEqual(payload["action"], "invalid_input")
        self.assertTrue(payload["invalid_input"])

    def test_rejects_schema_invalid_payload(self) -> None:
        status, payload = evaluate_http_payload(_schema_invalid_submission_payload())

        self.assertEqual(status, 400)
        self.assertTrue(payload["invalid_input"])
        self.assertIn("Invalid TaskEnvelope:", payload["error"])


class HarnessApiCliTests(unittest.TestCase):
    def test_parser_defaults_to_render_safe_host_and_port(self) -> None:
        original_port = os.environ.pop("PORT", None)
        self.addCleanup(lambda: os.environ.__setitem__("PORT", original_port) if original_port is not None else os.environ.pop("PORT", None))

        args = build_parser().parse_args([])

        self.assertEqual(args.host, "0.0.0.0")
        self.assertEqual(args.port, 8000)

    def test_parser_uses_port_environment_variable_when_present(self) -> None:
        original_port = os.environ.get("PORT")
        os.environ["PORT"] = "10000"
        self.addCleanup(lambda: os.environ.__setitem__("PORT", original_port) if original_port is not None else os.environ.pop("PORT", None))

        args = build_parser().parse_args([])

        self.assertEqual(args.host, "0.0.0.0")
        self.assertEqual(args.port, 10000)

    def test_service_defaults_to_file_store_backend(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)

        with patch.dict(
            os.environ,
            {"HARNESS_STORE_BACKEND": "file", "HARNESS_STORE_ROOT": temp_dir.name},
            clear=False,
        ):
            service = HarnessApiService()

        self.assertIsInstance(service.store, FileBackedHarnessStore)

    def test_service_uses_sqlite_store_backend_from_environment(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        database_path = str(Path(temp_dir.name) / "harness.db")

        with patch.dict(
            os.environ,
            {"HARNESS_STORE_BACKEND": "sqlite", "HARNESS_SQLITE_PATH": database_path},
            clear=True,
        ):
            service = HarnessApiService()

        self.assertIsInstance(service.store, SQLiteHarnessStore)
        self.assertEqual(service.store.database_path, Path(database_path))

    @unittest.skipUnless(POSTGRES_TEST_DATABASE_URL, "HARNESS_TEST_DATABASE_URL is required for Postgres startup selection test")
    def test_service_uses_postgres_store_backend_from_environment(self) -> None:
        with patch.dict(
            os.environ,
            {
                "HARNESS_STORE_BACKEND": "postgres",
                "POSTGRES_URL": POSTGRES_TEST_DATABASE_URL or "",
            },
            clear=False,
        ):
            service = HarnessApiService()

        self.assertIsInstance(service.store, PostgresHarnessStore)

class HarnessApiServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.service = HarnessApiService(store=FileBackedHarnessStore(self.temp_dir.name))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_service_persists_evaluation_and_task_snapshot(self) -> None:
        status, payload = self.service.evaluate(_request_payload("accepted_completion"))

        self.assertEqual(status, 200)
        self.assertEqual(payload["task_envelope"]["status"], "completed")
        self.assertEqual(payload["evaluation_record"]["task_id"], payload["task_envelope"]["id"])

        task_status, task_payload = self.service.get_task(payload["task_envelope"]["id"])
        history_status, history_payload = self.service.get_evaluation_history(payload["task_envelope"]["id"])

        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["status"], "completed")
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 1)

    def test_service_rejects_invalid_input_without_persisting_state(self) -> None:
        task_id = _request_payload("invalid_input")["request"]["task_envelope"]["id"]

        status, payload = self.service.evaluate(_request_payload("invalid_input"))
        task_status, task_payload = self.service.get_task(task_id)
        history_status, history_payload = self.service.get_evaluation_history(task_id)

        self.assertEqual(status, 400)
        self.assertTrue(payload["invalid_input"])
        self.assertEqual(task_status, 404)
        self.assertIn("not found", task_payload["error"].lower())
        self.assertEqual(history_status, 404)
        self.assertIn("not found", history_payload["error"].lower())

    def test_service_lists_dashboard_tasks_from_read_model_surface(self) -> None:
        self.service.submit({"request": {"task_envelope": deepcopy(_manual_happy_path_overlay_payload()["request"]["task_envelope"])}})
        blocked_task = create_task_envelope(
            {
                "id": "task-submit-list-blocked-1",
                "title": "Blocked by clarification",
                "description": "Task should remain blocked until clarification arrives.",
                "origin": {
                    "source_system": "manual",
                    "source_type": "manual",
                    "source_id": "task-submit-list-blocked-1",
                },
                "acceptance_criteria": [{"id": "ac-1", "description": "Clarification is resolved.", "required": True}],
            },
            now="2026-04-07T00:00:00Z",
        )
        self.service.submit(
            {
                "request": {
                    "task_envelope": blocked_task,
                    "task_status": "dispatch_ready",
                    "unresolved_conditions": ["Need repository clarification before execution can begin."],
                }
            }
        )

        status, payload = self.service.list_tasks()

        self.assertEqual(status, 200)
        self.assertEqual(len(payload["tasks"]), 2)
        self.assertIn("verification_summary", payload["tasks"][0])
        self.assertIn("timeline", payload["tasks"][0])

    def test_service_submit_persists_new_task_and_initial_evaluation(self) -> None:
        status, payload = self.service.submit(
            {"request": {"task_envelope": deepcopy(_manual_happy_path_overlay_payload()["request"]["task_envelope"])}}
        )

        task_status, task_payload = self.service.get_task(payload["task_envelope"]["id"])
        history_status, history_payload = self.service.get_evaluation_history(payload["task_envelope"]["id"])

        self.assertEqual(status, 200)
        self.assertEqual(payload["task_envelope"]["status"], "intake_ready")
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["status"], "intake_ready")
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 1)

    def test_service_submit_rejects_duplicate_task_id(self) -> None:
        submit_payload = {
            "request": {
                "task_envelope": deepcopy(_manual_happy_path_overlay_payload()["request"]["task_envelope"]),
            }
        }
        initial_status, initial_payload = self.service.submit(submit_payload)
        duplicate_status, duplicate_payload = self.service.submit(submit_payload)
        history_status, history_payload = self.service.get_evaluation_history(initial_payload["task_envelope"]["id"])

        self.assertEqual(initial_status, 200)
        self.assertEqual(duplicate_status, 409)
        self.assertTrue(duplicate_payload["duplicate_task_id"])
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 1)

    def test_service_submit_rejects_missing_task_id_without_crashing(self) -> None:
        status, payload = self.service.submit({"request": {"task_envelope": {"title": "Missing id"}}})

        self.assertEqual(status, 400)
        self.assertTrue(payload["invalid_input"])
        self.assertIn("task_envelope.id is required", payload["error"])

    def test_service_submit_rejects_schema_invalid_task_envelope_without_crashing(self) -> None:
        status, payload = self.service.submit(_schema_invalid_submission_payload())

        self.assertEqual(status, 400)
        self.assertTrue(payload["invalid_input"])
        self.assertIn("Invalid TaskEnvelope:", payload["error"])

    def test_service_evaluate_strips_verified_status_from_initial_support_artifacts(self) -> None:
        task_envelope = create_task_envelope(
            {
                "id": "task-evaluate-initial-support-artifact-1",
                "title": "Evaluate initial support artifact trust",
                "description": "New-task evaluation should not keep caller-certified verified support artifacts.",
                "origin": {
                    "source_system": "openclaw",
                    "source_type": "ingress_request",
                    "source_id": "req-evaluate-initial-support-artifact-1",
                },
                "acceptance_criteria": [
                    {
                        "id": "ac-1",
                        "description": "Harness preserves advisory support artifacts without trusting caller verification.",
                        "required": True,
                    }
                ],
            },
            now="2026-04-07T22:40:00Z",
        )
        task_envelope["artifacts"]["items"] = [
            {
                **_review_note_artifact("artifact-evaluate-initial-review-note-1"),
                "provenance": {
                    "source_system": "codex",
                    "source_type": "executor_report",
                    "source_id": "evaluate/self-certified-initial-review-note-1",
                    "captured_by": "harness-api",
                },
            }
        ]
        payload = {"request": {"task_envelope": task_envelope}}

        status, response = self.service.evaluate(payload)

        self.assertEqual(status, 200)
        stored_artifact = response["task_envelope"]["artifacts"]["items"][0]
        self.assertEqual(stored_artifact["verification_status"], "unverified")
        self.assertEqual(stored_artifact["metadata"]["submitted_verification_status"], "verified")

    def test_service_submit_rejects_completion_shaped_new_task_without_persisting_state(self) -> None:
        payload = _request_payload("accepted_completion")
        task_id = payload["request"]["task_envelope"]["id"]

        status, response = self.service.submit(payload)
        task_status, task_payload = self.service.get_task(task_id)

        self.assertEqual(status, 400)
        self.assertTrue(response["invalid_input"])
        self.assertIn("cannot claim completion", response["error"].lower())
        self.assertTrue(response["submission_contract_violations"])
        self.assertEqual(task_status, 404)
        self.assertIn("not found", task_payload["error"].lower())

    def test_service_submit_rejects_nested_execution_history_on_new_task(self) -> None:
        payload = {"request": {"task_envelope": deepcopy(_manual_happy_path_overlay_payload()["request"]["task_envelope"])}}
        payload["request"]["task_envelope"]["observability"]["execution_metadata"]["execution_attempts"] = [
            {"attempt_id": "attempt-1", "status": "completed"}
        ]

        status, response = self.service.submit(payload)

        self.assertEqual(status, 400)
        self.assertTrue(response["invalid_input"])
        self.assertEqual(
            response["submission_contract_violations"][0]["rule"],
            "initial_execution_attempt_history_not_allowed",
        )

    def test_service_submit_rejects_validated_completion_evidence_on_new_task(self) -> None:
        payload = {"request": {"task_envelope": deepcopy(_manual_happy_path_overlay_payload()["request"]["task_envelope"])}}
        payload["request"]["task_envelope"]["artifacts"]["completion_evidence"]["status"] = "satisfied"
        payload["request"]["task_envelope"]["artifacts"]["completion_evidence"]["validated_artifact_ids"] = [
            "artifact-pr-1"
        ]
        payload["request"]["task_envelope"]["artifacts"]["completion_evidence"]["validated_at"] = "2026-04-07T00:00:00Z"

        status, response = self.service.submit(payload)

        self.assertEqual(status, 400)
        self.assertTrue(response["invalid_input"])
        self.assertTrue(
            any(
                violation["rule"] == "initial_validated_completion_evidence_not_allowed"
                for violation in response["submission_contract_violations"]
            )
        )

    def test_service_submit_strips_verified_status_from_initial_support_artifacts(self) -> None:
        payload = {"request": {"task_envelope": deepcopy(_manual_happy_path_overlay_payload()["request"]["task_envelope"])}}
        payload["request"]["task_envelope"]["artifacts"]["items"] = [
            {
                **_review_note_artifact("artifact-submit-review-note-1"),
                "provenance": {
                    "source_system": "codex",
                    "source_type": "executor_report",
                    "source_id": "submit/self-certified-review-note-1",
                    "captured_by": "harness-api",
                },
            }
        ]

        status, response = self.service.submit(payload)

        self.assertEqual(status, 200)
        stored_artifact = response["task_envelope"]["artifacts"]["items"][0]
        self.assertEqual(stored_artifact["verification_status"], "unverified")
        self.assertEqual(stored_artifact["metadata"]["submitted_verification_status"], "verified")

    def test_service_submit_rejects_assigned_status_on_new_task(self) -> None:
        payload = {"request": {"task_envelope": deepcopy(_manual_happy_path_overlay_payload()["request"]["task_envelope"])}}
        task_id = payload["request"]["task_envelope"]["id"]
        payload["request"]["task_status"] = "assigned"

        status, response = self.service.submit(payload)
        task_status, task_payload = self.service.get_task(task_id)

        self.assertEqual(status, 400)
        self.assertTrue(response["invalid_input"])
        self.assertTrue(
            any(
                violation["rule"] == "initial_task_status_invalid"
                for violation in response["submission_contract_violations"]
            )
        )
        self.assertEqual(task_status, 404)
        self.assertIn("not found", task_payload["error"].lower())

    def test_service_submit_rejects_assigned_executor_on_new_task(self) -> None:
        payload = {"request": {"task_envelope": deepcopy(_manual_happy_path_overlay_payload()["request"]["task_envelope"])}}
        task_id = payload["request"]["task_envelope"]["id"]
        payload["request"]["assigned_executor"] = {
            "executor_type": "codex",
            "executor_id": "executor-submit-1",
            "assignment_reason": "Fresh submission should not assign executors.",
        }

        status, response = self.service.submit(payload)
        task_status, task_payload = self.service.get_task(task_id)

        self.assertEqual(status, 400)
        self.assertTrue(response["invalid_input"])
        self.assertTrue(
            any(
                violation["rule"] == "initial_assigned_executor_not_allowed"
                for violation in response["submission_contract_violations"]
            )
        )
        self.assertEqual(task_status, 404)
        self.assertIn("not found", task_payload["error"].lower())

    def test_service_can_submit_linear_ingress_payload_via_canonical_submission_path(self) -> None:
        status, payload = self.service.submit_linear_ingress(_linear_ingress_payload("accepted_completion"))

        task_status, task_payload = self.service.get_task(payload["task_envelope"]["id"])
        history_status, history_payload = self.service.get_evaluation_history(payload["task_envelope"]["id"])

        self.assertEqual(status, 200)
        self.assertEqual(payload["task_envelope"]["origin"]["source_system"], "linear")
        self.assertEqual(payload["task_envelope"]["status"], "intake_ready")
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["extensions"]["linear"]["issue_id"], f"lin-{payload['task_envelope']['id']}")
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 1)


    def test_service_can_submit_manual_ingress_payload_and_expose_canonical_read_surfaces(self) -> None:
        status, payload = self.service.submit_manual_ingress(_manual_ingress_payload())

        task_id = payload["task_envelope"]["id"]
        list_status, list_payload = self.service.list_tasks()
        read_status, read_payload = self.service.get_task_read_model(task_id)
        timeline_status, timeline_payload = self.service.get_task_timeline(task_id)
        history_status, history_payload = self.service.get_evaluation_history(task_id)

        self.assertEqual(status, 200)
        self.assertTrue(task_id)
        self.assertEqual(payload["task_envelope"]["origin"]["source_system"], "manual")
        self.assertEqual(list_status, 200)
        self.assertEqual(list_payload["tasks"][0]["task_id"], task_id)
        self.assertEqual(read_status, 200)
        self.assertEqual(read_payload["task"]["task_id"], task_id)
        self.assertEqual(timeline_status, 200)
        self.assertEqual(timeline_payload["task_id"], task_id)
        self.assertGreaterEqual(timeline_payload["event_count"], 1)
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 1)

    def test_service_submit_rejects_runtime_status_overlay_on_initial_submission(self) -> None:
        payload = {
            "request": {
                "task_envelope": deepcopy(_manual_happy_path_overlay_payload()["request"]["task_envelope"]),
                "task_status": "executing",
            }
        }

        status, response = self.service.submit(payload)

        self.assertEqual(status, 400)
        self.assertTrue(response["invalid_input"])
        self.assertIn("task_status may only seed intake/planning lifecycle states", response["error"])

    def test_service_evaluate_existing_task_rejects_runtime_status_overlay(self) -> None:
        submit_payload = {"request": {"task_envelope": deepcopy(_manual_happy_path_overlay_payload()["request"]["task_envelope"])}}
        submit_status, submit_response = self.service.submit(submit_payload)

        evaluate_payload = {
            "request": {
                "task_envelope": deepcopy(submit_response["task_envelope"]),
                "task_status": "executing",
                "linked_artifacts": deepcopy(_manual_happy_path_overlay_payload()["request"]["linked_artifacts"]),
                "completion_evidence": deepcopy(_manual_happy_path_overlay_payload()["request"]["completion_evidence"]),
                "external_facts": deepcopy(_manual_happy_path_overlay_payload()["request"]["external_facts"]),
                "claimed_completion": True,
                "acceptance_criteria_satisfied": True,
                "runtime_facts": deepcopy(_manual_happy_path_overlay_payload()["request"]["runtime_facts"]),
            }
        }

        status, response = self.service.evaluate(evaluate_payload)

        self.assertEqual(submit_status, 200)
        self.assertEqual(status, 400)
        self.assertTrue(response["invalid_input"])
        self.assertIn("task_status may only seed intake/planning lifecycle states", response["error"])

    def test_service_manual_ingress_canonicalizes_unresolved_conditions_into_clarification(self) -> None:
        payload = _manual_ingress_payload(task_id="task-manual-clarification-1")
        payload["unresolved_conditions"] = ["Need repository clarification before proceeding."]

        status, response = self.service.submit_manual_ingress(payload)

        self.assertEqual(status, 200)
        self.assertEqual(response["task_envelope"]["status"], "blocked")
        clarification = response["task_envelope"]["clarification"]
        self.assertEqual(clarification["status"], "required")
        self.assertEqual(clarification["resume_target_status"], "intake_ready")
        self.assertEqual(clarification["required_inputs"][0]["description"], "Need repository clarification before proceeding.")

    def test_service_manual_ingress_converts_unresolved_conditions_into_clarification_block(self) -> None:
        payload_in = _manual_ingress_payload(task_id="task-manual-clarification-1")
        payload_in["task_status"] = "dispatch_ready"
        payload_in["unresolved_conditions"] = ["Need target repository before dispatch can begin."]

        status, payload = self.service.submit_manual_ingress(payload_in)
        task_id = payload["task_envelope"]["id"]
        read_status, read_payload = self.service.get_task_read_model(task_id)

        self.assertEqual(status, 200)
        self.assertEqual(payload["task_envelope"]["status"], "blocked")
        self.assertEqual(payload["task_envelope"]["clarification"]["status"], "required")
        self.assertEqual(payload["task_envelope"]["clarification"]["resume_target_status"], "dispatch_ready")
        self.assertFalse(payload["automatic_dispatch"]["attempted"])
        self.assertFalse(payload["automatic_dispatch"]["dispatchable"])
        self.assertEqual(read_status, 200)
        self.assertEqual(read_payload["task"]["current_status"], "blocked")
        self.assertEqual(read_payload["task"]["clarification_summary"]["status"], "required")
        self.assertEqual(read_payload["task"]["clarification_summary"]["resume_target_status"], "dispatch_ready")

    def test_service_can_submit_openclaw_ingress_payload_and_persist_openclaw_provenance(self) -> None:
        payload_in = _openclaw_ingress_payload()
        payload_in["unresolved_conditions"] = ["Need repository confirmation before planning can continue."]
        status, payload = self.service.submit_openclaw_ingress(payload_in)

        task_id = payload["task_envelope"]["id"]
        read_status, read_payload = self.service.get_task_read_model(task_id)
        history_status, history_payload = self.service.get_evaluation_history(task_id)

        self.assertEqual(status, 200)
        self.assertEqual(payload["task_envelope"]["status"], "blocked")
        self.assertEqual(payload["task_envelope"]["origin"]["source_system"], "openclaw")
        self.assertEqual(payload["task_envelope"]["origin"]["source_id"], "msg-kno-164-1")
        self.assertEqual(payload["task_envelope"]["extensions"]["openclaw"]["conversation_id"], "conv-kno-164")
        self.assertEqual(payload["task_envelope"]["clarification"]["status"], "required")
        self.assertEqual(read_status, 200)
        self.assertEqual(read_payload["task"]["extensions"]["openclaw"]["metadata"]["request_kind"], "openclaw")
        self.assertEqual(read_payload["task"]["current_status"], "blocked")
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 1)

    def test_service_submit_blocks_requested_dispatch_ready_task_when_unresolved_conditions_exist(self) -> None:
        task_envelope = create_task_envelope(
            {
                "id": "task-submit-clarification-1",
                "title": "Task with unresolved clarification",
                "description": "Direct submit should not preserve dispatch-ready when information is missing.",
                "origin": {
                    "source_system": "manual",
                    "source_type": "manual",
                    "source_id": "task-submit-clarification-1",
                },
                "acceptance_criteria": [
                    {
                        "id": "ac-1",
                        "description": "Task is safe to route only after repository clarification.",
                        "required": True,
                    }
                ],
            },
            now="2026-04-06T00:00:00Z",
        )

        status, payload = self.service.submit(
            {
                "request": {
                    "task_envelope": task_envelope,
                    "task_status": "dispatch_ready",
                    "unresolved_conditions": ["Need the target repository before dispatch."],
                }
            }
        )
        timeline_status, timeline_payload = self.service.get_task_timeline("task-submit-clarification-1")

        self.assertEqual(status, 200)
        self.assertEqual(payload["task_envelope"]["status"], "blocked")
        self.assertEqual(payload["task_envelope"]["clarification"]["status"], "required")
        self.assertEqual(payload["task_envelope"]["clarification"]["resume_target_status"], "dispatch_ready")
        self.assertFalse(payload["automatic_dispatch"]["attempted"])
        self.assertFalse(payload["automatic_dispatch"]["dispatchable"])
        self.assertIn("clarification unresolved", payload["automatic_dispatch"]["reason"])
        self.assertEqual(timeline_status, 200)
        self.assertTrue(
            any(event["event_type"] == "clarification_updated" for event in timeline_payload["timeline"])
        )

    def test_service_openclaw_ingress_rejects_completion_shaped_handoff_without_persisting_task(self) -> None:
        payload = _openclaw_ingress_payload(task_id="task-openclaw-completion-shaped-1")
        payload["claimed_completion"] = True

        status, response_payload = self.service.submit_openclaw_ingress(payload)
        task_status, task_payload = self.service.get_task("task-openclaw-completion-shaped-1")

        self.assertEqual(status, 400)
        self.assertTrue(response_payload["invalid_input"])
        self.assertIn("cannot claim completion", response_payload["error"].lower())
        self.assertEqual(task_status, 404)
        self.assertIn("not found", task_payload["error"].lower())

    def test_service_openclaw_ingress_rejects_execution_status_handoff_without_persisting_task(self) -> None:
        payload = _openclaw_ingress_payload(task_id="task-openclaw-executing-1")
        payload["task"]["status"] = "executing"

        status, response_payload = self.service.submit_openclaw_ingress(payload)
        task_status, task_payload = self.service.get_task("task-openclaw-executing-1")

        self.assertEqual(status, 400)
        self.assertTrue(response_payload["invalid_input"])
        self.assertIn("task.status must be one of", response_payload["error"])
        self.assertEqual(task_status, 404)
        self.assertIn("not found", task_payload["error"].lower())

    def test_service_openclaw_ingress_rejects_planned_handoff_without_explicit_objective_contract(self) -> None:
        payload = _openclaw_ingress_payload(task_id="task-openclaw-planned-weak-1")
        payload["task"]["status"] = "planned"

        status, response_payload = self.service.submit_openclaw_ingress(payload)
        task_status, task_payload = self.service.get_task("task-openclaw-planned-weak-1")

        self.assertEqual(status, 400)
        self.assertTrue(response_payload["invalid_input"])
        self.assertIn("planned handoff requires task.objective_summary", response_payload["error"].lower())
        self.assertEqual(task_status, 404)
        self.assertIn("not found", task_payload["error"].lower())

    def test_service_openclaw_ingress_accepts_structured_planned_handoff(self) -> None:
        payload = _openclaw_ingress_payload(task_id="task-openclaw-planned-valid-1")
        payload["task"]["status"] = "planned"
        payload["task"]["objective_summary"] = "Produce a routing-ready implementation task."
        payload["task"]["objective_deliverable_type"] = "code_change"
        payload["task"]["objective_success_signal"] = "The task is defined enough to route without clarification."
        payload["task"]["parent_task_id"] = "epic-openclaw-1"
        payload["task"]["dependencies"] = [
            {
                "task_id": "task-bootstrap-prereq-1",
                "dependency_type": "blocks",
                "required_status": "completed",
                "description": "Repository bootstrap must complete first.",
            }
        ]
        payload["task"]["required_capabilities"] = ["github", "python"]
        payload["metadata"]["plan_summary"] = "Single-task implementation handoff is ready for dispatcher review."
        payload["task"]["acceptance_criteria"] = [
            "The task records an explicit deliverable type.",
            "The task records an explicit success signal.",
        ]
        payload["unresolved_conditions"] = []

        status, response_payload = self.service.submit_openclaw_ingress(payload)
        task_status, task_payload = self.service.get_task("task-openclaw-planned-valid-1")

        self.assertEqual(status, 200)
        self.assertEqual(
            response_payload["task_envelope"]["objective"]["deliverable_type"],
            "code_change",
        )
        self.assertEqual(
            response_payload["task_envelope"]["objective"]["success_signal"],
            "The task is defined enough to route without clarification.",
        )
        self.assertFalse(response_payload["automatic_dispatch"]["attempted"])
        self.assertFalse(response_payload["automatic_dispatch"]["dispatchable"])
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["status"], "planned")
        self.assertEqual(task_payload["task"]["objective"]["deliverable_type"], "code_change")
        self.assertEqual(task_payload["task"]["parent_task_id"], "epic-openclaw-1")
        self.assertEqual(task_payload["task"]["dependencies"][0]["task_id"], "task-bootstrap-prereq-1")
        self.assertEqual(task_payload["task"]["required_capabilities"], ["github", "python"])

    def test_service_openclaw_ingress_rejects_planned_handoff_without_plan_summary(self) -> None:
        payload = _openclaw_ingress_payload(task_id="task-openclaw-planned-no-summary-1")
        payload["task"]["status"] = "planned"
        payload["task"]["objective_summary"] = "Produce a routing-ready implementation task."
        payload["task"]["objective_deliverable_type"] = "code_change"
        payload["task"]["objective_success_signal"] = "The task is defined enough to route without clarification."
        payload["unresolved_conditions"] = []

        status, response_payload = self.service.submit_openclaw_ingress(payload)
        task_status, task_payload = self.service.get_task("task-openclaw-planned-no-summary-1")

        self.assertEqual(status, 400)
        self.assertTrue(response_payload["invalid_input"])
        self.assertIn("metadata.plan_summary", response_payload["error"])
        self.assertEqual(task_status, 404)
        self.assertIn("not found", task_payload["error"].lower())

    def test_service_openclaw_ingress_rejects_self_referential_dependency_structure(self) -> None:
        payload = _openclaw_ingress_payload(task_id="task-openclaw-self-dependency-1")
        payload["task"]["status"] = "planned"
        payload["task"]["objective_summary"] = "Produce a routing-ready implementation task."
        payload["task"]["objective_deliverable_type"] = "code_change"
        payload["task"]["objective_success_signal"] = "The task is defined enough to route without clarification."
        payload["task"]["dependencies"] = [
            {
                "task_id": "task-openclaw-self-dependency-1",
                "dependency_type": "blocks",
                "required_status": "completed",
            }
        ]
        payload["metadata"]["plan_summary"] = "Single-task implementation handoff is ready for dispatcher review."
        payload["unresolved_conditions"] = []

        status, response_payload = self.service.submit_openclaw_ingress(payload)
        task_status, task_payload = self.service.get_task("task-openclaw-self-dependency-1")

        self.assertEqual(status, 400)
        self.assertTrue(response_payload["invalid_input"])
        self.assertIn("self-dependency", response_payload["error"].lower())
        self.assertEqual(task_status, 404)
        self.assertIn("not found", task_payload["error"].lower())

    def test_service_dispatch_rejects_task_blocked_on_clarification(self) -> None:
        payload = _openclaw_ingress_payload(task_id="task-openclaw-clarification-blocked-1")
        payload["unresolved_conditions"] = ["Need repository confirmation before planning can continue."]

        submit_status, submit_payload = self.service.submit_openclaw_ingress(payload)
        dispatch_status, dispatch_payload = self.service.dispatch_task(
            submit_payload["task_envelope"]["id"],
            {"request": {"executor": "codex"}},
        )

        self.assertEqual(submit_status, 200)
        self.assertEqual(submit_payload["task_envelope"]["status"], "blocked")
        self.assertEqual(dispatch_status, 409)
        self.assertIn("blocked on clarification", dispatch_payload["error"])

    def test_service_submit_does_not_auto_dispatch_task_blocked_on_dependency(self) -> None:
        upstream_task = create_task_envelope(
            {
                "id": "task-upstream-planned-1",
                "title": "Bootstrap repo",
                "description": "Finish bootstrap before downstream work starts.",
                "origin": {
                    "source_system": "openclaw",
                    "source_type": "ingress_request",
                    "source_id": "msg-upstream-1",
                },
                "acceptance_criteria": [{"id": "ac-1", "description": "Bootstrap completes.", "required": True}],
            },
            now="2026-04-06T00:00:00Z",
        )
        upstream_task["status"] = "planned"
        self.service.store.put_task(upstream_task)

        downstream_task = create_task_envelope(
            {
                "id": "task-downstream-dependency-1",
                "title": "Implement downstream task",
                "description": "Only start after bootstrap finishes.",
                "origin": {
                    "source_system": "openclaw",
                    "source_type": "ingress_request",
                    "source_id": "msg-downstream-1",
                },
                "acceptance_criteria": [{"id": "ac-1", "description": "Downstream code lands.", "required": True}],
            },
            now="2026-04-06T00:00:00Z",
        )
        downstream_task["dependencies"] = [
            {
                "task_id": "task-upstream-planned-1",
                "dependency_type": "blocks",
                "required_status": "completed",
                "description": "Bootstrap must complete first.",
            }
        ]

        status, response_payload = self.service.submit(
            {
                "request": {
                    "task_envelope": downstream_task,
                    "task_status": "dispatch_ready",
                }
            }
        )

        self.assertEqual(status, 200)
        self.assertFalse(response_payload["automatic_dispatch"]["attempted"])
        self.assertFalse(response_payload["automatic_dispatch"]["dispatchable"])
        self.assertIn("blocked on dependency", response_payload["automatic_dispatch"]["reason"])

    def test_service_dispatch_rejects_task_with_unmet_blocking_dependency(self) -> None:
        upstream_task = create_task_envelope(
            {
                "id": "task-upstream-planned-2",
                "title": "Bootstrap repo",
                "description": "Finish bootstrap before downstream work starts.",
                "origin": {
                    "source_system": "openclaw",
                    "source_type": "ingress_request",
                    "source_id": "msg-upstream-2",
                },
                "acceptance_criteria": [{"id": "ac-1", "description": "Bootstrap completes.", "required": True}],
            },
            now="2026-04-06T00:00:00Z",
        )
        upstream_task["status"] = "planned"
        self.service.store.put_task(upstream_task)

        downstream_task = create_task_envelope(
            {
                "id": "task-downstream-dependency-2",
                "title": "Implement downstream task",
                "description": "Only start after bootstrap finishes.",
                "origin": {
                    "source_system": "openclaw",
                    "source_type": "ingress_request",
                    "source_id": "msg-downstream-2",
                },
                "acceptance_criteria": [{"id": "ac-1", "description": "Downstream code lands.", "required": True}],
            },
            now="2026-04-06T00:00:00Z",
        )
        downstream_task["dependencies"] = [
            {
                "task_id": "task-upstream-planned-2",
                "dependency_type": "blocks",
                "required_status": "completed",
            }
        ]
        self.service.store.put_task({**downstream_task, "status": "assigned"})

        dispatch_status, dispatch_payload = self.service.dispatch_task(
            "task-downstream-dependency-2",
            {"request": {"executor": "codex"}},
        )

        self.assertEqual(dispatch_status, 409)
        self.assertIn("blocked on dependency", dispatch_payload["error"])

    def test_service_dispatch_allows_task_once_blocking_dependency_reaches_required_status(self) -> None:
        upstream_task = create_task_envelope(
            {
                "id": "task-upstream-completed-1",
                "title": "Bootstrap repo",
                "description": "Finish bootstrap before downstream work starts.",
                "origin": {
                    "source_system": "openclaw",
                    "source_type": "ingress_request",
                    "source_id": "msg-upstream-3",
                },
                "acceptance_criteria": [{"id": "ac-1", "description": "Bootstrap completes.", "required": True}],
            },
            now="2026-04-06T00:00:00Z",
        )
        upstream_task["status"] = "completed"
        self.service.store.put_task(upstream_task)

        downstream_task = create_task_envelope(
            {
                "id": "task-downstream-dependency-3",
                "title": "Implement downstream task",
                "description": "Only start after bootstrap finishes.",
                "origin": {
                    "source_system": "openclaw",
                    "source_type": "ingress_request",
                    "source_id": "msg-downstream-3",
                },
                "acceptance_criteria": [{"id": "ac-1", "description": "Downstream code lands.", "required": True}],
            },
            now="2026-04-06T00:00:00Z",
        )
        downstream_task["dependencies"] = [
            {
                "task_id": "task-upstream-completed-1",
                "dependency_type": "blocks",
                "required_status": "completed",
            }
        ]
        self.service.store.put_task({**downstream_task, "status": "assigned"})

        dispatch_status, dispatch_payload = self.service.dispatch_task(
            "task-downstream-dependency-3",
            {"request": {"executor": "codex"}},
        )

        self.assertEqual(dispatch_status, 200)
        self.assertEqual(dispatch_payload["dispatch"]["task_id"], "task-downstream-dependency-3")

    def test_service_openclaw_ingress_rejects_runtime_facts_without_persisting_task(self) -> None:
        payload = _openclaw_ingress_payload(task_id="task-openclaw-runtime-facts-1")
        payload["runtime_facts"] = {"attempt_count": 1}

        status, response_payload = self.service.submit_openclaw_ingress(payload)
        task_status, task_payload = self.service.get_task("task-openclaw-runtime-facts-1")

        self.assertEqual(status, 400)
        self.assertTrue(response_payload["invalid_input"])
        self.assertIn("runtime_facts", response_payload["error"])
        self.assertEqual(task_status, 404)
        self.assertIn("not found", task_payload["error"].lower())

    def test_service_reevaluate_support_evidence_keeps_blocked_task_blocked_until_verified(self) -> None:
        initial_payload = _request_payload("blocked_insufficient_evidence")
        initial_status, initial_response = self.service.evaluate(initial_payload)

        reevaluation_payload = {
            "request": {
                "new_artifacts": [_review_note_artifact()],
                "completion_evidence": {
                    "validated_artifact_ids": [
                        "artifact-pr-1",
                        "artifact-commit-1",
                        "artifact-review-note-1",
                    ]
                },
                "external_facts": deepcopy(_request_payload("accepted_completion")["request"]["external_facts"]),
                "claimed_completion": True,
                "acceptance_criteria_satisfied": True,
                "runtime_facts": deepcopy(initial_payload["request"]["runtime_facts"]),
            }
        }
        reevaluation_status, reevaluation_response = self.service.reevaluate(
            initial_response["task_envelope"]["id"],
            reevaluation_payload,
        )

        self.assertEqual(initial_status, 200)
        self.assertEqual(initial_response["task_envelope"]["status"], "blocked")
        self.assertEqual(reevaluation_status, 200)
        self.assertEqual(reevaluation_response["task_envelope"]["status"], "blocked")
        self.assertEqual(reevaluation_response["action"], "no_op")
        evidence = reevaluation_response["task_envelope"]["artifacts"]["completion_evidence"]
        self.assertEqual(evidence["validated_artifact_ids"], ["artifact-pr-1", "artifact-commit-1"])
        self.assertEqual(evidence["status"], "satisfied")

    def test_service_evaluate_strips_executor_verified_status_from_support_artifacts(self) -> None:
        support_artifact = _review_note_artifact("artifact-review-note-evaluate-1")
        support_artifact["provenance"] = {
            "source_system": "codex",
            "source_type": "executor_report",
            "source_id": "evaluate/self-certified-review-note-1",
            "captured_by": "harness-api",
        }
        task_envelope = create_task_envelope(
            {
                "id": "task-evaluate-support-artifact-1",
                "title": "Evaluate support artifact trust",
                "description": "Direct evaluation should not self-certify support artifacts.",
                "origin": {
                    "source_system": "openclaw",
                    "source_type": "ingress_request",
                    "source_id": "req-evaluate-support-artifact-1",
                },
                "acceptance_criteria": [
                    {
                        "id": "ac-1",
                        "description": "Completion requires a verified review note artifact.",
                        "required": True,
                    }
                ],
            },
            now="2026-04-07T21:00:00Z",
        )
        task_envelope["artifacts"]["completion_evidence"] = {
            "policy": "required",
            "status": "deferred",
            "required_artifact_types": ["review_note"],
            "validated_artifact_ids": [],
            "validation_method": "deferred",
            "validated_at": None,
            "validator": None,
            "notes": None,
        }

        status, response = self.service.evaluate(
            {
                "request": {
                    "task_envelope": task_envelope,
                    "linked_artifacts": [support_artifact],
                    "completion_evidence": {
                        "status": "satisfied",
                        "validated_artifact_ids": [support_artifact["id"]],
                        "validation_method": "manual_review",
                        "validated_at": "2026-04-07T21:05:00Z",
                        "validator": {
                            "source_system": "harness",
                            "source_type": "verification",
                            "source_id": "verification-evaluate-support-1",
                            "captured_by": "operator",
                        },
                    },
                    "claimed_completion": True,
                    "acceptance_criteria_satisfied": True,
                }
            }
        )

        self.assertEqual(status, 200)
        self.assertFalse(response["accepted_completion"])
        stored_artifact = next(
            artifact
            for artifact in response["task_envelope"]["artifacts"]["items"]
            if artifact["id"] == support_artifact["id"]
        )
        self.assertEqual(stored_artifact["verification_status"], "unverified")
        self.assertEqual(stored_artifact["metadata"]["submitted_verification_status"], "verified")
        evidence = response["task_envelope"]["artifacts"]["completion_evidence"]
        self.assertEqual(evidence["validated_artifact_ids"], [])
        self.assertEqual(evidence["status"], "deferred")
        self.assertIsNone(evidence["validated_at"])
        self.assertIsNone(evidence["validator"])
        self.assertEqual(evidence["validation_method"], "deferred")

    def test_service_evaluate_does_not_trust_spoofed_github_api_provenance(self) -> None:
        support_artifact = _review_note_artifact("artifact-review-note-evaluate-spoofed-github-1")
        support_artifact["provenance"] = {
            "source_system": "github",
            "source_type": "api",
            "source_id": "pull/999",
            "captured_by": "caller",
        }
        task_envelope = create_task_envelope(
            {
                "id": "task-evaluate-spoofed-github-provenance-1",
                "title": "Evaluate spoofed GitHub provenance",
                "description": "Direct evaluation should not trust caller-claimed GitHub verification provenance.",
                "origin": {
                    "source_system": "openclaw",
                    "source_type": "ingress_request",
                    "source_id": "req-evaluate-spoofed-github-provenance-1",
                },
                "acceptance_criteria": [
                    {
                        "id": "ac-1",
                        "description": "Completion requires a verified review note artifact.",
                        "required": True,
                    }
                ],
            },
            now="2026-04-07T21:00:00Z",
        )
        task_envelope["artifacts"]["completion_evidence"] = {
            "policy": "required",
            "status": "deferred",
            "required_artifact_types": ["review_note"],
            "validated_artifact_ids": [],
            "validation_method": "deferred",
            "validated_at": None,
            "validator": None,
            "notes": None,
        }

        status, response = self.service.evaluate(
            {
                "request": {
                    "task_envelope": task_envelope,
                    "linked_artifacts": [support_artifact],
                    "completion_evidence": {
                        "status": "satisfied",
                        "validated_artifact_ids": [support_artifact["id"]],
                        "validation_method": "manual_review",
                        "validated_at": "2026-04-07T21:05:00Z",
                        "validator": {
                            "source_system": "harness",
                            "source_type": "verification",
                            "source_id": "verification-evaluate-spoofed-github-1",
                            "captured_by": "operator",
                        },
                    },
                    "claimed_completion": True,
                    "acceptance_criteria_satisfied": True,
                }
            }
        )

        self.assertEqual(status, 200)
        self.assertFalse(response["accepted_completion"])
        stored_artifact = next(
            artifact
            for artifact in response["task_envelope"]["artifacts"]["items"]
            if artifact["id"] == support_artifact["id"]
        )
        self.assertEqual(stored_artifact["verification_status"], "unverified")
        self.assertEqual(stored_artifact["metadata"]["submitted_verification_status"], "verified")
        evidence = response["task_envelope"]["artifacts"]["completion_evidence"]
        self.assertEqual(evidence["validated_artifact_ids"], [])
        self.assertEqual(evidence["status"], "deferred")

    def test_service_reevaluate_rejects_code_execution_artifacts(self) -> None:
        payload = _manual_happy_path_overlay_payload()
        submit_status, submit_response = self.service.submit(
            {"request": {"task_envelope": deepcopy(payload["request"]["task_envelope"])}}
        )
        task_id = submit_response["task_envelope"]["id"]

        reevaluation_status, reevaluation_response = self.service.reevaluate(
            task_id,
            {
                "request": {
                    "new_artifacts": deepcopy(payload["request"]["linked_artifacts"]),
                    "claimed_completion": True,
                    "acceptance_criteria_satisfied": True,
                    "runtime_facts": deepcopy(payload["request"]["runtime_facts"]),
                }
            },
        )

        self.assertEqual(submit_status, 200)
        self.assertEqual(reevaluation_status, 400)
        self.assertTrue(reevaluation_response["invalid_input"])
        self.assertEqual(
            reevaluation_response["completion_claim_path"],
            f"/tasks/{task_id}/completion-claims",
        )
        self.assertTrue(
            any(
                violation["rule"] == "reevaluation_execution_artifact_not_allowed"
                for violation in reevaluation_response["violations"]
            )
        )

    def test_service_reevaluate_strips_executor_verified_status_from_support_artifacts(self) -> None:
        task_envelope = create_task_envelope(
            {
                "id": "task-reevaluate-support-artifact-1",
                "title": "Reevaluation support artifact trust",
                "description": "Reevaluation should not self-certify support artifacts.",
                "origin": {
                    "source_system": "openclaw",
                    "source_type": "ingress_request",
                    "source_id": "req-reevaluate-support-artifact-1",
                },
                "acceptance_criteria": [
                    {
                        "id": "ac-1",
                        "description": "Completion requires a verified review note.",
                        "required": True,
                    }
                ],
            },
            now="2026-04-07T21:10:00Z",
        )
        task_envelope["artifacts"]["completion_evidence"] = {
            "policy": "required",
            "status": "deferred",
            "required_artifact_types": ["review_note"],
            "validated_artifact_ids": [],
            "validation_method": "deferred",
            "validated_at": None,
            "validator": None,
            "notes": None,
        }
        submit_status, submit_response = self.service.submit({"request": {"task_envelope": task_envelope}})
        task_id = submit_response["task_envelope"]["id"]

        support_artifact = _review_note_artifact("artifact-review-note-reevaluate-1")
        support_artifact["provenance"] = {
            "source_system": "codex",
            "source_type": "executor_report",
            "source_id": "reevaluate/self-certified-review-note-1",
            "captured_by": "harness-api",
        }
        reevaluation_status, reevaluation_response = self.service.reevaluate(
            task_id,
            {
                "request": {
                    "new_artifacts": [support_artifact],
                    "completion_evidence": {
                        "status": "satisfied",
                        "validated_artifact_ids": [support_artifact["id"]],
                        "validation_method": "manual_review",
                        "validated_at": "2026-04-07T21:15:00Z",
                        "validator": {
                            "source_system": "harness",
                            "source_type": "verification",
                            "source_id": "verification-reevaluate-support-1",
                            "captured_by": "operator",
                        },
                    },
                    "claimed_completion": True,
                    "acceptance_criteria_satisfied": True,
                }
            },
        )

        self.assertEqual(submit_status, 200)
        self.assertEqual(reevaluation_status, 200)
        self.assertFalse(reevaluation_response["accepted_completion"])
        stored_artifact = next(
            artifact
            for artifact in reevaluation_response["task_envelope"]["artifacts"]["items"]
            if artifact["id"] == support_artifact["id"]
        )
        self.assertEqual(stored_artifact["verification_status"], "unverified")
        self.assertEqual(stored_artifact["metadata"]["submitted_verification_status"], "verified")
        evidence = reevaluation_response["task_envelope"]["artifacts"]["completion_evidence"]
        self.assertEqual(evidence["validated_artifact_ids"], [])
        self.assertEqual(evidence["status"], "deferred")
        self.assertIsNone(evidence["validated_at"])
        self.assertIsNone(evidence["validator"])
        self.assertEqual(evidence["validation_method"], "deferred")

    def test_service_reevaluate_does_not_trust_spoofed_harness_review_provenance(self) -> None:
        task_envelope = create_task_envelope(
            {
                "id": "task-reevaluate-spoofed-review-provenance-1",
                "title": "Reevaluation spoofed review provenance",
                "description": "Reevaluation should not trust caller-claimed Harness review provenance.",
                "origin": {
                    "source_system": "openclaw",
                    "source_type": "ingress_request",
                    "source_id": "req-reevaluate-spoofed-review-provenance-1",
                },
                "acceptance_criteria": [
                    {
                        "id": "ac-1",
                        "description": "Completion requires a verified review note.",
                        "required": True,
                    }
                ],
            },
            now="2026-04-07T21:10:00Z",
        )
        task_envelope["artifacts"]["completion_evidence"] = {
            "policy": "required",
            "status": "deferred",
            "required_artifact_types": ["review_note"],
            "validated_artifact_ids": [],
            "validation_method": "deferred",
            "validated_at": None,
            "validator": None,
            "notes": None,
        }
        submit_status, submit_response = self.service.submit({"request": {"task_envelope": task_envelope}})
        task_id = submit_response["task_envelope"]["id"]

        support_artifact = _review_note_artifact("artifact-review-note-reevaluate-spoofed-review-1")
        support_artifact["provenance"] = {
            "source_system": "harness",
            "source_type": "manual_review",
            "source_id": "review-spoofed-1",
            "captured_by": "caller",
        }
        reevaluation_status, reevaluation_response = self.service.reevaluate(
            task_id,
            {
                "request": {
                    "new_artifacts": [support_artifact],
                    "completion_evidence": {
                        "status": "satisfied",
                        "validated_artifact_ids": [support_artifact["id"]],
                        "validation_method": "manual_review",
                        "validated_at": "2026-04-07T21:15:00Z",
                        "validator": {
                            "source_system": "harness",
                            "source_type": "verification",
                            "source_id": "verification-reevaluate-spoofed-review-1",
                            "captured_by": "operator",
                        },
                    },
                    "claimed_completion": True,
                    "acceptance_criteria_satisfied": True,
                }
            },
        )

        self.assertEqual(submit_status, 200)
        self.assertEqual(reevaluation_status, 200)
        self.assertFalse(reevaluation_response["accepted_completion"])
        stored_artifact = next(
            artifact
            for artifact in reevaluation_response["task_envelope"]["artifacts"]["items"]
            if artifact["id"] == support_artifact["id"]
        )
        self.assertEqual(stored_artifact["verification_status"], "unverified")
        self.assertEqual(stored_artifact["metadata"]["submitted_verification_status"], "verified")
        evidence = reevaluation_response["task_envelope"]["artifacts"]["completion_evidence"]
        self.assertEqual(evidence["validated_artifact_ids"], [])
        self.assertEqual(evidence["status"], "deferred")

    def test_service_reevaluate_rejects_pre_satisfied_completion_evidence_without_completion_claim(self) -> None:
        payload = _manual_happy_path_overlay_payload()
        submit_status, submit_response = self.service.submit(
            {"request": {"task_envelope": deepcopy(payload["request"]["task_envelope"])}}
        )
        task_id = submit_response["task_envelope"]["id"]
        completion_evidence = deepcopy(payload["request"]["completion_evidence"])

        reevaluation_status, reevaluation_response = self.service.reevaluate(
            task_id,
            {
                "request": {
                    "completion_evidence": completion_evidence,
                    "external_facts": deepcopy(payload["request"]["external_facts"]),
                    "runtime_facts": deepcopy(payload["request"]["runtime_facts"]),
                }
            },
        )

        self.assertEqual(submit_status, 200)
        self.assertEqual(reevaluation_status, 400)
        self.assertTrue(reevaluation_response["invalid_input"])
        self.assertIn("claimed_completion", reevaluation_response["error"])

    def test_service_reevaluate_strips_executor_verified_status_from_code_artifacts(self) -> None:
        service = HarnessApiService(store=FileBackedHarnessStore(self.temp_dir.name))
        task_envelope = create_task_envelope(
            {
                "id": "task-reevaluate-code-artifact-1",
                "title": "Reevaluation code artifact trust",
                "description": "Reevaluation should not self-certify code-bearing artifacts.",
                "origin": {
                    "source_system": "openclaw",
                    "source_type": "ingress_request",
                    "source_id": "req-reevaluate-code-artifact-1",
                },
                "acceptance_criteria": [
                    {
                        "id": "ac-1",
                        "description": "Completion requires a verified pull request.",
                        "required": True,
                    }
                ],
            },
            now="2026-04-07T19:00:00Z",
        )
        task_envelope["artifacts"]["completion_evidence"] = {
            "policy": "required",
            "status": "deferred",
            "required_artifact_types": ["pull_request"],
            "validated_artifact_ids": [],
            "validation_method": "deferred",
            "validated_at": None,
            "validator": None,
            "notes": None,
        }
        submit_status, submit_response = service.submit({"request": {"task_envelope": task_envelope}})
        task_id = submit_response["task_envelope"]["id"]

        pr_artifact = deepcopy(_manual_happy_path_overlay_payload()["request"]["linked_artifacts"][0])
        pr_artifact["provenance"] = {
            "source_system": "codex",
            "source_type": "executor_report",
            "source_id": "reevaluate/self-certified-pr-1",
            "captured_by": "harness-api",
        }
        reevaluation_status, reevaluation_response = service.reevaluate(
            task_id,
            {
                "request": {
                    "new_artifacts": [pr_artifact],
                    "completion_evidence": {
                        "status": "satisfied",
                        "validated_artifact_ids": [pr_artifact["id"]],
                        "validation_method": "manual_review",
                        "validated_at": "2026-04-07T19:05:00Z",
                        "validator": {
                            "source_system": "harness",
                            "source_type": "verification",
                            "source_id": "verification-reevaluate-code-1",
                            "captured_by": "operator",
                        },
                    },
                    "claimed_completion": True,
                    "acceptance_criteria_satisfied": True,
                }
            },
        )

        self.assertEqual(submit_status, 200)
        self.assertEqual(reevaluation_status, 200)
        self.assertFalse(reevaluation_response["accepted_completion"])
        stored_artifact = next(
            artifact
            for artifact in reevaluation_response["task_envelope"]["artifacts"]["items"]
            if artifact["id"] == pr_artifact["id"]
        )
        self.assertEqual(stored_artifact["verification_status"], "unverified")
        self.assertEqual(
            stored_artifact["metadata"]["submitted_verification_status"],
            "verified",
        )
        evidence = reevaluation_response["task_envelope"]["artifacts"]["completion_evidence"]
        self.assertEqual(evidence["validated_artifact_ids"], [])
        self.assertEqual(evidence["status"], "deferred")
        self.assertIsNone(evidence["validated_at"])
        self.assertIsNone(evidence["validator"])
        self.assertEqual(evidence["validation_method"], "deferred")

    def test_service_reevaluate_canonicalizes_unresolved_conditions_into_clarification(self) -> None:
        submit_payload = {"request": {"task_envelope": deepcopy(_manual_happy_path_overlay_payload()["request"]["task_envelope"])}}
        submit_status, submit_response = self.service.submit(submit_payload)
        task_id = submit_response["task_envelope"]["id"]

        reevaluation_status, reevaluation_response = self.service.reevaluate(
            task_id,
            {"request": {"unresolved_conditions": ["Need repository clarification before proceeding."]}},
        )

        self.assertEqual(submit_status, 200)
        self.assertEqual(reevaluation_status, 200)
        self.assertEqual(reevaluation_response["task_envelope"]["status"], "blocked")
        clarification = reevaluation_response["task_envelope"]["clarification"]
        self.assertEqual(clarification["status"], "required")
        self.assertEqual(clarification["resume_target_status"], "intake_ready")
        self.assertEqual(clarification["required_inputs"][0]["description"], "Need repository clarification before proceeding.")
        self.assertEqual(
            reevaluation_response["enforcement_result"]["verification_result"]["outcome"],
            "verification_deferred",
        )

    def test_service_reevaluate_resolves_clarification_when_conditions_are_cleared(self) -> None:
        submit_payload = {"request": {"task_envelope": deepcopy(_manual_happy_path_overlay_payload()["request"]["task_envelope"])}}
        submit_status, submit_response = self.service.submit(submit_payload)
        task_id = submit_response["task_envelope"]["id"]

        blocked_status, blocked_response = self.service.reevaluate(
            task_id,
            {"request": {"unresolved_conditions": ["Need repository clarification before proceeding."]}},
        )
        resolved_status, resolved_response = self.service.reevaluate(
            task_id,
            {"request": {"claimed_completion": False, "acceptance_criteria_satisfied": False}},
        )

        self.assertEqual(submit_status, 200)
        self.assertEqual(blocked_status, 200)
        self.assertEqual(resolved_status, 200)
        self.assertEqual(resolved_response["task_envelope"]["status"], "intake_ready")
        clarification = resolved_response["task_envelope"]["clarification"]
        self.assertEqual(clarification["status"], "resolved")
        self.assertEqual(
            clarification["resolution_summary"],
            "Clarification requirements were cleared by the reevaluation input.",
        )
        self.assertIsNotNone(clarification["resolved_at"])
        self.assertEqual(clarification["required_inputs"][0]["status"], "provided")

    def test_service_reevaluate_resumes_dispatch_ready_clarification_and_auto_dispatches(self) -> None:
        payload = _manual_ingress_payload(task_id="task-clarification-resume-dispatch-1")
        payload["task_status"] = "dispatch_ready"
        payload["unresolved_conditions"] = ["Need repository clarification before dispatch can begin."]

        submit_status, submit_response = self.service.submit_manual_ingress(payload)
        task_id = submit_response["task_envelope"]["id"]

        resolved_status, resolved_response = self.service.reevaluate(
            task_id,
            {"request": {"claimed_completion": False, "acceptance_criteria_satisfied": False}},
        )
        read_status, read_payload = self.service.get_task_read_model(task_id)
        timeline_status, timeline_payload = self.service.get_task_timeline(task_id)

        self.assertEqual(submit_status, 200)
        self.assertEqual(submit_response["task_envelope"]["status"], "blocked")
        self.assertEqual(resolved_status, 200)
        self.assertNotIn(resolved_response["task_envelope"]["status"], {"blocked", "dispatch_ready"})
        self.assertTrue(resolved_response["automatic_dispatch"]["attempted"])
        self.assertEqual(resolved_response["automatic_dispatch"]["status"], 200)
        self.assertEqual(resolved_response["automatic_dispatch"]["dispatch"]["attempt_id"], "attempt-1")
        clarification = resolved_response["task_envelope"]["clarification"]
        self.assertEqual(clarification["status"], "resolved")
        self.assertEqual(clarification["resume_target_status"], "dispatch_ready")
        self.assertEqual(read_status, 200)
        self.assertNotIn(read_payload["task"]["current_status"], {"blocked", "dispatch_ready"})
        self.assertEqual(read_payload["task"]["execution_summary"]["attempt_count"], 1)
        self.assertEqual(timeline_status, 200)
        dispatch_events = [event for event in timeline_payload["timeline"] if event["event_type"] == "task_dispatched"]
        self.assertTrue(dispatch_events)
        self.assertEqual(dispatch_events[-1]["details"]["dispatch_trigger"], "automatic_policy_post_reevaluation")

    def test_service_reevaluate_resumes_assigned_clarification_to_active_assignment(self) -> None:
        submit_payload = {"request": {"task_envelope": deepcopy(_manual_happy_path_overlay_payload()["request"]["task_envelope"])}}
        submit_status, submit_response = self.service.submit(submit_payload)
        task_id = submit_response["task_envelope"]["id"]

        stored_task = deepcopy(self.service.store.get_task(task_id))
        stored_task["status"] = "assigned"
        stored_task["assigned_executor"] = {
            "executor_type": "codex",
            "executor_id": "executor-clarification-resume-1",
            "assignment_reason": "Resume active assignment after clarification.",
        }
        self.service.store.update_task(stored_task)

        blocked_status, blocked_response = self.service.reevaluate(
            task_id,
            {"request": {"unresolved_conditions": ["Need clarification before the assigned work can continue."]}},
        )
        resolved_status, resolved_response = self.service.reevaluate(
            task_id,
            {"request": {"claimed_completion": False, "acceptance_criteria_satisfied": False}},
        )
        read_status, read_payload = self.service.get_task_read_model(task_id)

        self.assertEqual(submit_status, 200)
        self.assertEqual(blocked_status, 200)
        self.assertEqual(blocked_response["task_envelope"]["status"], "blocked")
        self.assertEqual(blocked_response["task_envelope"]["clarification"]["resume_target_status"], "assigned")
        self.assertEqual(resolved_status, 200)
        self.assertEqual(resolved_response["task_envelope"]["status"], "assigned")
        self.assertEqual(resolved_response["task_envelope"]["assigned_executor"]["executor_id"], "executor-clarification-resume-1")
        self.assertEqual(resolved_response["task_envelope"]["clarification"]["status"], "resolved")
        self.assertNotIn("automatic_dispatch", resolved_response)
        self.assertEqual(read_status, 200)
        self.assertEqual(read_payload["task"]["current_status"], "assigned")

    def test_service_evaluate_existing_task_rejects_top_level_overlays(self) -> None:
        payload = _manual_happy_path_overlay_payload()
        evaluate_payload = deepcopy(payload)
        del evaluate_payload["request"]["task_status"]
        submit_payload = {"request": {"task_envelope": deepcopy(payload["request"]["task_envelope"])}}

        submit_status, submit_response = self.service.submit(submit_payload)
        evaluate_status, evaluate_response = self.service.evaluate(evaluate_payload)

        self.assertEqual(submit_status, 200)
        self.assertEqual(submit_response["task_envelope"]["status"], "intake_ready")
        self.assertEqual(evaluate_status, 400)
        self.assertTrue(evaluate_response["invalid_input"])
        self.assertIn("/tasks/task-http-happy-overlay-1/reevaluate", evaluate_response["error"])
        violation_rules = {violation["rule"] for violation in evaluate_response["violations"]}
        self.assertEqual(violation_rules, {"existing_task_overlay_not_allowed"})
        violation_sources = {violation["source"] for violation in evaluate_response["violations"]}
        self.assertEqual(
            violation_sources,
            {
                "request.assigned_executor",
                "request.linked_artifacts",
                "request.completion_evidence",
            },
        )

    def test_service_reevaluate_rejects_code_execution_artifacts_for_intake_ready_task(self) -> None:
        payload = _manual_happy_path_overlay_payload()
        submit_payload = {"request": {"task_envelope": deepcopy(payload["request"]["task_envelope"])}}

        submit_status, submit_response = self.service.submit(submit_payload)
        task_id = submit_response["task_envelope"]["id"]
        reevaluation_payload = {
            "request": {
                "new_artifacts": deepcopy(payload["request"]["linked_artifacts"]),
                "completion_evidence": deepcopy(payload["request"]["completion_evidence"]),
                "external_facts": deepcopy(payload["request"]["external_facts"]),
                "claimed_completion": True,
                "acceptance_criteria_satisfied": True,
                "runtime_facts": deepcopy(payload["request"]["runtime_facts"]),
            }
        }

        reevaluation_status, reevaluation_response = self.service.reevaluate(task_id, reevaluation_payload)

        self.assertEqual(submit_status, 200)
        self.assertEqual(submit_response["task_envelope"]["status"], "intake_ready")
        self.assertEqual(reevaluation_status, 400)
        self.assertTrue(reevaluation_response["invalid_input"])
        self.assertEqual(
            reevaluation_response["completion_claim_path"],
            f"/tasks/{task_id}/completion-claims",
        )
        self.assertTrue(
            any(
                violation["rule"] == "reevaluation_execution_artifact_not_allowed"
                for violation in reevaluation_response["violations"]
            )
        )

    def test_service_reevaluate_rejects_submission_style_mutation_fields(self) -> None:
        payload = _manual_happy_path_overlay_payload()
        submit_payload = {"request": {"task_envelope": deepcopy(payload["request"]["task_envelope"])}}
        submit_status, submit_response = self.service.submit(submit_payload)
        task_id = submit_response["task_envelope"]["id"]

        reevaluation_status, reevaluation_response = self.service.reevaluate(
            task_id,
            {
                "request": {
                    "task_envelope": deepcopy(submit_response["task_envelope"]),
                    "task_status": "completed",
                    "assigned_executor": {
                        "executor_type": "codex",
                        "executor_id": "executor-bad-reevaluate-1",
                    },
                    "linked_artifacts": deepcopy(payload["request"]["linked_artifacts"]),
                }
            },
        )

        self.assertEqual(submit_status, 200)
        self.assertEqual(reevaluation_status, 400)
        self.assertTrue(reevaluation_response["invalid_input"])
        self.assertIn(f"/tasks/{task_id}/reevaluate", reevaluation_response["error"])
        violation_sources = {violation["source"] for violation in reevaluation_response["violations"]}
        self.assertEqual(
            violation_sources,
            {
                "request.task_envelope",
                "request.task_status",
                "request.assigned_executor",
                "request.linked_artifacts",
            },
        )

    def test_service_completion_claim_is_intercepted_and_cannot_directly_complete_task(self) -> None:
        payload = _manual_happy_path_overlay_payload()
        submit_payload = {"request": {"task_envelope": deepcopy(payload["request"]["task_envelope"])}}
        submit_status, submit_response = self.service.submit(submit_payload)
        task_id = submit_response["task_envelope"]["id"]

        claim_status, claim_response = self.service.submit_completion_claim(
            task_id,
            {
                "request": {
                    **_completion_claim_payload(claim_id="claim-intercepted-1"),
                    "runtime_facts": {"executor_reported_success": True, "attempt_count": 1},
                }
            },
        )

        self.assertEqual(submit_status, 200)
        self.assertEqual(claim_status, 200)
        self.assertFalse(claim_response["accepted_completion"])
        self.assertNotEqual(claim_response["task_envelope"]["status"], "completed")
        claims = claim_response["task_envelope"]["observability"]["execution_metadata"]["advisory_completion_claims"]
        self.assertEqual(claims[-1]["claim_id"], "claim-intercepted-1")

    def test_service_completion_claim_rejects_submission_style_mutation_fields(self) -> None:
        payload = _manual_happy_path_overlay_payload()
        submit_payload = {"request": {"task_envelope": deepcopy(payload["request"]["task_envelope"])}}
        submit_status, submit_response = self.service.submit(submit_payload)
        task_id = submit_response["task_envelope"]["id"]

        claim_status, claim_response = self.service.submit_completion_claim(
            task_id,
            {
                "request": {
                    **_completion_claim_payload(claim_id="claim-bad-shape-1"),
                    "task_envelope": deepcopy(submit_response["task_envelope"]),
                    "task_status": "completed",
                    "assigned_executor": {
                        "executor_type": "codex",
                        "executor_id": "executor-bad-claim-1",
                    },
                    "linked_artifacts": deepcopy(payload["request"]["linked_artifacts"]),
                }
            },
        )

        self.assertEqual(submit_status, 200)
        self.assertEqual(claim_status, 400)
        self.assertTrue(claim_response["invalid_input"])
        self.assertIn(f"/tasks/{task_id}/completion-claims", claim_response["error"])
        violation_sources = {violation["source"] for violation in claim_response["violations"]}
        self.assertEqual(
            violation_sources,
            {
                "request.task_envelope",
                "request.task_status",
                "request.assigned_executor",
                "request.linked_artifacts",
            },
        )

    def test_service_completion_claim_routes_into_canonical_evaluation_and_can_complete_when_evidence_aligns(self) -> None:
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_current_run_pull_request_gateway(),
        )
        payload = _manual_happy_path_overlay_payload()
        submit_payload = {"request": {"task_envelope": deepcopy(payload["request"]["task_envelope"])}}
        submit_status, submit_response = service.submit(submit_payload)
        task_id = submit_response["task_envelope"]["id"]

        claim_status, claim_response = service.submit_completion_claim(
            task_id,
            {
                "request": {
                    **_completion_claim_payload(claim_id="claim-complete-1"),
                    **_execution_attempt_payload(attempt_id="attempt-complete-1"),
                    "new_artifacts": deepcopy(payload["request"]["linked_artifacts"]),
                    "completion_evidence": deepcopy(payload["request"]["completion_evidence"]),
                    "external_facts": deepcopy(payload["request"]["external_facts"]),
                    "acceptance_criteria_satisfied": True,
                    "runtime_facts": deepcopy(payload["request"]["runtime_facts"]),
                }
            },
        )
        history_status, history_payload = service.get_evaluation_history(task_id)
        latest_request = history_payload["evaluations"][-1]["request"]

        self.assertEqual(submit_status, 200)
        self.assertEqual(claim_status, 200)
        self.assertTrue(claim_response["accepted_completion"])
        self.assertEqual(claim_response["task_envelope"]["status"], "completed")
        self.assertEqual(history_status, 200)
        self.assertTrue(latest_request["claimed_completion"])
        claims = latest_request["task_envelope"]["observability"]["execution_metadata"]["advisory_completion_claims"]
        self.assertEqual(claims[-1]["claim_id"], "claim-complete-1")

    def test_service_completion_claim_canonicalizes_unresolved_conditions_into_clarification(self) -> None:
        submit_payload = {"request": {"task_envelope": deepcopy(_manual_happy_path_overlay_payload()["request"]["task_envelope"])}}
        submit_status, submit_response = self.service.submit(submit_payload)
        task_id = submit_response["task_envelope"]["id"]

        claim_status, claim_response = self.service.submit_completion_claim(
            task_id,
            {
                "request": {
                    **_completion_claim_payload(claim_id="claim-clarification-1"),
                    "runtime_facts": {"executor_reported_success": True, "attempt_count": 1},
                    "unresolved_conditions": ["Need repository clarification before proceeding."],
                }
            },
        )

        self.assertEqual(submit_status, 200)
        self.assertEqual(claim_status, 200)
        self.assertFalse(claim_response["accepted_completion"])
        self.assertEqual(claim_response["task_envelope"]["status"], "blocked")
        clarification = claim_response["task_envelope"]["clarification"]
        self.assertEqual(clarification["status"], "required")
        self.assertEqual(clarification["resume_target_status"], "intake_ready")
        self.assertEqual(clarification["required_inputs"][0]["description"], "Need repository clarification before proceeding.")

    def test_service_completion_claim_resolves_clarification_when_conditions_are_cleared(self) -> None:
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_current_run_pull_request_gateway(),
        )
        submit_payload = {"request": {"task_envelope": deepcopy(_manual_happy_path_overlay_payload()["request"]["task_envelope"])}}
        submit_status, submit_response = service.submit(submit_payload)
        task_id = submit_response["task_envelope"]["id"]

        blocked_status, blocked_response = service.submit_completion_claim(
            task_id,
            {
                "request": {
                    **_completion_claim_payload(claim_id="claim-clarification-blocked-1"),
                    "runtime_facts": {"executor_reported_success": True, "attempt_count": 1},
                    "unresolved_conditions": ["Need repository clarification before proceeding."],
                }
            },
        )

        resolved_status, resolved_response = service.submit_completion_claim(
            task_id,
            {
                "request": {
                    **_completion_claim_payload(claim_id="claim-clarification-resolved-1"),
                    **_execution_attempt_payload(attempt_id="attempt-clarification-resolved-1"),
                    "new_artifacts": deepcopy(_manual_happy_path_overlay_payload()["request"]["linked_artifacts"]),
                    "completion_evidence": deepcopy(_manual_happy_path_overlay_payload()["request"]["completion_evidence"]),
                    "external_facts": deepcopy(_manual_happy_path_overlay_payload()["request"]["external_facts"]),
                    "runtime_facts": deepcopy(_manual_happy_path_overlay_payload()["request"]["runtime_facts"]),
                    "acceptance_criteria_satisfied": True,
                }
            },
        )

        self.assertEqual(submit_status, 200)
        self.assertEqual(blocked_status, 200)
        self.assertFalse(blocked_response["accepted_completion"])
        self.assertEqual(resolved_status, 200)
        self.assertTrue(resolved_response["accepted_completion"])
        clarification = resolved_response["task_envelope"]["clarification"]
        self.assertEqual(clarification["status"], "resolved")
        self.assertEqual(
            clarification["resolution_summary"],
            "Clarification requirements were cleared by the completion claim input.",
        )
        self.assertIsNotNone(clarification["resolved_at"])

    def test_service_completion_claim_reconciles_missing_commit_artifact_when_verified_pr_exists(self) -> None:
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_current_run_pull_request_gateway(),
        )
        payload = _manual_happy_path_overlay_payload()
        submit_payload = {"request": {"task_envelope": deepcopy(payload["request"]["task_envelope"])}}
        submit_status, submit_response = service.submit(submit_payload)
        task_id = submit_response["task_envelope"]["id"]

        pr_artifact = deepcopy(payload["request"]["linked_artifacts"][0])
        stored_task = deepcopy(service.store.get_task(task_id))
        stored_task["artifacts"]["items"] = [pr_artifact]
        service.store.update_task(stored_task)
        completion_evidence = deepcopy(payload["request"]["completion_evidence"])
        completion_evidence["validated_artifact_ids"] = [pr_artifact["id"]]

        claim_status, claim_response = service.submit_completion_claim(
            task_id,
            {
                "request": {
                    **_completion_claim_payload(claim_id="claim-missing-commit-1"),
                    **_execution_attempt_payload(attempt_id="attempt-1"),
                    "completion_evidence": completion_evidence,
                    "external_facts": deepcopy(payload["request"]["external_facts"]),
                    "acceptance_criteria_satisfied": True,
                    "runtime_facts": deepcopy(payload["request"]["runtime_facts"]),
                }
            },
        )

        self.assertEqual(submit_status, 200)
        self.assertEqual(claim_status, 200)
        self.assertTrue(claim_response["accepted_completion"])
        self.assertEqual(claim_response["task_envelope"]["status"], "completed")
        attempt = claim_response["task_envelope"]["reconciliation"]["attempts"][-1]
        self.assertEqual(attempt["failure_type"], "missing_commit_after_execution")
        evidence = claim_response["task_envelope"]["artifacts"]["completion_evidence"]
        self.assertEqual(evidence["validation_method"], "external_reconciliation")
        self.assertEqual(evidence["status"], "satisfied")
        self.assertIsNotNone(evidence["validated_at"])
        self.assertEqual(evidence["validator"]["source_system"], "harness")
        commit_artifacts = [
            artifact
            for artifact in claim_response["task_envelope"]["artifacts"]["items"]
            if isinstance(artifact, dict) and artifact.get("type") == "commit"
        ]
        self.assertEqual(len(commit_artifacts), 1)
        self.assertIn(
            commit_artifacts[0]["id"],
            claim_response["task_envelope"]["artifacts"]["completion_evidence"]["validated_artifact_ids"],
        )

    def test_service_completion_claim_reconciles_self_certified_commit_artifact_when_verified_pr_exists(self) -> None:
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_current_run_pull_request_gateway(),
        )
        payload = _manual_happy_path_overlay_payload()
        submit_status, submit_response = service.submit(
            {"request": {"task_envelope": deepcopy(payload["request"]["task_envelope"])}}
        )
        task_id = submit_response["task_envelope"]["id"]

        pr_artifact = deepcopy(payload["request"]["linked_artifacts"][0])
        stored_task = deepcopy(service.store.get_task(task_id))
        stored_task["artifacts"]["items"] = [pr_artifact]
        service.store.update_task(stored_task)

        commit_artifact = deepcopy(payload["request"]["linked_artifacts"][1])
        completion_evidence = deepcopy(payload["request"]["completion_evidence"])
        completion_evidence["validated_artifact_ids"] = [pr_artifact["id"], commit_artifact["id"]]

        claim_status, claim_response = service.submit_completion_claim(
            task_id,
            {
                "request": {
                    **_completion_claim_payload(claim_id="claim-self-certified-commit-1"),
                    **_execution_attempt_payload(attempt_id="attempt-self-certified-commit-1"),
                    "new_artifacts": [commit_artifact],
                    "completion_evidence": completion_evidence,
                    "external_facts": deepcopy(payload["request"]["external_facts"]),
                    "acceptance_criteria_satisfied": True,
                    "runtime_facts": deepcopy(payload["request"]["runtime_facts"]),
                }
            },
        )

        self.assertEqual(submit_status, 200)
        self.assertEqual(claim_status, 200)
        self.assertTrue(claim_response["accepted_completion"])
        attempts = claim_response["task_envelope"]["reconciliation"]["attempts"]
        self.assertEqual(attempts[-1]["failure_type"], "missing_commit_after_execution")
        commit_artifact = next(
            artifact
            for artifact in claim_response["task_envelope"]["artifacts"]["items"]
            if isinstance(artifact, dict) and artifact.get("type") == "commit"
        )
        self.assertEqual(commit_artifact["id"], "artifact-commit-dryrun-1")
        self.assertEqual(commit_artifact["verification_status"], "verified")
        self.assertEqual(commit_artifact["metadata"]["attached_by"], "missing_commit_after_execution")
        self.assertIn(
            "artifact-commit-dryrun-1",
            claim_response["task_envelope"]["artifacts"]["completion_evidence"]["validated_artifact_ids"],
        )

    def test_service_completion_claim_reconciles_self_certified_pr_and_commit_artifacts_sequentially(self) -> None:
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_current_run_pull_request_gateway(),
        )
        payload = _manual_happy_path_overlay_payload()
        submit_status, submit_response = service.submit(
            {"request": {"task_envelope": deepcopy(payload["request"]["task_envelope"])}}
        )
        task_id = submit_response["task_envelope"]["id"]

        claim_status, claim_response = service.submit_completion_claim(
            task_id,
            {
                "request": {
                    **_completion_claim_payload(claim_id="claim-self-certified-pr-commit-1"),
                    **_execution_attempt_payload(attempt_id="attempt-self-certified-pr-commit-1"),
                    "new_artifacts": deepcopy(payload["request"]["linked_artifacts"]),
                    "completion_evidence": deepcopy(payload["request"]["completion_evidence"]),
                    "external_facts": deepcopy(payload["request"]["external_facts"]),
                    "acceptance_criteria_satisfied": True,
                    "runtime_facts": deepcopy(payload["request"]["runtime_facts"]),
                }
            },
        )

        self.assertEqual(submit_status, 200)
        self.assertEqual(claim_status, 200)
        self.assertTrue(claim_response["accepted_completion"])
        attempts = claim_response["task_envelope"]["reconciliation"]["attempts"]
        self.assertEqual(
            [attempt["failure_type"] for attempt in attempts[-2:]],
            ["missing_pr_after_execution", "missing_commit_after_execution"],
        )
        evidence = claim_response["task_envelope"]["artifacts"]["completion_evidence"]
        evidence_ids = evidence["validated_artifact_ids"]
        self.assertIn("artifact-pr-dryrun-1", evidence_ids)
        self.assertIn("artifact-commit-dryrun-1", evidence_ids)
        self.assertEqual(evidence["validation_method"], "external_reconciliation")
        self.assertEqual(evidence["status"], "satisfied")
        self.assertEqual(evidence["validator"]["captured_by"], "reconciliation")
        commit_artifact = next(
            artifact
            for artifact in claim_response["task_envelope"]["artifacts"]["items"]
            if isinstance(artifact, dict) and artifact.get("type") == "commit"
        )
        self.assertEqual(commit_artifact["metadata"]["attached_by"], "missing_commit_after_execution")

    def test_service_completion_claim_can_attach_execution_attempt_and_link_reevaluation(self) -> None:
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_current_run_pull_request_gateway(),
        )
        payload = _manual_happy_path_overlay_payload()
        submit_payload = {"request": {"task_envelope": deepcopy(payload["request"]["task_envelope"])}}
        submit_status, submit_response = service.submit(submit_payload)
        task_id = submit_response["task_envelope"]["id"]

        claim_status, claim_response = service.submit_completion_claim(
            task_id,
            {
                "request": {
                    **_completion_claim_payload(claim_id="claim-with-attempt-1"),
                    **_execution_attempt_payload(attempt_id="attempt-linked-1"),
                    "new_artifacts": deepcopy(payload["request"]["linked_artifacts"]),
                    "completion_evidence": deepcopy(payload["request"]["completion_evidence"]),
                    "external_facts": deepcopy(payload["request"]["external_facts"]),
                    "acceptance_criteria_satisfied": True,
                    "runtime_facts": deepcopy(payload["request"]["runtime_facts"]),
                }
            },
        )
        timeline_status, timeline_payload = service.get_task_timeline(task_id)

        self.assertEqual(submit_status, 200)
        self.assertEqual(claim_status, 200)
        self.assertTrue(claim_response["accepted_completion"])
        execution_attempts = claim_response["task_envelope"]["observability"]["execution_metadata"]["execution_attempts"]
        latest_attempt = execution_attempts[-1]
        self.assertEqual(latest_attempt["attempt_id"], "attempt-linked-1")
        self.assertEqual(latest_attempt["completion_claim_id"], "claim-with-attempt-1")
        self.assertEqual(latest_attempt["reevaluation"]["evaluation_id"], claim_response["evaluation_record"]["evaluation_id"])
        self.assertEqual(timeline_status, 200)
        execution_events = [
            event for event in timeline_payload["timeline"] if event["event_type"] == "execution_attempt_recorded"
        ]
        self.assertTrue(execution_events)

    def test_service_completion_claim_retries_invalid_execution_attempt_then_fails(self) -> None:
        payload = _manual_happy_path_overlay_payload()
        submit_payload = {
            "request": {
                "task_envelope": deepcopy(payload["request"]["task_envelope"]),
            }
        }
        submit_status, submit_response = self.service.submit(submit_payload)
        task_id = submit_response["task_envelope"]["id"]
        assigned_task = deepcopy(self.service.store.get_task(task_id))
        assigned_task["status"] = "assigned"
        assigned_task["assigned_executor"] = {
            "executor_type": "codex",
            "executor_id": "executor-invalid-attempt-1",
            "assignment_reason": "Exercise invalid execution attempt retries.",
        }
        assigned_task["timestamps"]["updated_at"] = "2026-04-01T10:03:00Z"
        self.service.store.update_task(assigned_task)
        assign_status, assign_response = self.service.get_task(task_id)
        invalid_attempt_payload = _execution_attempt_payload(attempt_id="attempt-invalid-1")
        invalid_attempt_payload["execution_attempt"]["artifact_references"] = [
            {
                "reference_id": "attempt-invalid-1:commit",
                "artifact_type": "commit",
                "location": "stub://attempts/attempt-invalid-1/commit",
                "metadata": {
                    "branch_name": "codex/e2e-test",
                },
            }
        ]

        with patch.dict(os.environ, {"HARNESS_INVALID_EXECUTION_RETRY_BUDGET": "1"}):
            claim_status, claim_response = self.service.submit_completion_claim(
                task_id,
                {
                    "request": {
                        **_completion_claim_payload(claim_id="claim-invalid-attempt-1"),
                        **invalid_attempt_payload,
                        "runtime_facts": {"executor_reported_success": True, "attempt_count": 1},
                    }
                },
            )
        history_status, history_payload = self.service.get_evaluation_history(task_id)
        read_status, read_payload = self.service.get_task_read_model(task_id)

        self.assertEqual(submit_status, 200)
        self.assertEqual(assign_status, 200)
        self.assertEqual(assign_response["task"]["status"], "assigned")
        self.assertEqual(claim_status, 200)
        self.assertEqual(claim_response["action"], "contract_violation_failed")
        self.assertEqual(claim_response["task_envelope"]["status"], "failed")
        self.assertEqual(claim_response["evaluation_record"]["result"]["failure_classification"]["failure_type"], "contract_violation")
        self.assertEqual(
            claim_response["invalid_execution_attempt"]["validation"]["failure_type"],
            "invalid_execution_attempt",
        )
        execution_attempts = claim_response["task_envelope"]["observability"]["execution_metadata"]["execution_attempts"]
        self.assertEqual(len(execution_attempts), 2)
        self.assertEqual(
            execution_attempts[0]["metadata"]["attempt_validation"]["failure_type"],
            "invalid_execution_attempt",
        )
        self.assertEqual(
            execution_attempts[-1]["metadata"]["attempt_validation"]["failure_type"],
            "contract_violation",
        )
        self.assertEqual(history_status, 200)
        self.assertGreaterEqual(len(history_payload["evaluations"]), 3)
        retry_records = [
            item for item in history_payload["evaluations"] if item["request"].get("retry_context") is not None
        ]
        self.assertTrue(retry_records)
        self.assertEqual(
            retry_records[-1]["request"]["retry_context"]["triggered_by_category"],
            "invalid_execution_attempt",
        )
        self.assertEqual(
            history_payload["evaluations"][-1]["result"]["failure_classification"]["failure_type"],
            "contract_violation",
        )
        self.assertEqual(read_status, 200)
        self.assertEqual(read_payload["task"]["execution_summary"]["invalid_attempt_count"], 1)
        self.assertEqual(
            read_payload["task"]["execution_summary"]["latest_attempt_validation"]["failure_type"],
            "contract_violation",
        )
        self.assertEqual(read_payload["task"]["failure_summary"]["failure_type"], "contract_violation")

    def test_service_completion_claim_invalid_execution_attempt_does_not_corrupt_canceled_task_truth(self) -> None:
        initial_payload = _request_payload("review_required")
        initial_payload["request"]["review_request"]["allowed_outcomes"] = [
            "accept_completion",
            "cancel_task",
        ]
        initial_status, initial_response = self.service.evaluate(initial_payload)
        task_id = initial_response["task_envelope"]["id"]

        canceled_status, canceled_response = self.service.reevaluate(
            task_id,
            {
                "request": {
                    "review_decision": build_review_decision_from_request(
                        initial_response["enforcement_result"]["review_request"],
                        outcome="cancel_task",
                    )
                }
            },
        )
        before_task = deepcopy(self.service.store.get_task(task_id))

        invalid_attempt_payload = _execution_attempt_payload(attempt_id="attempt-canceled-invalid-1")
        invalid_attempt_payload["execution_attempt"]["artifact_references"] = [
            {
                "reference_id": "attempt-canceled-invalid-1:commit",
                "artifact_type": "commit",
                "location": "stub://attempts/attempt-canceled-invalid-1/commit",
                "metadata": {
                    "branch_name": "codex/e2e-test",
                },
            }
        ]
        claim_status, claim_response = self.service.submit_completion_claim(
            task_id,
            {
                "request": {
                    **_completion_claim_payload(claim_id="claim-canceled-invalid-1"),
                    **invalid_attempt_payload,
                    "runtime_facts": {"executor_reported_success": True, "attempt_count": 1},
                }
            },
        )
        after_task = self.service.store.get_task(task_id)
        read_status, read_payload = self.service.get_task_read_model(task_id)

        self.assertEqual(initial_status, 200)
        self.assertEqual(canceled_status, 200)
        self.assertEqual(canceled_response["task_envelope"]["status"], "canceled")
        self.assertEqual(claim_status, 200)
        self.assertEqual(claim_response["action"], "transition_rejected")
        self.assertIn("canceled -> failed", claim_response["error"])
        self.assertEqual(claim_response["task_envelope"]["status"], "canceled")
        self.assertEqual(before_task, after_task)
        self.assertEqual(read_status, 200)
        self.assertEqual(read_payload["task"]["current_status"], "canceled")

    def test_service_reevaluate_cancel_task_clears_active_assignment(self) -> None:
        initial_payload = _request_payload("review_required")
        initial_payload["request"]["task_envelope"]["status"] = "assigned"
        initial_payload["request"]["task_envelope"]["assigned_executor"] = {
            "executor_type": "codex",
            "executor_id": "executor-review-cancel-clear-1",
            "assignment_reason": "Seed active assignment for review cancel coverage.",
        }
        initial_payload["request"]["review_request"]["allowed_outcomes"] = [
            "accept_completion",
            "cancel_task",
        ]

        initial_status, initial_response = self.service.evaluate(initial_payload)
        task_id = initial_response["task_envelope"]["id"]

        resolution_status, resolution_response = self.service.reevaluate(
            task_id,
            {
                "request": {
                    "review_decision": build_review_decision_from_request(
                        initial_response["enforcement_result"]["review_request"],
                        outcome="cancel_task",
                    )
                }
            },
        )
        read_status, read_payload = self.service.get_task_read_model(task_id)

        self.assertEqual(initial_status, 200)
        self.assertEqual(resolution_status, 200)
        self.assertEqual(resolution_response["action"], "transition_applied")
        self.assertEqual(resolution_response["task_envelope"]["status"], "canceled")
        self.assertIsNone(resolution_response["task_envelope"].get("assigned_executor"))
        self.assertEqual(read_status, 200)
        self.assertEqual(read_payload["task"]["current_status"], "canceled")
        self.assertIsNone(read_payload["task"].get("assigned_executor"))

    def test_service_completion_claim_ignores_support_artifact_context_for_execution_validation(self) -> None:
        payload = _manual_happy_path_overlay_payload()
        submit_payload = {
            "request": {
                "task_envelope": deepcopy(payload["request"]["task_envelope"]),
            }
        }
        submit_status, submit_response = self.service.submit(submit_payload)
        task_id = submit_response["task_envelope"]["id"]
        assigned_task = deepcopy(self.service.store.get_task(task_id))
        assigned_task["status"] = "assigned"
        assigned_task["assigned_executor"] = {
            "executor_type": "codex",
            "executor_id": "executor-invalid-support-context-1",
            "assignment_reason": "Exercise support artifact context rejection.",
        }
        assigned_task["timestamps"]["updated_at"] = "2026-04-01T10:03:00Z"
        self.service.store.update_task(assigned_task)

        support_artifact = _review_note_artifact("artifact-support-context-note-1")
        support_artifact["repository"] = {
            "host": "github.com",
            "owner": "KnoxAnalytics",
            "name": "HARNESS-DRYRUN",
        }
        support_artifact["branch"] = {
            "name": "codex/e2e-test",
            "base_branch": "main",
            "head_commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
        }
        support_artifact["commit_sha"] = "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705"

        with patch.dict(os.environ, {"HARNESS_INVALID_EXECUTION_RETRY_BUDGET": "1"}):
            claim_status, claim_response = self.service.submit_completion_claim(
                task_id,
                {
                    "request": {
                        **_completion_claim_payload(claim_id="claim-invalid-support-context-1"),
                        **_execution_attempt_payload(attempt_id="attempt-invalid-support-context-1"),
                        "new_artifacts": [support_artifact],
                        "runtime_facts": {"executor_reported_success": True, "attempt_count": 1},
                    }
                },
            )

        self.assertEqual(submit_status, 200)
        self.assertEqual(claim_status, 200)
        self.assertEqual(claim_response["action"], "contract_violation_failed")
        self.assertEqual(claim_response["task_envelope"]["status"], "failed")
        self.assertEqual(
            claim_response["contract_violation"]["validation"]["rule_failures"][0]["rule"],
            "missing_branch_identity",
        )
        self.assertFalse(
            claim_response["contract_violation"]["validation"]["context_observations"].get("repository")
        )

    def test_service_completion_claim_ignores_support_artifact_references_for_execution_validation(self) -> None:
        payload = _manual_happy_path_overlay_payload()
        submit_status, submit_response = self.service.submit(
            {"request": {"task_envelope": deepcopy(payload["request"]["task_envelope"])}}
        )
        task_id = submit_response["task_envelope"]["id"]
        assigned_task = deepcopy(self.service.store.get_task(task_id))
        assigned_task["status"] = "assigned"
        assigned_task["assigned_executor"] = {
            "executor_type": "codex",
            "executor_id": "executor-invalid-support-reference-1",
            "assignment_reason": "Exercise support artifact reference rejection.",
        }
        assigned_task["timestamps"]["updated_at"] = "2026-04-01T10:03:00Z"
        self.service.store.update_task(assigned_task)

        invalid_attempt_payload = _execution_attempt_payload(attempt_id="attempt-invalid-support-reference-1")
        invalid_attempt_payload["execution_attempt"]["artifact_references"] = [
            {
                "reference_id": "attempt-invalid-support-reference-1:review-note",
                "artifact_type": "review_note",
                "location": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/tree/codex/e2e-test",
                "metadata": {
                    "repository_host": "github.com",
                    "repository_owner": "KnoxAnalytics",
                    "repository_name": "HARNESS-DRYRUN",
                    "branch_name": "codex/e2e-test",
                    "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                },
            }
        ]

        with patch.dict(os.environ, {"HARNESS_INVALID_EXECUTION_RETRY_BUDGET": "1"}):
            claim_status, claim_response = self.service.submit_completion_claim(
                task_id,
                {
                    "request": {
                        **_completion_claim_payload(claim_id="claim-invalid-support-reference-1"),
                        **invalid_attempt_payload,
                        "runtime_facts": {"executor_reported_success": True, "attempt_count": 1},
                    }
                },
            )

        self.assertEqual(submit_status, 200)
        self.assertEqual(claim_status, 200)
        self.assertEqual(claim_response["action"], "contract_violation_failed")
        self.assertEqual(
            claim_response["contract_violation"]["validation"]["rule_failures"][0]["rule"],
            "missing_branch_identity",
        )
        self.assertFalse(
            claim_response["contract_violation"]["validation"]["context_observations"].get("repository")
        )

    def test_service_completion_claim_rejects_reserved_work_branch_as_contract_violation(self) -> None:
        payload = _manual_happy_path_overlay_payload()
        submit_payload = {
            "request": {
                "task_envelope": deepcopy(payload["request"]["task_envelope"]),
            }
        }
        submit_status, submit_response = self.service.submit(submit_payload)
        task_id = submit_response["task_envelope"]["id"]

        invalid_attempt_payload = _execution_attempt_payload(attempt_id="attempt-work-branch-1")
        invalid_attempt_payload["execution_attempt"]["artifact_references"] = [
            {
                "reference_id": "attempt-work-branch-1:commit",
                "artifact_type": "commit",
                "location": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/commit/8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                "metadata": {
                    "repository_host": "github.com",
                    "repository_owner": "KnoxAnalytics",
                    "repository_name": "HARNESS-DRYRUN",
                    "branch_name": "work",
                    "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                },
            }
        ]
        linked_artifacts = deepcopy(payload["request"]["linked_artifacts"])
        linked_artifacts[0]["branch"]["name"] = "work"
        external_facts = deepcopy(payload["request"]["external_facts"])
        external_facts["expected_code_context"]["branch_name"] = "work"
        external_facts["github_facts"]["branch"]["name"] = "work"

        claim_status, claim_response = self.service.submit_completion_claim(
            task_id,
            {
                "request": {
                    **_completion_claim_payload(claim_id="claim-work-branch-1"),
                    **invalid_attempt_payload,
                    "new_artifacts": linked_artifacts,
                    "completion_evidence": deepcopy(payload["request"]["completion_evidence"]),
                    "external_facts": external_facts,
                    "acceptance_criteria_satisfied": True,
                    "runtime_facts": {"executor_reported_success": True, "attempt_count": 1},
                }
            },
        )
        read_status, read_payload = self.service.get_task_read_model(task_id)
        timeline_status, timeline_payload = self.service.get_task_timeline(task_id)

        self.assertEqual(submit_status, 200)
        self.assertEqual(claim_status, 200)
        self.assertEqual(claim_response["action"], "contract_violation_failed")
        self.assertEqual(claim_response["task_envelope"]["status"], "failed")
        self.assertEqual(
            claim_response["evaluation_record"]["result"]["failure_classification"]["failure_type"],
            "contract_violation",
        )
        self.assertEqual(
            claim_response["contract_violation"]["validation"]["rule_failures"][0]["rule"],
            "reserved_shared_branch",
        )
        self.assertEqual(read_status, 200)
        self.assertEqual(read_payload["task"]["failure_summary"]["failure_type"], "contract_violation")
        self.assertEqual(
            read_payload["task"]["execution_summary"]["latest_attempt_validation"]["rule_failures"][0]["rule"],
            "reserved_shared_branch",
        )
        self.assertEqual(timeline_status, 200)
        execution_attempt_events = [
            event for event in timeline_payload["timeline"] if event["event_type"] == "execution_attempt_recorded"
        ]
        self.assertTrue(execution_attempt_events)
        self.assertEqual(
            execution_attempt_events[-1]["details"]["attempt_validation"]["rule_failures"][0]["rule"],
            "reserved_shared_branch",
        )

    def test_service_completion_claim_rejects_missing_branch_identity(self) -> None:
        payload = _manual_happy_path_overlay_payload()
        submit_payload = {
            "request": {
                "task_envelope": deepcopy(payload["request"]["task_envelope"]),
            }
        }
        submit_status, submit_response = self.service.submit(submit_payload)
        task_id = submit_response["task_envelope"]["id"]

        attempt_payload = _execution_attempt_payload(attempt_id="attempt-missing-branch-1")
        attempt_payload["execution_attempt"]["artifact_references"] = [
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
        external_facts = deepcopy(payload["request"]["external_facts"])
        external_facts["expected_code_context"].pop("branch_name", None)
        external_facts["github_facts"].pop("branch", None)

        claim_status, claim_response = self.service.submit_completion_claim(
            task_id,
            {
                "request": {
                    **_completion_claim_payload(claim_id="claim-missing-branch-1"),
                    **attempt_payload,
                    "external_facts": external_facts,
                    "runtime_facts": {"executor_reported_success": True, "attempt_count": 1},
                }
            },
        )

        self.assertEqual(submit_status, 200)
        self.assertEqual(claim_status, 200)
        self.assertEqual(claim_response["action"], "contract_violation_failed")
        self.assertEqual(claim_response["task_envelope"]["status"], "failed")
        self.assertEqual(
            claim_response["evaluation_record"]["result"]["failure_classification"]["failure_type"],
            "contract_violation",
        )
        self.assertEqual(
            claim_response["contract_violation"]["validation"]["rule_failures"][0]["rule"],
            "missing_branch_identity",
        )

    def test_service_completion_claim_rejects_missing_pr_url_when_pr_proof_is_supplied(self) -> None:
        payload = _manual_happy_path_overlay_payload()
        submit_payload = {"request": {"task_envelope": deepcopy(payload["request"]["task_envelope"])}}
        submit_status, submit_response = self.service.submit(submit_payload)
        task_id = submit_response["task_envelope"]["id"]

        linked_artifacts = deepcopy(payload["request"]["linked_artifacts"])
        linked_artifacts[0]["location"] = None

        claim_status, claim_response = self.service.submit_completion_claim(
            task_id,
            {
                "request": {
                    **_completion_claim_payload(claim_id="claim-missing-pr-url-1"),
                    **_execution_attempt_payload(attempt_id="attempt-missing-pr-url-1"),
                    "new_artifacts": linked_artifacts,
                    "completion_evidence": deepcopy(payload["request"]["completion_evidence"]),
                    "external_facts": deepcopy(payload["request"]["external_facts"]),
                    "acceptance_criteria_satisfied": True,
                    "runtime_facts": {"executor_reported_success": True, "attempt_count": 1},
                }
            },
        )

        self.assertEqual(submit_status, 200)
        self.assertEqual(claim_status, 200)
        self.assertEqual(claim_response["action"], "contract_violation_failed")
        self.assertEqual(
            claim_response["contract_violation"]["validation"]["rule_failures"][0]["rule"],
            "missing_pr_url",
        )

    def test_service_completion_claim_rejects_invalid_non_numeric_pr_url(self) -> None:
        payload = _manual_happy_path_overlay_payload()
        submit_payload = {"request": {"task_envelope": deepcopy(payload["request"]["task_envelope"])}}
        submit_status, submit_response = self.service.submit(submit_payload)
        task_id = submit_response["task_envelope"]["id"]

        linked_artifacts = deepcopy(payload["request"]["linked_artifacts"])
        linked_artifacts[0]["location"] = "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/compare/main...work"
        external_facts = deepcopy(payload["request"]["external_facts"])
        external_facts["github_facts"]["pull_request"]["url"] = "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/pull/new/work"

        claim_status, claim_response = self.service.submit_completion_claim(
            task_id,
            {
                "request": {
                    **_completion_claim_payload(claim_id="claim-invalid-pr-url-1"),
                    **_execution_attempt_payload(attempt_id="attempt-invalid-pr-url-1"),
                    "new_artifacts": linked_artifacts,
                    "completion_evidence": deepcopy(payload["request"]["completion_evidence"]),
                    "external_facts": external_facts,
                    "acceptance_criteria_satisfied": True,
                    "runtime_facts": {"executor_reported_success": True, "attempt_count": 1},
                }
            },
        )

        self.assertEqual(submit_status, 200)
        self.assertEqual(claim_status, 200)
        self.assertEqual(claim_response["action"], "contract_violation_failed")
        failed_rules = {
            item["rule"] for item in claim_response["contract_violation"]["validation"]["rule_failures"]
        }
        self.assertIn("invalid_pr_url", failed_rules)

    def test_service_completion_claim_rejects_closed_pr_as_current_run_proof(self) -> None:
        payload = _manual_happy_path_overlay_payload()
        submit_payload = {"request": {"task_envelope": deepcopy(payload["request"]["task_envelope"])}}
        submit_status, submit_response = self.service.submit(submit_payload)
        task_id = submit_response["task_envelope"]["id"]

        linked_artifacts = deepcopy(payload["request"]["linked_artifacts"])
        linked_artifacts[0]["metadata"]["pull_request_state"] = "closed"
        external_facts = deepcopy(payload["request"]["external_facts"])
        external_facts["github_facts"]["pull_request"]["state"] = "closed"

        claim_status, claim_response = self.service.submit_completion_claim(
            task_id,
            {
                "request": {
                    **_completion_claim_payload(claim_id="claim-closed-pr-1"),
                    **_execution_attempt_payload(attempt_id="attempt-closed-pr-1"),
                    "new_artifacts": linked_artifacts,
                    "completion_evidence": deepcopy(payload["request"]["completion_evidence"]),
                    "external_facts": external_facts,
                    "acceptance_criteria_satisfied": True,
                    "runtime_facts": {"executor_reported_success": True, "attempt_count": 1},
                }
            },
        )

        self.assertEqual(submit_status, 200)
        self.assertEqual(claim_status, 200)
        self.assertEqual(claim_response["action"], "contract_violation_failed")
        failed_rules = {
            item["rule"] for item in claim_response["contract_violation"]["validation"]["rule_failures"]
        }
        self.assertIn("stale_pull_request_not_allowed", failed_rules)

    def test_service_completion_claim_rejects_pull_request_with_unknown_state(self) -> None:
        payload = _manual_happy_path_overlay_payload()
        submit_payload = {"request": {"task_envelope": deepcopy(payload["request"]["task_envelope"])}}
        submit_status, submit_response = self.service.submit(submit_payload)
        task_id = submit_response["task_envelope"]["id"]

        linked_artifacts = deepcopy(payload["request"]["linked_artifacts"])
        linked_artifacts[0]["metadata"].pop("pull_request_state", None)
        external_facts = deepcopy(payload["request"]["external_facts"])
        external_facts["github_facts"]["pull_request"]["state"] = None

        claim_status, claim_response = self.service.submit_completion_claim(
            task_id,
            {
                "request": {
                    **_completion_claim_payload(claim_id="claim-unknown-pr-state-1"),
                    **_execution_attempt_payload(attempt_id="attempt-unknown-pr-state-1"),
                    "new_artifacts": linked_artifacts,
                    "completion_evidence": deepcopy(payload["request"]["completion_evidence"]),
                    "external_facts": external_facts,
                    "acceptance_criteria_satisfied": True,
                    "runtime_facts": {"executor_reported_success": True, "attempt_count": 1},
                }
            },
        )

        self.assertEqual(submit_status, 200)
        self.assertEqual(claim_status, 200)
        self.assertEqual(claim_response["action"], "contract_violation_failed")
        failed_rules = {
            item["rule"] for item in claim_response["contract_violation"]["validation"]["rule_failures"]
        }
        self.assertIn("unknown_pull_request_state", failed_rules)

    def test_service_completion_claim_allows_valid_execution_attempt_with_repo_branch_and_commit(self) -> None:
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_current_run_pull_request_gateway(),
        )
        payload = _manual_happy_path_overlay_payload()
        submit_payload = {
            "request": {
                "task_envelope": deepcopy(payload["request"]["task_envelope"]),
            }
        }
        submit_status, submit_response = service.submit(submit_payload)
        task_id = submit_response["task_envelope"]["id"]

        valid_attempt_payload = _execution_attempt_payload(attempt_id="attempt-valid-1")
        valid_attempt_payload["execution_attempt"]["artifact_references"] = [
            {
                "reference_id": "attempt-valid-1:commit",
                "artifact_type": "commit",
                "location": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/commit/8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                "metadata": {
                    "repository_host": "github.com",
                    "repository_owner": "KnoxAnalytics",
                    "repository_name": "HARNESS-DRYRUN",
                    "branch_name": "codex/e2e-test",
                    "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                },
            }
        ]
        claim_status, claim_response = service.submit_completion_claim(
            task_id,
            {
                "request": {
                    **_completion_claim_payload(claim_id="claim-valid-attempt-1"),
                    **valid_attempt_payload,
                    "new_artifacts": deepcopy(payload["request"]["linked_artifacts"]),
                    "completion_evidence": deepcopy(payload["request"]["completion_evidence"]),
                    "external_facts": deepcopy(payload["request"]["external_facts"]),
                    "acceptance_criteria_satisfied": True,
                    "runtime_facts": deepcopy(payload["request"]["runtime_facts"]),
                }
            },
        )

        self.assertEqual(submit_status, 200)
        self.assertEqual(claim_status, 200)
        self.assertTrue(claim_response["accepted_completion"])
        latest_attempt = claim_response["task_envelope"]["observability"]["execution_metadata"]["execution_attempts"][-1]
        self.assertEqual(latest_attempt["metadata"]["attempt_validation"]["status"], "valid")

    def test_service_completion_claim_uses_current_attempt_proof_before_reconciliation(self) -> None:
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_current_run_pull_request_gateway(),
        )
        payload = _manual_happy_path_overlay_payload()
        task_envelope = deepcopy(payload["request"]["task_envelope"])
        task_envelope["id"] = "task-current-attempt-proof-1"
        task_envelope["title"] = "Current attempt proof avoids unnecessary reconciliation"
        task_envelope["description"] = (
            "A real current-run PR URL and commit SHA from the completion claim should suppress "
            "missing_pr_after_execution and missing_commit_after_execution."
        )
        task_envelope["artifacts"]["items"] = []
        task_envelope["artifacts"]["completion_evidence"] = {
            "policy": "deferred",
            "status": "deferred",
            "required_artifact_types": ["pull_request", "commit"],
            "validated_artifact_ids": [],
            "validation_method": "deferred",
            "validated_at": None,
            "validator": None,
            "notes": None,
        }
        submit_status, submit_response = service.submit({"request": {"task_envelope": task_envelope}})
        task_id = submit_response["task_envelope"]["id"]

        claim_status, claim_response = service.submit_completion_claim(
            task_id,
            {
                "request": {
                    "completion_claim": {
                        "claim_id": "claim-current-attempt-proof-1",
                        "reported_at": "2026-04-16T20:37:07Z",
                        "reported_by": "hermes",
                        "reason": "Hermes completed the dry-run task and reported real GitHub proof.",
                        "metadata": {"attempt_id": "attempt-current-attempt-proof-1"},
                    },
                    "execution_attempt": {
                        "attempt_id": "attempt-current-attempt-proof-1",
                        "recorded_at": "2026-04-16T20:37:07Z",
                        "status": "succeeded",
                        "reported_by": "hermes",
                        "artifact_references": [
                            {
                                "reference_id": "attempt-current-attempt-proof-1:commit",
                                "artifact_type": "commit",
                                "location": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/commit/8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                                "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                                "metadata": {
                                    "repository_host": "github.com",
                                    "repository_owner": "KnoxAnalytics",
                                    "repository_name": "HARNESS-DRYRUN",
                                    "branch_name": "codex/e2e-test",
                                    "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                                },
                            },
                            {
                                "reference_id": "attempt-current-attempt-proof-1:pr",
                                "artifact_type": "pull_request",
                                "location": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/pull/2",
                                "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                                "metadata": {
                                    "repository_host": "github.com",
                                    "repository_owner": "KnoxAnalytics",
                                    "repository_name": "HARNESS-DRYRUN",
                                    "branch_name": "codex/e2e-test",
                                    "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                                    "pull_request_url": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/pull/2",
                                    "pull_request_number": 2,
                                    "pull_request_state": "open",
                                },
                            },
                        ],
                        "metadata": {"executor_run_id": "hermes:attempt-current-attempt-proof-1"},
                    },
                    "acceptance_criteria_satisfied": True,
                    "runtime_facts": {"executor_reported_success": True, "attempt_count": 1},
                    "external_facts": {
                        "expected_code_context": {
                            "repository_host": "github.com",
                            "repository_owner": "KnoxAnalytics",
                            "repository_name": "HARNESS-DRYRUN",
                            "branch_name": "codex/e2e-test",
                            "base_branch": "main",
                        }
                    },
                }
            },
        )

        self.assertEqual(submit_status, 200)
        self.assertEqual(claim_status, 200)
        self.assertEqual(claim_response["action"], "transition_applied")
        self.assertTrue(claim_response["accepted_completion"])
        self.assertEqual(claim_response["task_envelope"]["status"], "completed")
        self.assertNotIn("reconciliation_attempt", claim_response)
        latest_attempt = claim_response["task_envelope"]["observability"]["execution_metadata"]["execution_attempts"][-1]
        context = latest_attempt["metadata"]["attempt_validation"]["context_observations"]
        self.assertFalse(context["has_valid_current_run_pull_request_artifact"])
        self.assertFalse(context["has_valid_current_run_commit_artifact"])
        self.assertEqual(
            [attempt["failure_type"] for attempt in claim_response["task_envelope"]["reconciliation"]["attempts"][-2:]],
            ["missing_pr_after_execution", "missing_commit_after_execution"],
        )

    def test_service_completion_claim_reconciliation_sets_required_policy_when_artifact_evidence_becomes_satisfied(self) -> None:
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_current_run_pull_request_gateway(),
        )
        payload = _manual_happy_path_overlay_payload()
        task_envelope = deepcopy(payload["request"]["task_envelope"])
        task_envelope["id"] = "task-reconciliation-policy-upgrade-1"
        task_envelope["title"] = "Reconciliation evidence policy upgrade"
        task_envelope["description"] = "Harness-owned reconciliation must not leave satisfied evidence under deferred policy."
        task_envelope["artifacts"]["items"] = []
        task_envelope["artifacts"]["completion_evidence"] = {
            "policy": "deferred",
            "status": "deferred",
            "required_artifact_types": ["pull_request", "commit"],
            "validated_artifact_ids": [],
            "validation_method": "deferred",
            "validated_at": None,
            "validator": None,
            "notes": None,
        }
        submit_status, submit_response = service.submit({"request": {"task_envelope": task_envelope}})
        task_id = submit_response["task_envelope"]["id"]

        valid_attempt_payload = _execution_attempt_payload(attempt_id="attempt-reconciliation-policy-upgrade-1")
        valid_attempt_payload["execution_attempt"]["artifact_references"] = [
            {
                "reference_id": "attempt-reconciliation-policy-upgrade-1:commit",
                "artifact_type": "commit",
                "location": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/commit/8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                "metadata": {
                    "repository_host": "github.com",
                    "repository_owner": "KnoxAnalytics",
                    "repository_name": "HARNESS-DRYRUN",
                    "branch_name": "codex/e2e-test",
                    "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                },
            }
        ]
        claim_status, claim_response = service.submit_completion_claim(
            task_id,
            {
                "request": {
                    **_completion_claim_payload(claim_id="claim-reconciliation-policy-upgrade-1"),
                    **valid_attempt_payload,
                    "acceptance_criteria_satisfied": True,
                    "runtime_facts": deepcopy(payload["request"]["runtime_facts"]),
                }
            },
        )

        self.assertEqual(submit_status, 200)
        self.assertEqual(claim_status, 200)
        self.assertEqual(claim_response["action"], "transition_applied")
        self.assertTrue(claim_response["accepted_completion"])
        evidence = claim_response["task_envelope"]["artifacts"]["completion_evidence"]
        self.assertEqual(evidence["policy"], "required")
        self.assertEqual(evidence["status"], "satisfied")
        self.assertEqual(evidence["validation_method"], "external_reconciliation")

    def test_service_completion_claim_flags_vague_acceptance_criteria_for_review(self) -> None:
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_current_run_pull_request_gateway(),
        )
        payload = _manual_happy_path_overlay_payload()
        vague_task = deepcopy(payload["request"]["task_envelope"])
        vague_task["acceptance_criteria"] = [
            {
                "id": "ac-vague",
                "description": "Task works properly.",
                "required": True,
            }
        ]
        vague_task["objective"]["success_signal"] = "Task satisfies declared acceptance criteria."
        submit_payload = {
            "request": {
                "task_envelope": vague_task,
            }
        }
        submit_status, submit_response = service.submit(submit_payload)
        task_id = submit_response["task_envelope"]["id"]

        valid_attempt_payload = _execution_attempt_payload(attempt_id="attempt-vague-criteria-1")
        valid_attempt_payload["execution_attempt"]["artifact_references"] = [
            {
                "reference_id": "attempt-vague-criteria-1:commit",
                "artifact_type": "commit",
                "location": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/commit/8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                "metadata": {
                    "repository_host": "github.com",
                    "repository_owner": "KnoxAnalytics",
                    "repository_name": "HARNESS-DRYRUN",
                    "branch_name": "codex/e2e-test",
                    "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                },
            }
        ]
        claim_status, claim_response = service.submit_completion_claim(
            task_id,
            {
                "request": {
                    **_completion_claim_payload(claim_id="claim-vague-criteria-1"),
                    **valid_attempt_payload,
                    "new_artifacts": deepcopy(payload["request"]["linked_artifacts"]),
                    "completion_evidence": deepcopy(payload["request"]["completion_evidence"]),
                    "external_facts": deepcopy(payload["request"]["external_facts"]),
                    "acceptance_criteria_satisfied": True,
                    "runtime_facts": deepcopy(payload["request"]["runtime_facts"]),
                }
            },
        )
        read_status, read_payload = service.get_task_read_model(task_id)

        self.assertEqual(submit_status, 200)
        self.assertEqual(claim_status, 200)
        self.assertEqual(claim_response["action"], "review_required")
        self.assertFalse(claim_response["accepted_completion"])
        self.assertTrue(claim_response["requires_review"])
        self.assertEqual(claim_response["task_envelope"]["status"], "in_review")
        verification = claim_response["enforcement_result"]["verification_result"]
        self.assertEqual(verification["outcome"], "review_required")
        self.assertFalse(verification["acceptance_criteria_assessment"]["automatic_completion_safe"])
        self.assertIn(
            "too vague for automatic completion",
            " ".join(verification["reasons"]).lower(),
        )
        self.assertEqual(read_status, 200)
        self.assertEqual(read_payload["task"]["current_status"], "in_review")
        self.assertFalse(
            read_payload["task"]["verification_summary"]["acceptance_criteria_assessment"]["automatic_completion_safe"]
        )

    def test_service_completion_claim_routes_valid_attempt_without_pr_to_missing_pr_boundary(self) -> None:
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_no_create_pull_request_gateway(),
        )
        payload = _manual_happy_path_overlay_payload()
        submit_payload = {
            "request": {
                "task_envelope": deepcopy(payload["request"]["task_envelope"]),
            }
        }
        submit_status, submit_response = service.submit(submit_payload)
        task_id = submit_response["task_envelope"]["id"]

        valid_attempt_payload = _execution_attempt_payload(attempt_id="attempt-valid-no-pr-1")
        valid_attempt_payload["execution_attempt"]["artifact_references"] = [
            {
                "reference_id": "attempt-valid-no-pr-1:commit",
                "artifact_type": "commit",
                "location": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/commit/8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                "metadata": {
                    "repository_host": "github.com",
                    "repository_owner": "KnoxAnalytics",
                    "repository_name": "HARNESS-DRYRUN",
                    "branch_name": "codex/e2e-test",
                    "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                },
            }
        ]
        claim_status, claim_response = service.submit_completion_claim(
            task_id,
            {
                "request": {
                    **_completion_claim_payload(claim_id="claim-valid-no-pr-1"),
                    **valid_attempt_payload,
                    "external_facts": deepcopy(payload["request"]["external_facts"]),
                    "runtime_facts": {"executor_reported_success": True, "attempt_count": 1},
                }
            },
        )
        read_status, read_payload = service.get_task_read_model(task_id)

        self.assertEqual(submit_status, 200)
        self.assertEqual(claim_status, 200)
        self.assertEqual(claim_response["action"], "reconciliation_failed")
        self.assertEqual(claim_response["reconciliation_attempt"]["failure_type"], "missing_pr_after_execution")
        self.assertEqual(claim_response["task_envelope"]["status"], "in_review")
        self.assertEqual(claim_response["review_request"]["trigger"], "reconciliation")
        self.assertEqual(claim_response["evaluation_record"]["result"]["action"], "review_required")
        latest_attempt = claim_response["task_envelope"]["observability"]["execution_metadata"]["execution_attempts"][-1]
        self.assertIn("metadata", latest_attempt)
        self.assertIn("attempt_validation", latest_attempt["metadata"])
        self.assertEqual(latest_attempt["metadata"]["attempt_validation"]["status"], "valid")
        self.assertNotIn("invalid_execution_attempt", claim_response)
        self.assertEqual(read_status, 200)
        self.assertEqual(read_payload["task"]["current_status"], "in_review")
        self.assertEqual(read_payload["task"]["execution_summary"]["invalid_attempt_count"], 0)
        self.assertEqual(read_payload["task"]["review_summary"]["status"], "requested")

        history_status, history_payload = service.get_evaluation_history(task_id)
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 2)
        self.assertEqual(history_payload["evaluations"][-1]["result"]["action"], "review_required")

    def test_service_completion_claim_reconciliation_review_gate_can_be_manually_resolved(self) -> None:
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_no_create_pull_request_gateway(),
        )
        payload = _manual_happy_path_overlay_payload()
        submit_status, submit_response = service.submit(
            {"request": {"task_envelope": deepcopy(payload["request"]["task_envelope"])}}
        )
        task_id = submit_response["task_envelope"]["id"]

        valid_attempt_payload = _execution_attempt_payload(attempt_id="attempt-valid-no-pr-resolve-1")
        valid_attempt_payload["execution_attempt"]["artifact_references"] = [
            {
                "reference_id": "attempt-valid-no-pr-resolve-1:commit",
                "artifact_type": "commit",
                "location": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/commit/8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                "metadata": {
                    "repository_host": "github.com",
                    "repository_owner": "KnoxAnalytics",
                    "repository_name": "HARNESS-DRYRUN",
                    "branch_name": "codex/e2e-test",
                    "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                },
            }
        ]
        claim_status, claim_response = service.submit_completion_claim(
            task_id,
            {
                "request": {
                    **_completion_claim_payload(claim_id="claim-valid-no-pr-resolve-1"),
                    **valid_attempt_payload,
                    "external_facts": deepcopy(payload["request"]["external_facts"]),
                    "runtime_facts": {"executor_reported_success": True, "attempt_count": 1},
                }
            },
        )
        review_request_payload = claim_response["evaluation_record"]["result"]["enforcement_result"]["review_request"]
        review_request = ReviewRequest(
            review_request_id=review_request_payload["review_request_id"],
            task_id=review_request_payload["task_id"],
            requested_at=review_request_payload["requested_at"],
            requested_by=review_request_payload["requested_by"],
            trigger=ReviewTrigger(review_request_payload["trigger"]),
            summary=review_request_payload["summary"],
            presented_sections=tuple(review_request_payload["presented_sections"]),
            allowed_outcomes=tuple(ReviewOutcome(item) for item in review_request_payload["allowed_outcomes"]),
            prior_review_ids=tuple(review_request_payload.get("prior_review_ids", ())),
            metadata=dict(review_request_payload.get("metadata", {})),
        )
        reevaluation_status, reevaluation_response = service.reevaluate(
            task_id,
            {
                "request": {
                    "review_decision": _to_jsonable(
                        resolve_review_request(
                            review_request,
                            review_id="review-reconcile-1",
                            reviewer=ReviewerIdentity(
                                reviewer_id="operator-1",
                                reviewer_name="Casey Reviewer",
                                authority_role="operator",
                            ),
                            outcome=ReviewOutcome.ACCEPT_COMPLETION,
                            reasoning="Manual review accepted the reconciliation-backed completion.",
                        )
                    )
                }
            },
        )

        self.assertEqual(submit_status, 200)
        self.assertEqual(claim_status, 200)
        self.assertEqual(claim_response["task_envelope"]["status"], "in_review")
        self.assertEqual(reevaluation_status, 200)
        self.assertEqual(reevaluation_response["task_envelope"]["status"], "completed")

        read_status, read_payload = service.get_task_read_model(task_id)
        self.assertEqual(read_status, 200)
        self.assertEqual(read_payload["task"]["review_summary"]["status"], "resolved")
        self.assertEqual(read_payload["task"]["review_summary"]["decision_count"], 1)

    def test_service_completion_claim_strips_executor_verified_status_and_still_reconciles(self) -> None:
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_no_create_pull_request_gateway(),
        )
        payload = _manual_happy_path_overlay_payload()
        submit_status, submit_response = service.submit(
            {"request": {"task_envelope": deepcopy(payload["request"]["task_envelope"])}}
        )
        task_id = submit_response["task_envelope"]["id"]

        claim_artifacts = deepcopy(payload["request"]["linked_artifacts"])
        claim_artifacts[0]["verification_status"] = "verified"
        claim_artifacts[0]["metadata"]["pull_request_state"] = "open"

        claim_status, claim_response = service.submit_completion_claim(
            task_id,
            {
                "request": {
                    **_completion_claim_payload(claim_id="claim-self-certified-pr-1"),
                    **_execution_attempt_payload(attempt_id="attempt-self-certified-pr-1"),
                    "new_artifacts": claim_artifacts,
                    "completion_evidence": deepcopy(payload["request"]["completion_evidence"]),
                    "external_facts": deepcopy(payload["request"]["external_facts"]),
                    "acceptance_criteria_satisfied": True,
                    "runtime_facts": deepcopy(payload["request"]["runtime_facts"]),
                }
            },
        )

        self.assertEqual(submit_status, 200)
        self.assertEqual(claim_status, 200)
        self.assertEqual(claim_response["action"], "reconciliation_failed")
        pull_request_artifacts = [
            artifact
            for artifact in claim_response["task_envelope"]["artifacts"]["items"]
            if isinstance(artifact, dict) and artifact.get("type") == "pull_request"
        ]
        self.assertTrue(pull_request_artifacts)
        self.assertEqual(pull_request_artifacts[-1]["verification_status"], "unverified")

    def test_service_completion_claim_strips_executor_verified_status_from_support_artifacts(self) -> None:
        service = HarnessApiService(store=FileBackedHarnessStore(self.temp_dir.name))
        task_envelope = create_task_envelope(
            {
                "id": "task-support-artifact-claim-1",
                "title": "Support artifact completion claim",
                "description": "Completion claim should not self-certify support artifacts.",
                "origin": {
                    "source_system": "openclaw",
                    "source_type": "ingress_request",
                    "source_id": "req-support-artifact-claim-1",
                },
                "acceptance_criteria": [
                    {
                        "id": "ac-1",
                        "description": "Completion requires a reviewed support note.",
                        "required": True,
                    }
                ],
            },
            now="2026-04-07T18:00:00Z",
        )
        task_envelope["artifacts"]["completion_evidence"] = {
            "policy": "required",
            "status": "deferred",
            "required_artifact_types": ["review_note"],
            "validated_artifact_ids": [],
            "validation_method": "deferred",
            "validated_at": None,
            "validator": None,
            "notes": None,
        }
        submit_status, submit_response = service.submit({"request": {"task_envelope": task_envelope}})
        task_id = submit_response["task_envelope"]["id"]

        claim_status, claim_response = service.submit_completion_claim(
            task_id,
            {
                "request": {
                    **_completion_claim_payload(claim_id="claim-support-verified-note-1"),
                    **_execution_attempt_payload(attempt_id="attempt-support-verified-note-1"),
                    "new_artifacts": [_review_note_artifact("artifact-review-note-claim-1")],
                    "completion_evidence": {
                        "validated_artifact_ids": ["artifact-review-note-claim-1"],
                        "validation_method": "manual_review",
                    },
                    "acceptance_criteria_satisfied": True,
                    "runtime_facts": {"executor_reported_success": True, "attempt_count": 1},
                }
            },
        )

        self.assertEqual(submit_status, 200)
        self.assertEqual(claim_status, 200)
        self.assertFalse(claim_response["accepted_completion"])
        self.assertNotEqual(claim_response["task_envelope"]["status"], "completed")
        review_note_artifact = next(
            artifact
            for artifact in claim_response["task_envelope"]["artifacts"]["items"]
            if artifact["id"] == "artifact-review-note-claim-1"
        )
        self.assertEqual(review_note_artifact["verification_status"], "unverified")
        self.assertEqual(
            review_note_artifact["metadata"]["submitted_verification_status"],
            "verified",
        )
        self.assertEqual(
            claim_response["task_envelope"]["artifacts"]["completion_evidence"]["validated_artifact_ids"],
            [],
        )

    def test_service_completion_claim_clears_satisfied_evidence_metadata_when_pruned(self) -> None:
        service = HarnessApiService(store=FileBackedHarnessStore(self.temp_dir.name))
        task_envelope = create_task_envelope(
            {
                "id": "task-pruned-evidence-metadata-1",
                "title": "Pruned evidence metadata",
                "description": "Completion evidence metadata should reset when all validated ids are stripped.",
                "origin": {
                    "source_system": "openclaw",
                    "source_type": "ingress_request",
                    "source_id": "req-pruned-evidence-metadata-1",
                },
                "acceptance_criteria": [
                    {
                        "id": "ac-1",
                        "description": "Completion requires a reviewed support note.",
                        "required": True,
                    }
                ],
            },
            now="2026-04-07T18:00:00Z",
        )
        task_envelope["artifacts"]["completion_evidence"] = {
            "policy": "required",
            "status": "deferred",
            "required_artifact_types": ["review_note"],
            "validated_artifact_ids": [],
            "validation_method": "deferred",
            "validated_at": None,
            "validator": None,
            "notes": None,
        }
        submit_status, submit_response = service.submit({"request": {"task_envelope": task_envelope}})
        task_id = submit_response["task_envelope"]["id"]

        claim_status, claim_response = service.submit_completion_claim(
            task_id,
            {
                "request": {
                    **_completion_claim_payload(claim_id="claim-pruned-evidence-metadata-1"),
                    **_execution_attempt_payload(attempt_id="attempt-pruned-evidence-metadata-1"),
                    "new_artifacts": [_review_note_artifact("artifact-review-note-pruned-1")],
                    "completion_evidence": {
                        "status": "satisfied",
                        "validated_artifact_ids": ["artifact-review-note-pruned-1"],
                        "validation_method": "manual_review",
                        "validated_at": "2026-04-07T18:05:00Z",
                        "validator": {
                            "source_system": "harness",
                            "source_type": "verification",
                            "source_id": "verification-pruned-1",
                            "captured_by": "executor",
                        },
                    },
                    "acceptance_criteria_satisfied": True,
                    "runtime_facts": {"executor_reported_success": True, "attempt_count": 1},
                }
            },
        )

        self.assertEqual(submit_status, 200)
        self.assertEqual(claim_status, 200)
        self.assertFalse(claim_response["accepted_completion"])
        evidence = claim_response["task_envelope"]["artifacts"]["completion_evidence"]
        self.assertEqual(evidence["validated_artifact_ids"], [])
        self.assertEqual(evidence["status"], "deferred")
        self.assertIsNone(evidence["validated_at"])
        self.assertIsNone(evidence["validator"])
        self.assertEqual(evidence["validation_method"], "deferred")

    def test_service_completion_claim_strips_executor_verified_status_from_changed_file_artifacts(self) -> None:
        service = HarnessApiService(store=FileBackedHarnessStore(self.temp_dir.name))
        payload = _manual_happy_path_overlay_payload()
        task_envelope = deepcopy(payload["request"]["task_envelope"])
        task_envelope["id"] = "task-changed-file-claim-1"
        task_envelope["title"] = "Changed file completion claim"
        task_envelope["description"] = "Completion claims should not self-certify changed-file artifacts."
        task_envelope["artifacts"]["completion_evidence"] = {
            "policy": "required",
            "status": "deferred",
            "required_artifact_types": ["changed_file"],
            "validated_artifact_ids": [],
            "validation_method": "deferred",
            "validated_at": None,
            "validator": None,
            "notes": None,
        }
        submit_status, submit_response = service.submit({"request": {"task_envelope": task_envelope}})
        task_id = submit_response["task_envelope"]["id"]
        stored_task = deepcopy(service.store.get_task(task_id))
        stored_task["artifacts"]["items"] = deepcopy(payload["request"]["linked_artifacts"])
        service.store.update_task(stored_task)

        claim_status, claim_response = service.submit_completion_claim(
            task_id,
            {
                "request": {
                    **_completion_claim_payload(claim_id="claim-changed-file-verified-1"),
                    **_execution_attempt_payload(attempt_id="attempt-changed-file-verified-1"),
                    "new_artifacts": [_changed_file_artifact("artifact-changed-file-claim-1")],
                    "completion_evidence": {
                        "validated_artifact_ids": ["artifact-changed-file-claim-1"],
                        "validation_method": "manual_review",
                    },
                    "external_facts": deepcopy(payload["request"]["external_facts"]),
                    "acceptance_criteria_satisfied": True,
                    "runtime_facts": {"executor_reported_success": True, "attempt_count": 1},
                }
            },
        )

        self.assertEqual(submit_status, 200)
        self.assertEqual(claim_status, 200)
        self.assertFalse(claim_response["accepted_completion"])
        self.assertNotEqual(claim_response["task_envelope"]["status"], "completed")
        changed_file_artifact = next(
            artifact
            for artifact in claim_response["task_envelope"]["artifacts"]["items"]
            if artifact["id"] == "artifact-changed-file-claim-1"
        )
        self.assertEqual(changed_file_artifact["verification_status"], "unverified")
        self.assertEqual(
            changed_file_artifact["metadata"]["submitted_verification_status"],
            "verified",
        )
        self.assertEqual(
            claim_response["task_envelope"]["artifacts"]["completion_evidence"]["validated_artifact_ids"],
            [],
        )

    def test_service_completion_claim_strips_executor_verified_status_from_branch_artifacts(self) -> None:
        service = HarnessApiService(store=FileBackedHarnessStore(self.temp_dir.name))
        payload = _manual_happy_path_overlay_payload()
        task_envelope = deepcopy(payload["request"]["task_envelope"])
        task_envelope["id"] = "task-branch-claim-1"
        task_envelope["title"] = "Branch completion claim"
        task_envelope["description"] = "Completion claims should not self-certify branch artifacts."
        task_envelope["artifacts"]["completion_evidence"] = {
            "policy": "required",
            "status": "deferred",
            "required_artifact_types": ["branch"],
            "validated_artifact_ids": [],
            "validation_method": "deferred",
            "validated_at": None,
            "validator": None,
            "notes": None,
        }
        submit_status, submit_response = service.submit({"request": {"task_envelope": task_envelope}})
        task_id = submit_response["task_envelope"]["id"]
        stored_task = deepcopy(service.store.get_task(task_id))
        stored_task["artifacts"]["items"] = deepcopy(payload["request"]["linked_artifacts"])
        service.store.update_task(stored_task)

        claim_status, claim_response = service.submit_completion_claim(
            task_id,
            {
                "request": {
                    **_completion_claim_payload(claim_id="claim-branch-verified-1"),
                    **_execution_attempt_payload(attempt_id="attempt-branch-verified-1"),
                    "new_artifacts": [_branch_artifact("artifact-branch-claim-1")],
                    "completion_evidence": {
                        "validated_artifact_ids": ["artifact-branch-claim-1"],
                        "validation_method": "manual_review",
                    },
                    "external_facts": deepcopy(payload["request"]["external_facts"]),
                    "acceptance_criteria_satisfied": True,
                    "runtime_facts": {"executor_reported_success": True, "attempt_count": 1},
                }
            },
        )

        self.assertEqual(submit_status, 200)
        self.assertEqual(claim_status, 200)
        self.assertFalse(claim_response["accepted_completion"])
        self.assertNotEqual(claim_response["task_envelope"]["status"], "completed")
        branch_artifact = next(
            artifact
            for artifact in claim_response["task_envelope"]["artifacts"]["items"]
            if artifact["id"] == "artifact-branch-claim-1"
        )
        self.assertEqual(branch_artifact["verification_status"], "unverified")
        self.assertEqual(
            branch_artifact["metadata"]["submitted_verification_status"],
            "verified",
        )
        self.assertEqual(
            claim_response["task_envelope"]["artifacts"]["completion_evidence"]["validated_artifact_ids"],
            [],
        )

    def test_service_completion_claim_allows_missing_commit_when_branch_can_be_reconciled(self) -> None:
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_no_create_pull_request_gateway(),
        )
        payload = _manual_happy_path_overlay_payload()
        submit_payload = {
            "request": {
                "task_envelope": deepcopy(payload["request"]["task_envelope"]),
            }
        }
        submit_status, submit_response = service.submit(submit_payload)
        task_id = submit_response["task_envelope"]["id"]

        pending_commit_attempt_payload = _execution_attempt_payload(attempt_id="attempt-valid-missing-commit-1")
        pending_commit_attempt_payload["execution_attempt"]["artifact_references"] = [
            {
                "reference_id": "attempt-valid-missing-commit-1:branch",
                "artifact_type": "branch",
                "location": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/tree/codex/e2e-test",
                "metadata": {
                    "repository_host": "github.com",
                    "repository_owner": "KnoxAnalytics",
                    "repository_name": "HARNESS-DRYRUN",
                    "branch_name": "codex/e2e-test",
                },
            }
        ]
        external_facts = deepcopy(payload["request"]["external_facts"])
        external_facts.pop("github_facts", None)

        claim_status, claim_response = service.submit_completion_claim(
            task_id,
            {
                "request": {
                    **_completion_claim_payload(claim_id="claim-valid-missing-commit-1"),
                    **pending_commit_attempt_payload,
                    "runtime_facts": {"executor_reported_success": True, "attempt_count": 1},
                    "external_facts": external_facts,
                }
            },
        )

        self.assertEqual(submit_status, 200)
        self.assertEqual(claim_status, 200)
        self.assertEqual(claim_response["action"], "reconciliation_failed")
        latest_attempt = claim_response["task_envelope"]["observability"]["execution_metadata"]["execution_attempts"][-1]
        self.assertEqual(latest_attempt["metadata"]["attempt_validation"]["status"], "valid")
        self.assertTrue(
            latest_attempt["metadata"]["attempt_validation"]["context_observations"]["commit_resolution_pending"]
        )
        self.assertNotIn("invalid_execution_attempt", claim_response)

    def test_service_dispatch_task_records_attempt_and_runs_reevaluation(self) -> None:
        payload = _manual_happy_path_overlay_payload()
        evaluate_payload = {
            "request": {
                "task_envelope": deepcopy(payload["request"]["task_envelope"]),
                "task_status": "dispatch_ready",
            }
        }
        submit_status, submit_response = self.service.evaluate(evaluate_payload)
        task_id = submit_response["task_envelope"]["id"]

        dispatch_status, dispatch_response = self.service.dispatch_task(
            task_id,
            {
                "request": {
                    "executor": "codex",
                    "execution_parameters": {"mode": "manual"},
                    "artifact_references": [
                        {
                            "reference_id": "attempt-1:pr",
                            "artifact_type": "pull_request",
                            "location": "https://github.com/sfayka/Harness/pull/999",
                            "metadata": {
                                "branch_name": "codex/manual-task-dispatch",
                                "commit_sha": "abc123",
                            },
                        }
                    ],
                }
            },
        )
        timeline_status, timeline_payload = self.service.get_task_timeline(task_id)
        read_model_status, read_model_payload = self.service.get_task_read_model(task_id)

        self.assertEqual(submit_status, 200)
        self.assertEqual(submit_response["task_envelope"]["status"], "dispatch_ready")
        self.assertEqual(dispatch_status, 200)
        self.assertEqual(dispatch_response["dispatch"]["attempt_id"], "attempt-1")
        self.assertEqual(dispatch_response["dispatch"]["executor"], "codex")
        self.assertIn(
            dispatch_response["dispatch"]["attempt_status"],
            {"started", "in_progress", "completed", "failed", "blocked"},
        )
        self.assertEqual(timeline_status, 200)
        self.assertTrue(any(event["event_type"] == "task_dispatched" for event in timeline_payload["timeline"]))
        self.assertTrue(any(event["event_type"] == "execution_event_recorded" for event in timeline_payload["timeline"]))
        self.assertTrue(any(event["event_type"] == "execution_artifact_attached" for event in timeline_payload["timeline"]))
        self.assertEqual(read_model_status, 200)
        self.assertEqual(read_model_payload["task"]["execution_summary"]["attempt_count"], 1)

    def test_service_dispatch_task_uses_event_timestamps_when_adapter_events_arrive_out_of_order(self) -> None:
        payload = _manual_happy_path_overlay_payload()
        evaluate_payload = {
            "request": {
                "task_envelope": deepcopy(payload["request"]["task_envelope"]),
                "task_status": "dispatch_ready",
            }
        }
        submit_status, submit_response = self.service.evaluate(evaluate_payload)
        task_id = submit_response["task_envelope"]["id"]

        with patch("modules.api.StubExecutorAdapter", return_value=_OutOfOrderDispatchAdapter()):
            dispatch_status, dispatch_response = self.service.dispatch_task(task_id, {"request": {"executor": "codex"}})

        latest_attempt = dispatch_response["task_envelope"]["observability"]["execution_metadata"]["execution_attempts"][-1]

        self.assertEqual(submit_status, 200)
        self.assertEqual(dispatch_status, 200)
        self.assertEqual(latest_attempt["metadata"]["dispatch_at"], "2026-04-11T09:05:00Z")
        self.assertEqual(latest_attempt["recorded_at"], "2026-04-11T09:10:00Z")

    def test_service_dispatch_task_can_use_injected_codex_cloud_adapter(self) -> None:
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            executor_adapters={
                "codex": CodexCloudExecutorAdapter(runtime_client=_FakeCodexCloudRuntimeClient()),
            },
        )
        payload = _manual_happy_path_overlay_payload()
        evaluate_payload = {
            "request": {
                "task_envelope": deepcopy(payload["request"]["task_envelope"]),
                "task_status": "dispatch_ready",
            }
        }
        submit_status, submit_response = service.evaluate(evaluate_payload)
        task_id = submit_response["task_envelope"]["id"]

        dispatch_status, dispatch_response = service.dispatch_task(task_id, {"request": {"executor": "codex"}})

        latest_attempt = dispatch_response["task_envelope"]["observability"]["execution_metadata"]["execution_attempts"][-1]
        artifact_types = [item["artifact_type"] for item in latest_attempt["artifact_references"]]

        self.assertEqual(submit_status, 200)
        self.assertEqual(dispatch_status, 200)
        self.assertEqual(dispatch_response["dispatch"]["executor"], "codex")
        self.assertEqual(latest_attempt["metadata"]["executor"], "codex")
        self.assertEqual(latest_attempt["metadata"]["execution_events"][-1]["metadata"]["adapter"], "codex-cloud")
        self.assertEqual(artifact_types, ["branch", "commit", "pull_request"])

    def test_service_submit_auto_dispatches_dispatch_ready_task(self) -> None:
        payload = _manual_happy_path_overlay_payload()
        submit_payload = {
            "request": {
                "task_envelope": deepcopy(payload["request"]["task_envelope"]),
                "task_status": "dispatch_ready",
            }
        }

        submit_status, submit_response = self.service.submit(submit_payload)
        task_id = submit_response["task_envelope"]["id"]
        read_model_status, read_model_payload = self.service.get_task_read_model(task_id)
        timeline_status, timeline_payload = self.service.get_task_timeline(task_id)

        self.assertEqual(submit_status, 200)
        self.assertTrue(submit_response["automatic_dispatch"]["attempted"])
        self.assertEqual(submit_response["automatic_dispatch"]["status"], 200)
        self.assertEqual(submit_response["automatic_dispatch"]["dispatch"]["attempt_id"], "attempt-1")
        self.assertEqual(read_model_status, 200)
        self.assertNotEqual(read_model_payload["task"]["current_status"], "dispatch_ready")
        self.assertEqual(read_model_payload["task"]["execution_summary"]["attempt_count"], 1)
        self.assertEqual(read_model_payload["task"]["execution_summary"]["latest_dispatch_origin"], "automatic")
        self.assertEqual(timeline_status, 200)
        dispatch_events = [event for event in timeline_payload["timeline"] if event["event_type"] == "task_dispatched"]
        self.assertTrue(dispatch_events)
        self.assertEqual(dispatch_events[-1]["details"]["dispatch_mode"], "automatic")
        dispatch_triggers = {event["details"]["dispatch_trigger"] for event in dispatch_events}
        self.assertIn("automatic_policy_post_ingestion", dispatch_triggers)
        self.assertNotIn("invalid_execution_attempt_retry", dispatch_triggers)

    def test_service_submit_does_not_auto_dispatch_planned_task(self) -> None:
        payload = _manual_happy_path_overlay_payload()
        submit_payload = {
            "request": {
                "task_envelope": deepcopy(payload["request"]["task_envelope"]),
                "task_status": "planned",
            }
        }

        submit_status, submit_response = self.service.submit(submit_payload)
        task_id = submit_response["task_envelope"]["id"]
        timeline_status, timeline_payload = self.service.get_task_timeline(task_id)

        self.assertEqual(submit_status, 200)
        self.assertFalse(submit_response["automatic_dispatch"]["attempted"])
        self.assertFalse(submit_response["automatic_dispatch"]["dispatchable"])
        self.assertEqual(timeline_status, 200)
        dispatch_events = [event for event in timeline_payload["timeline"] if event["event_type"] == "task_dispatched"]
        self.assertFalse(dispatch_events)

    def test_service_dispatch_rejects_planned_task_until_dispatch_ready(self) -> None:
        payload = _manual_happy_path_overlay_payload()
        submit_payload = {
            "request": {
                "task_envelope": deepcopy(payload["request"]["task_envelope"]),
                "task_status": "planned",
            }
        }

        submit_status, submit_response = self.service.submit(submit_payload)
        task_id = submit_response["task_envelope"]["id"]
        dispatch_status, dispatch_response = self.service.dispatch_task(task_id, {"request": {"executor": "codex"}})

        self.assertEqual(submit_status, 200)
        self.assertEqual(dispatch_status, 409)
        self.assertIn("not dispatch-ready", dispatch_response["error"])

    def test_service_dispatch_rejects_terminal_tasks(self) -> None:
        submit_status, submit_payload = self.service.evaluate(_request_payload("accepted_completion"))
        task_id = submit_payload["task_envelope"]["id"]

        dispatch_status, dispatch_response = self.service.dispatch_task(task_id, {"request": {"executor": "codex"}})

        self.assertEqual(submit_status, 200)
        self.assertEqual(dispatch_status, 409)
        self.assertIn("terminal", dispatch_response["error"])

    def test_service_evaluate_existing_review_required_task_cannot_be_overwritten_to_completed(self) -> None:
        initial_status, initial_response = self.service.evaluate(_request_payload("review_required"))
        task_id = initial_response["task_envelope"]["id"]

        overwrite_payload = _request_payload("accepted_completion")
        overwrite_payload["request"]["task_envelope"]["id"] = task_id
        overwrite_payload["request"]["task_envelope"]["status"] = "completed"
        overwrite_payload["request"]["task_envelope"]["timestamps"]["completed_at"] = "2026-03-24T18:00:00Z"

        overwrite_status, overwrite_response = self.service.evaluate(overwrite_payload)
        task_status, task_payload = self.service.get_task(task_id)
        history_status, history_payload = self.service.get_evaluation_history(task_id)

        self.assertEqual(initial_status, 200)
        self.assertEqual(initial_response["task_envelope"]["status"], "in_review")
        self.assertEqual(overwrite_status, 200)
        self.assertEqual(overwrite_response["action"], "review_required")
        self.assertEqual(overwrite_response["task_envelope"]["status"], "in_review")
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["status"], "in_review")
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 2)

    def test_service_can_resolve_legacy_completed_review_gate_via_manual_decision(self) -> None:
        initial_status, initial_response = self.service.evaluate(_request_payload("review_required"))
        task_id = initial_response["task_envelope"]["id"]
        stored_task = deepcopy(self.service.store.get_task(task_id))
        stored_task["status"] = "completed"
        stored_task["timestamps"]["completed_at"] = "2026-03-24T18:05:00Z"
        self.service.store.update_task(stored_task)

        resolution_status, resolution_response = self.service.reevaluate(
            task_id,
            {"request": {"review_decision": _review_decision_payload(task_id)}},
        )
        task_status, task_payload = self.service.get_task(task_id)
        history_status, history_payload = self.service.get_evaluation_history(task_id)

        self.assertEqual(initial_status, 200)
        self.assertEqual(resolution_status, 200)
        self.assertEqual(resolution_response["task_envelope"]["status"], "completed")
        self.assertEqual(resolution_response["target_status"], "completed")
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["status"], "completed")
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 2)

    def test_service_reevaluate_authorize_redispatch_auto_dispatches_follow_up(self) -> None:
        initial_payload = _request_payload("review_required")
        initial_payload["request"]["review_request"]["allowed_outcomes"] = [
            "accept_completion",
            "authorize_redispatch",
        ]
        initial_status, initial_response = self.service.evaluate(initial_payload)
        task_id = initial_response["task_envelope"]["id"]

        stored_task = deepcopy(self.service.store.get_task(task_id))
        stored_task["observability"]["execution_metadata"]["execution_attempts"] = [
            {
                "attempt_id": "attempt-1",
                "recorded_at": "2026-03-24T17:05:00Z",
                "status": "completed",
                "reported_by": "codex",
                "completion_claim_id": "claim-prior-1",
                "artifact_references": [],
                "metadata": {"dispatch_trigger": "manual_api"},
                "reevaluation": {
                    "evaluation_id": "evaluation-prior-1",
                    "linked_at": "2026-03-24T17:06:00Z",
                    "action": "review_required",
                },
            }
        ]
        self.service.store.update_task(stored_task)

        resolution_status, resolution_response = self.service.reevaluate(
            task_id,
            {
                "request": {
                    "review_decision": _review_decision_payload(
                        task_id,
                        outcome=ReviewOutcome.AUTHORIZE_REDISPATCH,
                        allowed_outcomes=(
                            ReviewOutcome.ACCEPT_COMPLETION,
                            ReviewOutcome.AUTHORIZE_REDISPATCH,
                        ),
                    )
                }
            },
        )
        timeline_status, timeline_payload = self.service.get_task_timeline(task_id)
        read_status, read_payload = self.service.get_task_read_model(task_id)

        self.assertEqual(initial_status, 200)
        self.assertEqual(resolution_status, 200)
        self.assertEqual(resolution_response["target_status"], "failed")
        self.assertTrue(resolution_response["automatic_dispatch"]["attempted"])
        self.assertEqual(resolution_response["automatic_dispatch"]["status"], 200)
        self.assertEqual(resolution_response["automatic_dispatch"]["dispatch"]["attempt_id"], "attempt-2")
        self.assertEqual(resolution_response["task_envelope"]["status"], "failed")
        self.assertEqual(timeline_status, 200)
        dispatch_events = [event for event in timeline_payload["timeline"] if event["event_type"] == "task_dispatched"]
        self.assertTrue(dispatch_events)
        self.assertEqual(dispatch_events[-1]["details"]["dispatch_trigger"], "manual_review_authorize_redispatch")
        self.assertEqual(read_status, 200)
        self.assertEqual(read_payload["task"]["execution_summary"]["attempt_count"], 2)

    def test_service_reevaluate_authorize_retry_without_assignment_keeps_review_gate_active(self) -> None:
        initial_payload = _request_payload("review_required")
        initial_payload["request"]["review_request"]["allowed_outcomes"] = [
            "accept_completion",
            "authorize_retry",
        ]
        initial_status, initial_response = self.service.evaluate(initial_payload)
        task_id = initial_response["task_envelope"]["id"]

        resolution_status, resolution_response = self.service.reevaluate(
            task_id,
            {
                "request": {
                    "review_decision": _review_decision_payload(
                        task_id,
                        outcome=ReviewOutcome.AUTHORIZE_RETRY,
                        allowed_outcomes=(
                            ReviewOutcome.ACCEPT_COMPLETION,
                            ReviewOutcome.AUTHORIZE_RETRY,
                        ),
                    )
                }
            },
        )
        read_status, read_payload = self.service.get_task_read_model(task_id)
        timeline_status, timeline_payload = self.service.get_task_timeline(task_id)

        self.assertEqual(initial_status, 200)
        self.assertEqual(resolution_status, 200)
        self.assertEqual(resolution_response["action"], "transition_rejected")
        self.assertTrue(resolution_response["requires_review"])
        self.assertEqual(resolution_response["task_envelope"]["status"], "in_review")
        self.assertEqual(read_status, 200)
        self.assertEqual(read_payload["task"]["review_summary"]["status"], "requested")
        self.assertEqual(timeline_status, 200)
        self.assertTrue(
            any(event["event_type"] == "review_decision_rejected" for event in timeline_payload["timeline"])
        )
        self.assertFalse(any(event["event_type"] == "review_decided" for event in timeline_payload["timeline"]))

    def test_service_reevaluate_can_accept_completion_after_rejected_retry_attempt(self) -> None:
        initial_payload = _request_payload("review_required")
        initial_payload["request"]["review_request"]["allowed_outcomes"] = [
            "accept_completion",
            "authorize_retry",
        ]
        initial_status, initial_response = self.service.evaluate(initial_payload)
        task_id = initial_response["task_envelope"]["id"]

        rejected_status, rejected_response = self.service.reevaluate(
            task_id,
            {
                "request": {
                    "review_decision": _review_decision_payload(
                        task_id,
                        outcome=ReviewOutcome.AUTHORIZE_RETRY,
                        allowed_outcomes=(
                            ReviewOutcome.ACCEPT_COMPLETION,
                            ReviewOutcome.AUTHORIZE_RETRY,
                        ),
                    )
                }
            },
        )
        accepted_status, accepted_response = self.service.reevaluate(
            task_id,
            {
                "request": {
                    "review_decision": _review_decision_payload(
                        task_id,
                        outcome=ReviewOutcome.ACCEPT_COMPLETION,
                        allowed_outcomes=(
                            ReviewOutcome.ACCEPT_COMPLETION,
                            ReviewOutcome.AUTHORIZE_RETRY,
                        ),
                    )
                }
            },
        )

        self.assertEqual(initial_status, 200)
        self.assertEqual(rejected_status, 200)
        self.assertEqual(rejected_response["action"], "transition_rejected")
        self.assertEqual(accepted_status, 200)
        self.assertEqual(accepted_response["action"], "transition_applied")
        self.assertEqual(accepted_response["task_envelope"]["status"], "completed")

    def test_service_reevaluate_authorize_replan_clears_prior_completion_evidence(self) -> None:
        initial_payload = _request_payload("review_required")
        initial_payload["request"]["review_request"]["allowed_outcomes"] = [
            "accept_completion",
            "authorize_replan",
        ]
        initial_status, initial_response = self.service.evaluate(initial_payload)
        task_id = initial_response["task_envelope"]["id"]

        resolution_status, resolution_response = self.service.reevaluate(
            task_id,
            {
                "request": {
                    "review_decision": _review_decision_payload(
                        task_id,
                        outcome=ReviewOutcome.AUTHORIZE_REPLAN,
                        allowed_outcomes=(
                            ReviewOutcome.ACCEPT_COMPLETION,
                            ReviewOutcome.AUTHORIZE_REPLAN,
                        ),
                    )
                }
            },
        )
        evidence = resolution_response["task_envelope"]["artifacts"]["completion_evidence"]
        follow_up_status, follow_up_response = self.service.reevaluate(
            task_id,
            {
                "request": {
                    "external_facts": deepcopy(_request_payload("accepted_completion")["request"]["external_facts"]),
                    "runtime_facts": deepcopy(_request_payload("accepted_completion")["request"]["runtime_facts"]),
                    "claimed_completion": True,
                    "acceptance_criteria_satisfied": True,
                }
            },
        )

        self.assertEqual(initial_status, 200)
        self.assertEqual(resolution_status, 200)
        self.assertEqual(resolution_response["action"], "follow_up_authorized")
        self.assertEqual(resolution_response["task_envelope"]["status"], "planned")
        self.assertEqual(evidence["validated_artifact_ids"], [])
        self.assertEqual(evidence["status"], "deferred")
        self.assertIsNone(evidence["validated_at"])
        self.assertIsNone(evidence["validator"])
        self.assertEqual(evidence["validation_method"], "deferred")
        self.assertEqual(follow_up_status, 200)
        self.assertFalse(follow_up_response["accepted_completion"])
        self.assertNotEqual(follow_up_response["task_envelope"]["status"], "completed")

    def test_service_reevaluate_reject_completion_clears_prior_completion_evidence(self) -> None:
        initial_payload = _request_payload("review_required")
        initial_payload["request"]["review_request"]["allowed_outcomes"] = [
            "accept_completion",
            "reject_completion",
        ]
        initial_status, initial_response = self.service.evaluate(initial_payload)
        task_id = initial_response["task_envelope"]["id"]

        resolution_status, resolution_response = self.service.reevaluate(
            task_id,
            {
                "request": {
                    "review_decision": _review_decision_payload(
                        task_id,
                        outcome=ReviewOutcome.REJECT_COMPLETION,
                        allowed_outcomes=(
                            ReviewOutcome.ACCEPT_COMPLETION,
                            ReviewOutcome.REJECT_COMPLETION,
                        ),
                    )
                }
            },
        )
        evidence = resolution_response["task_envelope"]["artifacts"]["completion_evidence"]
        follow_up_status, follow_up_response = self.service.reevaluate(
            task_id,
            {
                "request": {
                    "external_facts": deepcopy(_request_payload("accepted_completion")["request"]["external_facts"]),
                    "runtime_facts": deepcopy(_request_payload("accepted_completion")["request"]["runtime_facts"]),
                    "claimed_completion": True,
                    "acceptance_criteria_satisfied": True,
                }
            },
        )

        self.assertEqual(initial_status, 200)
        self.assertEqual(resolution_status, 200)
        self.assertEqual(resolution_response["action"], "transition_applied")
        self.assertEqual(resolution_response["task_envelope"]["status"], "blocked")
        self.assertEqual(evidence["validated_artifact_ids"], [])
        self.assertEqual(evidence["status"], "deferred")
        self.assertIsNone(evidence["validated_at"])
        self.assertIsNone(evidence["validator"])
        self.assertEqual(evidence["validation_method"], "deferred")
        self.assertEqual(follow_up_status, 200)
        self.assertFalse(follow_up_response["accepted_completion"])
        self.assertNotEqual(follow_up_response["task_envelope"]["status"], "completed")

    def test_service_reevaluate_require_clarification_creates_canonical_clarification_block(self) -> None:
        initial_payload = _request_payload("review_required")
        initial_payload["request"]["review_request"]["allowed_outcomes"] = [
            "accept_completion",
            "require_clarification",
        ]
        initial_status, initial_response = self.service.evaluate(initial_payload)
        task_id = initial_response["task_envelope"]["id"]

        resolution_status, resolution_response = self.service.reevaluate(
            task_id,
            {
                "request": {
                    "review_decision": build_review_decision_from_request(
                        initial_response["enforcement_result"]["review_request"],
                        outcome="require_clarification",
                    )
                }
            },
        )
        read_status, read_payload = self.service.get_task_read_model(task_id)
        timeline_status, timeline_payload = self.service.get_task_timeline(task_id)

        self.assertEqual(initial_status, 200)
        self.assertEqual(initial_response["task_envelope"]["status"], "in_review")
        self.assertEqual(resolution_status, 200)
        self.assertEqual(resolution_response["action"], "follow_up_authorized")
        self.assertEqual(resolution_response["task_envelope"]["status"], "blocked")
        self.assertEqual(resolution_response["task_envelope"]["clarification"]["status"], "required")
        self.assertEqual(
            resolution_response["task_envelope"]["clarification"]["resume_target_status"],
            "intake_ready",
        )
        self.assertEqual(
            resolution_response["task_envelope"]["clarification"]["requested_by"],
            "manual_review",
        )
        self.assertEqual(
            resolution_response["task_envelope"]["clarification"]["required_inputs"][0]["description"],
            "Manual review authorized the next control-plane action.",
        )
        self.assertEqual(read_status, 200)
        self.assertEqual(read_payload["task"]["clarification_summary"]["status"], "required")
        self.assertEqual(read_payload["task"]["clarification_summary"]["resume_target_status"], "intake_ready")
        self.assertEqual(timeline_status, 200)
        self.assertTrue(
            any(event["event_type"] == "clarification_required" for event in timeline_payload["timeline"])
        )

    def test_service_reevaluate_manual_review_clarification_from_assigned_resumes_original_assignment(self) -> None:
        initial_payload = _request_payload("review_required")
        initial_payload["request"]["task_envelope"]["status"] = "assigned"
        initial_payload["request"]["task_envelope"]["assigned_executor"] = {
            "executor_type": "codex",
            "executor_id": "executor-review-clarification-resume-1",
            "assignment_reason": "Resume assigned work after manual review clarification.",
        }
        initial_payload["request"]["review_request"]["allowed_outcomes"] = [
            "accept_completion",
            "require_clarification",
        ]
        initial_status, initial_response = self.service.evaluate(initial_payload)
        task_id = initial_response["task_envelope"]["id"]

        blocked_status, blocked_response = self.service.reevaluate(
            task_id,
            {
                "request": {
                    "review_decision": build_review_decision_from_request(
                        initial_response["enforcement_result"]["review_request"],
                        outcome="require_clarification",
                    )
                }
            },
        )
        resolved_status, resolved_response = self.service.reevaluate(
            task_id,
            {"request": {"claimed_completion": False, "acceptance_criteria_satisfied": False}},
        )
        read_status, read_payload = self.service.get_task_read_model(task_id)

        self.assertEqual(initial_status, 200)
        self.assertEqual(blocked_status, 200)
        self.assertEqual(blocked_response["task_envelope"]["status"], "blocked")
        self.assertEqual(blocked_response["task_envelope"]["clarification"]["resume_target_status"], "assigned")
        self.assertEqual(resolved_status, 200)
        self.assertEqual(resolved_response["task_envelope"]["status"], "assigned")
        self.assertEqual(
            resolved_response["task_envelope"]["assigned_executor"]["executor_id"],
            "executor-review-clarification-resume-1",
        )
        self.assertEqual(resolved_response["task_envelope"]["clarification"]["status"], "resolved")
        self.assertEqual(read_status, 200)
        self.assertEqual(read_payload["task"]["current_status"], "assigned")
        self.assertEqual(
            read_payload["task"]["assigned_executor"]["executor_id"],
            "executor-review-clarification-resume-1",
        )

    def test_service_reevaluate_manual_review_clarification_from_dispatch_ready_auto_dispatches(self) -> None:
        initial_payload = _request_payload("review_required")
        initial_payload["request"]["task_envelope"]["status"] = "dispatch_ready"
        initial_payload["request"]["review_request"]["allowed_outcomes"] = [
            "accept_completion",
            "require_clarification",
        ]
        initial_status, initial_response = self.service.evaluate(initial_payload)
        task_id = initial_response["task_envelope"]["id"]

        blocked_status, blocked_response = self.service.reevaluate(
            task_id,
            {
                "request": {
                    "review_decision": build_review_decision_from_request(
                        initial_response["enforcement_result"]["review_request"],
                        outcome="require_clarification",
                    )
                }
            },
        )
        resolved_status, resolved_response = self.service.reevaluate(
            task_id,
            {"request": {"claimed_completion": False, "acceptance_criteria_satisfied": False}},
        )
        timeline_status, timeline_payload = self.service.get_task_timeline(task_id)
        execution_attempts = (
            ((resolved_response["task_envelope"].get("observability") or {}).get("execution_metadata") or {}).get(
                "execution_attempts"
            )
            or []
        )

        self.assertEqual(initial_status, 200)
        self.assertEqual(blocked_status, 200)
        self.assertEqual(blocked_response["task_envelope"]["status"], "blocked")
        self.assertEqual(blocked_response["task_envelope"]["clarification"]["resume_target_status"], "dispatch_ready")
        self.assertEqual(resolved_status, 200)
        self.assertEqual(resolved_response["task_envelope"]["clarification"]["status"], "resolved")
        self.assertTrue(resolved_response["automatic_dispatch"]["attempted"])
        self.assertEqual(resolved_response["automatic_dispatch"]["dispatch"]["attempt_id"], "attempt-1")
        self.assertEqual(len(execution_attempts), 1)
        self.assertEqual(timeline_status, 200)
        dispatch_events = [event for event in timeline_payload["timeline"] if event["event_type"] == "task_dispatched"]
        self.assertTrue(
            any(event["event_type"] == "clarification_resolved" for event in timeline_payload["timeline"])
        )
        self.assertEqual(dispatch_events[-1]["details"]["dispatch_trigger"], "automatic_policy_post_reevaluation")

    def test_service_reevaluate_authorize_retry_with_assignment_clears_prior_completion_evidence(self) -> None:
        initial_payload = _request_payload("review_required")
        initial_payload["request"]["review_request"]["allowed_outcomes"] = [
            "accept_completion",
            "authorize_retry",
        ]
        initial_status, initial_response = self.service.evaluate(initial_payload)
        task_id = initial_response["task_envelope"]["id"]

        stored_task = deepcopy(self.service.store.get_task(task_id))
        stored_task["assigned_executor"] = {
            "executor_type": "codex",
            "executor_id": "executor-review-retry-proof-reset-1",
            "assignment_reason": "Seed active assignment for authorize_retry proof reset coverage.",
        }
        self.service.store.update_task(stored_task)

        resolution_status, resolution_response = self.service.reevaluate(
            task_id,
            {
                "request": {
                    "review_decision": _review_decision_payload(
                        task_id,
                        outcome=ReviewOutcome.AUTHORIZE_RETRY,
                        allowed_outcomes=(
                            ReviewOutcome.ACCEPT_COMPLETION,
                            ReviewOutcome.AUTHORIZE_RETRY,
                        ),
                    )
                }
            },
        )
        evidence = resolution_response["task_envelope"]["artifacts"]["completion_evidence"]
        follow_up_status, follow_up_response = self.service.reevaluate(
            task_id,
            {
                "request": {
                    "external_facts": deepcopy(_request_payload("accepted_completion")["request"]["external_facts"]),
                    "runtime_facts": deepcopy(_request_payload("accepted_completion")["request"]["runtime_facts"]),
                    "claimed_completion": True,
                    "acceptance_criteria_satisfied": True,
                }
            },
        )

        self.assertEqual(initial_status, 200)
        self.assertEqual(resolution_status, 200)
        self.assertEqual(resolution_response["action"], "follow_up_authorized")
        self.assertEqual(resolution_response["task_envelope"]["status"], "assigned")
        self.assertEqual(
            resolution_response["task_envelope"]["assigned_executor"]["executor_id"],
            "executor-review-retry-proof-reset-1",
        )
        self.assertEqual(evidence["validated_artifact_ids"], [])
        self.assertEqual(evidence["status"], "deferred")
        self.assertIsNone(evidence["validated_at"])
        self.assertIsNone(evidence["validator"])
        self.assertEqual(evidence["validation_method"], "deferred")
        self.assertEqual(follow_up_status, 200)
        self.assertFalse(follow_up_response["accepted_completion"])
        self.assertNotEqual(follow_up_response["task_envelope"]["status"], "completed")

    def test_service_reevaluate_authorize_replan_clears_active_assignment(self) -> None:
        initial_payload = _request_payload("review_required")
        initial_payload["request"]["task_envelope"]["status"] = "assigned"
        initial_payload["request"]["task_envelope"]["assigned_executor"] = {
            "executor_type": "codex",
            "executor_id": "executor-review-replan-clear-1",
            "assignment_reason": "Seed active assignment for review replan coverage.",
        }
        initial_payload["request"]["review_request"]["allowed_outcomes"] = [
            "accept_completion",
            "authorize_replan",
        ]
        initial_status, initial_response = self.service.evaluate(initial_payload)
        task_id = initial_response["task_envelope"]["id"]

        resolution_status, resolution_response = self.service.reevaluate(
            task_id,
            {
                "request": {
                    "review_decision": build_review_decision_from_request(
                        initial_response["enforcement_result"]["review_request"],
                        outcome="authorize_replan",
                    )
                }
            },
        )
        read_status, read_payload = self.service.get_task_read_model(task_id)

        self.assertEqual(initial_status, 200)
        self.assertEqual(resolution_status, 200)
        self.assertEqual(resolution_response["action"], "follow_up_authorized")
        self.assertEqual(resolution_response["task_envelope"]["status"], "planned")
        self.assertIsNone(resolution_response["task_envelope"].get("assigned_executor"))
        self.assertEqual(read_status, 200)
        self.assertEqual(read_payload["task"]["current_status"], "planned")
        self.assertIsNone(read_payload["task"].get("assigned_executor"))

    def test_service_reevaluate_keep_blocked_clears_active_assignment(self) -> None:
        initial_payload = _request_payload("review_required")
        initial_payload["request"]["task_envelope"]["status"] = "assigned"
        initial_payload["request"]["task_envelope"]["assigned_executor"] = {
            "executor_type": "codex",
            "executor_id": "executor-review-blocked-clear-1",
            "assignment_reason": "Seed active assignment for review blocked coverage.",
        }
        initial_payload["request"]["review_request"]["allowed_outcomes"] = [
            "accept_completion",
            "keep_blocked",
        ]
        initial_status, initial_response = self.service.evaluate(initial_payload)
        task_id = initial_response["task_envelope"]["id"]

        resolution_status, resolution_response = self.service.reevaluate(
            task_id,
            {
                "request": {
                    "review_decision": build_review_decision_from_request(
                        initial_response["enforcement_result"]["review_request"],
                        outcome="keep_blocked",
                    )
                }
            },
        )
        read_status, read_payload = self.service.get_task_read_model(task_id)

        self.assertEqual(initial_status, 200)
        self.assertEqual(resolution_status, 200)
        self.assertEqual(resolution_response["action"], "transition_applied")
        self.assertEqual(resolution_response["task_envelope"]["status"], "blocked")
        self.assertIsNone(resolution_response["task_envelope"].get("assigned_executor"))
        self.assertEqual(read_status, 200)
        self.assertEqual(read_payload["task"]["current_status"], "blocked")
        self.assertIsNone(read_payload["task"].get("assigned_executor"))

    def test_service_reevaluate_reject_completion_clears_active_assignment(self) -> None:
        initial_payload = _request_payload("review_required")
        initial_payload["request"]["task_envelope"]["status"] = "assigned"
        initial_payload["request"]["task_envelope"]["assigned_executor"] = {
            "executor_type": "codex",
            "executor_id": "executor-review-reject-clear-1",
            "assignment_reason": "Seed active assignment for review reject coverage.",
        }
        initial_payload["request"]["review_request"]["allowed_outcomes"] = [
            "accept_completion",
            "reject_completion",
        ]
        initial_status, initial_response = self.service.evaluate(initial_payload)
        task_id = initial_response["task_envelope"]["id"]

        resolution_status, resolution_response = self.service.reevaluate(
            task_id,
            {
                "request": {
                    "review_decision": build_review_decision_from_request(
                        initial_response["enforcement_result"]["review_request"],
                        outcome="reject_completion",
                    )
                }
            },
        )
        read_status, read_payload = self.service.get_task_read_model(task_id)

        self.assertEqual(initial_status, 200)
        self.assertEqual(resolution_status, 200)
        self.assertEqual(resolution_response["action"], "transition_applied")
        self.assertEqual(resolution_response["task_envelope"]["status"], "blocked")
        self.assertIsNone(resolution_response["task_envelope"].get("assigned_executor"))
        self.assertEqual(read_status, 200)
        self.assertEqual(read_payload["task"]["current_status"], "blocked")
        self.assertIsNone(read_payload["task"].get("assigned_executor"))

    def test_service_reconciliation_authorize_redispatch_returns_post_dispatch_failure_truth(self) -> None:
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_no_create_pull_request_gateway(),
        )
        payload = _manual_happy_path_overlay_payload()
        submit_status, submit_response = service.submit(
            {"request": {"task_envelope": deepcopy(payload["request"]["task_envelope"])}}
        )
        task_id = submit_response["task_envelope"]["id"]
        stored_task = deepcopy(service.store.get_task(task_id))
        stored_task["status"] = "assigned"
        stored_task["assigned_executor"] = {
            "executor_type": "codex",
            "executor_id": "executor-reconcile-redispatch-1",
            "assignment_reason": "Seed active assignment for reconciliation redispatch coverage.",
        }
        service.store.update_task(stored_task)

        valid_attempt_payload = _execution_attempt_payload(attempt_id="attempt-valid-no-pr-redispatch-1")
        valid_attempt_payload["execution_attempt"]["artifact_references"] = [
            {
                "reference_id": "attempt-valid-no-pr-redispatch-1:commit",
                "artifact_type": "commit",
                "location": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/commit/8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                "metadata": {
                    "repository_host": "github.com",
                    "repository_owner": "KnoxAnalytics",
                    "repository_name": "HARNESS-DRYRUN",
                    "branch_name": "codex/e2e-test",
                    "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                },
            }
        ]
        claim_status, claim_response = service.submit_completion_claim(
            task_id,
            {
                "request": {
                    **_completion_claim_payload(claim_id="claim-valid-no-pr-redispatch-1"),
                    **valid_attempt_payload,
                    "external_facts": deepcopy(payload["request"]["external_facts"]),
                    "runtime_facts": {"executor_reported_success": True, "attempt_count": 1},
                }
            },
        )
        review_request_payload = claim_response["evaluation_record"]["result"]["enforcement_result"]["review_request"]
        review_request = ReviewRequest(
            review_request_id=review_request_payload["review_request_id"],
            task_id=review_request_payload["task_id"],
            requested_at=review_request_payload["requested_at"],
            requested_by=review_request_payload["requested_by"],
            trigger=ReviewTrigger(review_request_payload["trigger"]),
            summary=review_request_payload["summary"],
            presented_sections=tuple(review_request_payload["presented_sections"]),
            allowed_outcomes=tuple(ReviewOutcome(item) for item in review_request_payload["allowed_outcomes"]),
            prior_review_ids=tuple(review_request_payload.get("prior_review_ids", ())),
            metadata=dict(review_request_payload.get("metadata", {})),
        )
        reevaluation_status, reevaluation_response = service.reevaluate(
            task_id,
            {
                "request": {
                    "review_decision": _to_jsonable(
                        resolve_review_request(
                            review_request,
                            review_id="review-reconcile-redispatch-1",
                            reviewer=ReviewerIdentity(
                                reviewer_id="operator-1",
                                reviewer_name="Casey Reviewer",
                                authority_role="operator",
                            ),
                            outcome=ReviewOutcome.AUTHORIZE_REDISPATCH,
                            reasoning="Manual review authorized redispatch for a new grounded execution attempt.",
                        )
                    )
                }
            },
        )

        self.assertEqual(submit_status, 200)
        self.assertEqual(claim_status, 200)
        self.assertEqual(claim_response["task_envelope"]["status"], "in_review")
        self.assertEqual(reevaluation_status, 200)
        self.assertEqual(reevaluation_response["action"], "contract_violation_failed")
        self.assertEqual(reevaluation_response["target_status"], "failed")
        self.assertTrue(reevaluation_response["automatic_dispatch"]["attempted"])
        self.assertEqual(reevaluation_response["automatic_dispatch"]["dispatch"]["attempt_id"], "attempt-2")
        self.assertEqual(reevaluation_response["task_envelope"]["status"], "failed")

    def test_service_reevaluate_rejects_review_decision_with_mismatched_target_status(self) -> None:
        initial_status, initial_response = self.service.evaluate(_request_payload("review_required"))
        task_id = initial_response["task_envelope"]["id"]

        resolution_status, resolution_response = self.service.reevaluate(
            task_id,
            {
                "request": {
                    "review_decision": _tampered_review_decision_payload(
                        task_id,
                        recommended_target_status="failed",
                        authorized_target_status="failed",
                    )
                }
            },
        )

        self.assertEqual(initial_status, 200)
        self.assertEqual(resolution_status, 400)
        self.assertTrue(resolution_response["invalid_input"])
        self.assertIn("review_decision", resolution_response["error"])

    def test_service_reevaluate_rejects_review_decision_with_disallowed_outcome(self) -> None:
        initial_status, initial_response = self.service.evaluate(_request_payload("review_required"))
        task_id = initial_response["task_envelope"]["id"]

        resolution_status, resolution_response = self.service.reevaluate(
            task_id,
            {
                "request": {
                    "review_decision": _tampered_review_decision_payload(
                        task_id,
                        outcome="mark_failed",
                        authorized_target_status="failed",
                        recommended_target_status="failed",
                        allowed_outcomes=("accept_completion",),
                    )
                }
            },
        )

        self.assertEqual(initial_status, 200)
        self.assertEqual(resolution_status, 400)
        self.assertTrue(resolution_response["invalid_input"])
        self.assertIn("not allowed", resolution_response["error"])

    def test_service_reevaluate_rejects_review_decision_without_active_review_gate(self) -> None:
        initial_status, initial_response = self.service.evaluate(_request_payload("accepted_completion"))
        task_id = initial_response["task_envelope"]["id"]

        resolution_status, resolution_response = self.service.reevaluate(
            task_id,
            {"request": {"review_decision": _review_decision_payload(task_id)}},
        )

        self.assertEqual(initial_status, 200)
        self.assertEqual(resolution_status, 400)
        self.assertTrue(resolution_response["invalid_input"])
        self.assertIn("active review", resolution_response["error"])

    def test_service_reevaluate_rejects_review_decision_for_non_active_review_request(self) -> None:
        initial_status, initial_response = self.service.evaluate(_request_payload("review_required"))
        task_id = initial_response["task_envelope"]["id"]

        resolution_status, resolution_response = self.service.reevaluate(
            task_id,
            {
                "request": {
                    "review_decision": _tampered_review_decision_payload(
                        task_id,
                        review_request_id="review-request-api-other",
                    )
                }
            },
        )

        self.assertEqual(initial_status, 200)
        self.assertEqual(resolution_status, 400)
        self.assertTrue(resolution_response["invalid_input"])
        self.assertIn("active review request", resolution_response["error"])

    def test_service_reevaluate_rejects_review_decision_with_modified_active_request_contract(self) -> None:
        initial_status, initial_response = self.service.evaluate(_request_payload("review_required"))
        task_id = initial_response["task_envelope"]["id"]

        resolution_status, resolution_response = self.service.reevaluate(
            task_id,
            {
                "request": {
                    "review_decision": _tampered_review_decision_payload(
                        task_id,
                        summary="A different review contract was presented to the operator.",
                    )
                }
            },
        )

        self.assertEqual(initial_status, 200)
        self.assertEqual(resolution_status, 400)
        self.assertTrue(resolution_response["invalid_input"])
        self.assertIn("match the active review request exactly", resolution_response["error"])

    def test_service_reevaluate_rejects_review_decision_backdated_before_request(self) -> None:
        initial_status, initial_response = self.service.evaluate(_request_payload("review_required"))
        task_id = initial_response["task_envelope"]["id"]
        backdated = _review_decision_payload(task_id)
        backdated["record"]["reviewed_at"] = "2026-03-24T19:59:59Z"

        resolution_status, resolution_response = self.service.reevaluate(
            task_id,
            {
                "request": {
                    "review_decision": backdated,
                }
            },
        )
        task_status, task_payload = self.service.get_task(task_id)

        self.assertEqual(initial_status, 200)
        self.assertEqual(resolution_status, 400)
        self.assertTrue(resolution_response["invalid_input"])
        self.assertIn("reviewed_at must not be earlier than requested_at", resolution_response["error"])
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["status"], "in_review")

    def test_health_reports_file_store_without_database_configuration(self) -> None:
        status, payload = self.service.health()

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["store_backend"], "file")
        self.assertFalse(payload["database_configured"])
        self.assertIsNone(payload["database_host"])
        self.assertIsNone(payload["database_path"])
        self.assertIsNone(payload["database_schema_ready"])

    def test_health_reports_sqlite_schema_ready(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        store = SQLiteHarnessStore(Path(temp_dir.name) / "harness.db")
        service = HarnessApiService(store=store)

        status, payload = service.health()

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["store_backend"], "sqlite")
        self.assertTrue(payload["database_configured"])
        self.assertIsNone(payload["database_host"])
        self.assertEqual(payload["database_path"], str(store.database_path))
        self.assertTrue(payload["database_schema_ready"])

    def test_health_reports_postgres_schema_ready_without_exposing_credentials(self) -> None:
        store = PostgresHarnessStore("postgresql://worker:super-secret@db.internal.example:5432/harness")
        service = HarnessApiService(store=store)

        with patch.object(store, "_connect", return_value=_FakeConnection([(True,), (True,)])):
            status, payload = service.health()

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["store_backend"], "postgres")
        self.assertTrue(payload["database_configured"])
        self.assertEqual(payload["database_host"], "db.internal.example")
        self.assertIsNone(payload["database_path"])
        self.assertTrue(payload["database_schema_ready"])
        self.assertNotIn("super-secret", json.dumps(payload))
        self.assertNotIn("worker", json.dumps(payload))

    def test_health_reports_postgres_schema_not_ready_when_expected_tables_are_missing(self) -> None:
        store = PostgresHarnessStore("postgresql://db.internal.example/harness")
        service = HarnessApiService(store=store)

        with patch.object(store, "_connect", return_value=_FakeConnection([(True,), (False,)])):
            status, payload = service.health()

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "degraded")
        self.assertEqual(payload["store_backend"], "postgres")
        self.assertTrue(payload["database_configured"])
        self.assertEqual(payload["database_host"], "db.internal.example")
        self.assertIsNone(payload["database_path"])
        self.assertFalse(payload["database_schema_ready"])

    def test_health_reports_postgres_schema_not_ready_when_database_is_unreachable(self) -> None:
        store = PostgresHarnessStore("postgresql://db.internal.example/harness")
        service = HarnessApiService(store=store)

        with patch.object(store, "_connect", side_effect=RuntimeError("connection refused")):
            status, payload = service.health()

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "degraded")
        self.assertEqual(payload["store_backend"], "postgres")
        self.assertTrue(payload["database_configured"])
        self.assertEqual(payload["database_host"], "db.internal.example")
        self.assertIsNone(payload["database_path"])
        self.assertFalse(payload["database_schema_ready"])

    def test_service_retries_retryable_transient_failure_with_bounded_budget(self) -> None:
        payload = _request_payload("accepted_completion")
        payload["request"]["runtime_facts"] = {
            "executor_reported_success": True,
            "executor_reported_failure": True,
            "terminal_failure": True,
            "attempt_count": 1,
            "latest_attempt_outcome": "failed",
        }

        with patch.dict(os.environ, {"HARNESS_CLASSIFIED_RETRY_BUDGET": "2"}):
            status, response = self.service.evaluate(payload)
        history_status, history = self.service.get_evaluation_history(response["task_envelope"]["id"])

        self.assertEqual(status, 200)
        self.assertEqual(response["failure_classification"]["category"], "executor_failure")
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history["evaluations"]), 3)
        retry_requests = [item["request"].get("retry_context") for item in history["evaluations"]]
        self.assertIsNone(retry_requests[0])
        self.assertEqual(retry_requests[1]["triggered_by_category"], "executor_failure")
        self.assertFalse(retry_requests[1]["is_final_attempt"])
        self.assertEqual(retry_requests[2]["triggered_by_category"], "executor_failure")
        self.assertTrue(retry_requests[2]["is_final_attempt"])

    def test_service_does_not_retry_non_retryable_contract_violation(self) -> None:
        payload = _request_payload("accepted_completion")
        payload["request"]["unresolved_conditions"] = ["Execution checkpoint is missing."]

        with patch.dict(os.environ, {"HARNESS_CLASSIFIED_RETRY_BUDGET": "2"}):
            status, response = self.service.evaluate(payload)
        history_status, history = self.service.get_evaluation_history(response["task_envelope"]["id"])

        self.assertEqual(status, 200)
        self.assertEqual(response["failure_classification"]["category"], "contract_violation")
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history["evaluations"]), 1)

    def test_service_retries_retryable_evidence_insufficient_with_bounded_budget(self) -> None:
        payload = _request_payload("blocked_insufficient_evidence")
        payload["request"]["runtime_facts"] = {
            "executor_reported_failure": True,
            "attempt_count": 1,
            "latest_attempt_outcome": "failed",
        }

        with patch.dict(os.environ, {"HARNESS_CLASSIFIED_RETRY_BUDGET": "2"}):
            status, response = self.service.evaluate(payload)
        history_status, history = self.service.get_evaluation_history(response["task_envelope"]["id"])

        self.assertEqual(status, 200)
        self.assertEqual(response["failure_classification"]["category"], "evidence_insufficient")
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history["evaluations"]), 3)
        retry_requests = [item["request"].get("retry_context") for item in history["evaluations"]]
        self.assertIsNone(retry_requests[0])
        self.assertEqual(retry_requests[1]["triggered_by_category"], "evidence_insufficient")
        self.assertEqual(retry_requests[2]["triggered_by_category"], "evidence_insufficient")

    def test_service_does_not_retry_non_retryable_reconciliation_mismatch(self) -> None:
        payload = _request_payload("blocked_reconciliation_mismatch")

        with patch.dict(os.environ, {"HARNESS_CLASSIFIED_RETRY_BUDGET": "2"}):
            status, response = self.service.evaluate(payload)
        history_status, history = self.service.get_evaluation_history(response["task_envelope"]["id"])

        self.assertEqual(status, 200)
        self.assertEqual(response["failure_classification"]["category"], "reconciliation_mismatch")
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history["evaluations"]), 1)


class HarnessHttpApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.server = run_server(host="127.0.0.1", port=0, store_root=self.temp_dir.name)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp_dir.cleanup()

    def _get_json(self, path: str) -> tuple[int, dict]:
        try:
            with urlopen(self.base_url + path) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            try:
                return error.code, json.loads(error.read().decode("utf-8"))
            finally:
                error.close()

    def _post_json(self, path: str, payload: dict) -> tuple[int, dict]:
        request = Request(
            self.base_url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            try:
                return error.code, json.loads(error.read().decode("utf-8"))
            finally:
                error.close()

    def test_health_endpoint(self) -> None:
        status, payload = self._get_json("/health")

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["store_backend"], "file")
        self.assertFalse(payload["database_configured"])
        self.assertIsNone(payload["database_host"])
        self.assertIsNone(payload["database_path"])
        self.assertIsNone(payload["database_schema_ready"])

    def test_api_submit_accepts_new_task_and_persists_initial_result(self) -> None:
        status, payload = self._post_json(
            "/tasks",
            {"request": {"task_envelope": deepcopy(_manual_happy_path_overlay_payload()["request"]["task_envelope"])}},
        )
        task_id = payload["task_envelope"]["id"]

        task_status, task_payload = self._get_json(f"/tasks/{task_id}")
        history_status, history_payload = self._get_json(f"/tasks/{task_id}/evaluations")

        self.assertEqual(status, 200)
        self.assertEqual(payload["task_envelope"]["status"], "intake_ready")
        self.assertIn("evaluation_record", payload)
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["status"], "intake_ready")
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 1)

    def test_api_lists_dashboard_tasks(self) -> None:
        self._post_json(
            "/tasks",
            {"request": {"task_envelope": deepcopy(_manual_happy_path_overlay_payload()["request"]["task_envelope"])}},
        )
        blocked_task = create_task_envelope(
            {
                "id": "task-api-list-blocked-1",
                "title": "Blocked by clarification",
                "description": "Task should remain blocked until clarification arrives.",
                "origin": {
                    "source_system": "manual",
                    "source_type": "manual",
                    "source_id": "task-api-list-blocked-1",
                },
                "acceptance_criteria": [{"id": "ac-1", "description": "Clarification resolves.", "required": True}],
            },
            now="2026-04-07T00:00:00Z",
        )
        self._post_json(
            "/tasks",
            {
                "request": {
                    "task_envelope": blocked_task,
                    "task_status": "dispatch_ready",
                    "unresolved_conditions": ["Need repository clarification before execution can begin."],
                }
            },
        )

        status, payload = self._get_json("/tasks")

        self.assertEqual(status, 200)
        self.assertEqual(len(payload["tasks"]), 2)
        self.assertIn("task_id", payload["tasks"][0])
        self.assertIn("review_summary", payload["tasks"][0])

    def test_api_submit_can_persist_initial_blocked_result(self) -> None:
        blocked_task = create_task_envelope(
            {
                "id": "task-api-blocked-1",
                "title": "Blocked by clarification",
                "description": "Task should block on clarification.",
                "origin": {
                    "source_system": "manual",
                    "source_type": "manual",
                    "source_id": "task-api-blocked-1",
                },
                "acceptance_criteria": [{"id": "ac-1", "description": "Clarification resolves.", "required": True}],
            },
            now="2026-04-07T00:00:00Z",
        )
        status, payload = self._post_json(
            "/tasks",
            {
                "request": {
                    "task_envelope": blocked_task,
                    "task_status": "dispatch_ready",
                    "unresolved_conditions": ["Need repository clarification before execution can begin."],
                }
            },
        )
        task_id = payload["task_envelope"]["id"]

        task_status, task_payload = self._get_json(f"/tasks/{task_id}")

        self.assertEqual(status, 200)
        self.assertEqual(payload["task_envelope"]["status"], "blocked")
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["status"], "blocked")

    def test_api_submit_rejects_completion_shaped_new_task(self) -> None:
        payload = _request_payload("accepted_completion")
        task_id = payload["request"]["task_envelope"]["id"]

        status, response = self._post_json("/tasks", payload)
        task_status, task_payload = self._get_json(f"/tasks/{task_id}")

        self.assertEqual(status, 400)
        self.assertTrue(response["invalid_input"])
        self.assertIn("cannot claim completion", response["error"].lower())
        self.assertTrue(response["submission_contract_violations"])
        self.assertEqual(task_status, 404)
        self.assertIn("not found", task_payload["error"].lower())

    def test_api_submit_rejects_invalid_input_without_persisting_state(self) -> None:
        invalid_payload = _request_payload("invalid_input")
        task_id = invalid_payload["request"]["task_envelope"]["id"]

        status, payload = self._post_json("/tasks", invalid_payload)
        task_status, task_payload = self._get_json(f"/tasks/{task_id}")

        self.assertEqual(status, 400)
        self.assertTrue(payload["invalid_input"])
        self.assertEqual(task_status, 404)

    def test_api_completion_claim_ignores_support_artifact_context_for_execution_validation(self) -> None:
        payload = _manual_happy_path_overlay_payload()
        submit_status, submit_payload = self._post_json(
            "/tasks",
            {"request": {"task_envelope": deepcopy(payload["request"]["task_envelope"])}},
        )
        task_id = submit_payload["task_envelope"]["id"]
        store = FileBackedHarnessStore(self.temp_dir.name)
        task = deepcopy(store.get_task(task_id))
        task["status"] = "assigned"
        task["assigned_executor"] = {
            "executor_type": "codex",
            "executor_id": "executor-invalid-support-context-api-1",
            "assignment_reason": "Exercise support artifact context rejection.",
        }
        task["timestamps"]["updated_at"] = "2026-04-01T10:03:00Z"
        store.update_task(task)

        support_artifact = _review_note_artifact("artifact-support-context-note-api-1")
        support_artifact["repository"] = {
            "host": "github.com",
            "owner": "KnoxAnalytics",
            "name": "HARNESS-DRYRUN",
        }
        support_artifact["branch"] = {
            "name": "codex/e2e-test",
            "base_branch": "main",
            "head_commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
        }
        support_artifact["commit_sha"] = "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705"

        with patch.dict(os.environ, {"HARNESS_INVALID_EXECUTION_RETRY_BUDGET": "1"}):
            claim_status, claim_response = self._post_json(
                f"/tasks/{task_id}/completion-claims",
                {
                    "request": {
                        **_completion_claim_payload(claim_id="claim-invalid-support-context-api-1"),
                        **_execution_attempt_payload(attempt_id="attempt-invalid-support-context-api-1"),
                        "new_artifacts": [support_artifact],
                        "runtime_facts": {"executor_reported_success": True, "attempt_count": 1},
                    }
                },
            )

        self.assertEqual(submit_status, 200)
        self.assertEqual(claim_status, 200)
        self.assertEqual(claim_response["action"], "contract_violation_failed")
        self.assertEqual(
            claim_response["contract_violation"]["validation"]["rule_failures"][0]["rule"],
            "missing_branch_identity",
        )

    def test_api_completion_claim_ignores_support_artifact_references_for_execution_validation(self) -> None:
        payload = _manual_happy_path_overlay_payload()
        submit_status, submit_payload = self._post_json(
            "/tasks",
            {"request": {"task_envelope": deepcopy(payload["request"]["task_envelope"])}},
        )
        task_id = submit_payload["task_envelope"]["id"]
        store = FileBackedHarnessStore(self.temp_dir.name)
        task = deepcopy(store.get_task(task_id))
        task["status"] = "assigned"
        task["assigned_executor"] = {
            "executor_type": "codex",
            "executor_id": "executor-invalid-support-reference-api-1",
            "assignment_reason": "Exercise support artifact reference rejection.",
        }
        task["timestamps"]["updated_at"] = "2026-04-01T10:03:00Z"
        store.update_task(task)

        invalid_attempt_payload = _execution_attempt_payload(attempt_id="attempt-invalid-support-reference-api-1")
        invalid_attempt_payload["execution_attempt"]["artifact_references"] = [
            {
                "reference_id": "attempt-invalid-support-reference-api-1:review-note",
                "artifact_type": "review_note",
                "location": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/tree/codex/e2e-test",
                "metadata": {
                    "repository_host": "github.com",
                    "repository_owner": "KnoxAnalytics",
                    "repository_name": "HARNESS-DRYRUN",
                    "branch_name": "codex/e2e-test",
                    "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                },
            }
        ]

        with patch.dict(os.environ, {"HARNESS_INVALID_EXECUTION_RETRY_BUDGET": "1"}):
            claim_status, claim_response = self._post_json(
                f"/tasks/{task_id}/completion-claims",
                {
                    "request": {
                        **_completion_claim_payload(claim_id="claim-invalid-support-reference-api-1"),
                        **invalid_attempt_payload,
                        "runtime_facts": {"executor_reported_success": True, "attempt_count": 1},
                    }
                },
            )

        self.assertEqual(submit_status, 200)
        self.assertEqual(claim_status, 200)
        self.assertEqual(claim_response["action"], "contract_violation_failed")
        self.assertEqual(
            claim_response["contract_violation"]["validation"]["rule_failures"][0]["rule"],
            "missing_branch_identity",
        )

    def test_api_submit_rejects_new_task_with_execution_history(self) -> None:
        payload = {"request": {"task_envelope": deepcopy(_manual_happy_path_overlay_payload()["request"]["task_envelope"])}}
        task_id = payload["request"]["task_envelope"]["id"]
        payload["request"]["task_envelope"]["observability"]["execution_metadata"]["execution_attempts"] = [
            {"attempt_id": "attempt-1", "status": "completed"}
        ]

        status, response = self._post_json("/tasks", payload)
        task_status, task_payload = self._get_json(f"/tasks/{task_id}")

        self.assertEqual(status, 400)
        self.assertTrue(response["invalid_input"])
        self.assertEqual(
            response["submission_contract_violations"][0]["rule"],
            "initial_execution_attempt_history_not_allowed",
        )
        self.assertEqual(task_status, 404)
        self.assertIn("not found", task_payload["error"].lower())

    def test_api_submit_rejects_assigned_status_on_new_task(self) -> None:
        payload = {"request": {"task_envelope": deepcopy(_manual_happy_path_overlay_payload()["request"]["task_envelope"])}}
        task_id = payload["request"]["task_envelope"]["id"]
        payload["request"]["task_status"] = "assigned"

        status, response = self._post_json("/tasks", payload)
        task_status, task_payload = self._get_json(f"/tasks/{task_id}")

        self.assertEqual(status, 400)
        self.assertTrue(response["invalid_input"])
        self.assertTrue(
            any(
                violation["rule"] == "initial_task_status_invalid"
                for violation in response["submission_contract_violations"]
            )
        )
        self.assertEqual(task_status, 404)
        self.assertIn("not found", task_payload["error"].lower())

    def test_api_submit_rejects_assigned_executor_on_new_task(self) -> None:
        payload = {"request": {"task_envelope": deepcopy(_manual_happy_path_overlay_payload()["request"]["task_envelope"])}}
        task_id = payload["request"]["task_envelope"]["id"]
        payload["request"]["assigned_executor"] = {
            "executor_type": "codex",
            "executor_id": "executor-api-submit-1",
            "assignment_reason": "Fresh HTTP submit should not assign executors.",
        }

        status, response = self._post_json("/tasks", payload)
        task_status, task_payload = self._get_json(f"/tasks/{task_id}")

        self.assertEqual(status, 400)
        self.assertTrue(response["invalid_input"])
        self.assertTrue(
            any(
                violation["rule"] == "initial_assigned_executor_not_allowed"
                for violation in response["submission_contract_violations"]
            )
        )
        self.assertEqual(task_status, 404)
        self.assertIn("not found", task_payload["error"].lower())

    def test_api_submit_rejects_missing_task_id_with_structured_400(self) -> None:
        status, payload = self._post_json("/tasks", {"request": {"task_envelope": {"title": "Missing id"}}})

        self.assertEqual(status, 400)
        self.assertTrue(payload["invalid_input"])
        self.assertIn("task_envelope.id is required", payload["error"])

    def test_api_submit_rejects_schema_invalid_task_envelope_with_structured_400(self) -> None:
        status, payload = self._post_json("/tasks", _schema_invalid_submission_payload())

        self.assertEqual(status, 400)
        self.assertTrue(payload["invalid_input"])
        self.assertIn("Invalid TaskEnvelope:", payload["error"])

    def test_api_submit_rejects_duplicate_task_id_with_conflict(self) -> None:
        submit_payload = {
            "request": {
                "task_envelope": deepcopy(_manual_happy_path_overlay_payload()["request"]["task_envelope"]),
            }
        }
        initial_status, initial_payload = self._post_json("/tasks", submit_payload)
        duplicate_status, duplicate_payload = self._post_json("/tasks", submit_payload)
        history_status, history_payload = self._get_json(
            f"/tasks/{initial_payload['task_envelope']['id']}/evaluations"
        )

        self.assertEqual(initial_status, 200)
        self.assertEqual(duplicate_status, 409)
        self.assertTrue(duplicate_payload["duplicate_task_id"])
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 1)

    def test_api_linear_ingress_can_submit_accepted_task(self) -> None:
        status, payload = self._post_json("/ingress/linear", _linear_ingress_payload("accepted_completion"))
        task_id = payload["task_envelope"]["id"]

        task_status, task_payload = self._get_json(f"/tasks/{task_id}")
        history_status, history_payload = self._get_json(f"/tasks/{task_id}/evaluations")

        self.assertEqual(status, 200)
        self.assertEqual(payload["task_envelope"]["origin"]["source_system"], "linear")
        self.assertEqual(payload["task_envelope"]["status"], "intake_ready")
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["extensions"]["linear"]["issue_id"], f"lin-{task_id}")
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 1)

    def test_api_linear_ingress_can_submit_initial_blocked_task(self) -> None:
        status, payload = self._post_json("/ingress/linear", _linear_ingress_payload("blocked_insufficient_evidence"))
        task_id = payload["task_envelope"]["id"]

        task_status, task_payload = self._get_json(f"/tasks/{task_id}")

        self.assertEqual(status, 200)
        self.assertEqual(payload["task_envelope"]["status"], "blocked")
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["status"], "blocked")

    def test_api_linear_ingress_rejects_completion_shaped_handoff(self) -> None:
        payload = _linear_ingress_payload("accepted_completion", task_id="task-linear-invalid-completion-1")
        payload["claimed_completion"] = True

        status, response_payload = self._post_json("/ingress/linear", payload)
        task_status, task_payload = self._get_json("/tasks/task-linear-invalid-completion-1")

        self.assertEqual(status, 400)
        self.assertTrue(response_payload["invalid_input"])
        self.assertIn("cannot claim completion", response_payload["error"].lower())
        self.assertEqual(task_status, 404)
        self.assertIn("not found", task_payload["error"].lower())

    def test_api_linear_ingress_rejects_runtime_facts_and_execution_artifacts(self) -> None:
        payload = _linear_ingress_payload("accepted_completion", task_id="task-linear-invalid-runtime-1")
        payload["runtime_facts"] = {"attempt_count": 1}

        status, response_payload = self._post_json("/ingress/linear", payload)
        task_status, task_payload = self._get_json("/tasks/task-linear-invalid-runtime-1")

        self.assertEqual(status, 400)
        self.assertTrue(response_payload["invalid_input"])
        self.assertIn("cannot submit runtime_facts", response_payload["error"].lower())
        self.assertEqual(task_status, 404)
        self.assertIn("not found", task_payload["error"].lower())

        payload = _linear_ingress_payload("accepted_completion", task_id="task-linear-invalid-artifact-1")
        payload["linked_artifacts"] = [{"id": "artifact-pr-1", "type": "pull_request"}]

        status, response_payload = self._post_json("/ingress/linear", payload)
        task_status, task_payload = self._get_json("/tasks/task-linear-invalid-artifact-1")

        self.assertEqual(status, 400)
        self.assertTrue(response_payload["invalid_input"])
        self.assertIn("cannot attach repository execution artifacts", response_payload["error"].lower())
        self.assertEqual(task_status, 404)
        self.assertIn("not found", task_payload["error"].lower())

    def test_api_linear_ingress_rejects_assignment_truth(self) -> None:
        payload = _linear_ingress_payload("accepted_completion", task_id="task-linear-invalid-assigned-1")
        payload["task_status"] = "assigned"

        status, response_payload = self._post_json("/ingress/linear", payload)
        task_status, task_payload = self._get_json("/tasks/task-linear-invalid-assigned-1")

        self.assertEqual(status, 400)
        self.assertTrue(response_payload["invalid_input"])
        self.assertIn("task_status must be one of", response_payload["error"].lower())
        self.assertEqual(task_status, 404)
        self.assertIn("not found", task_payload["error"].lower())

        payload = _linear_ingress_payload("accepted_completion", task_id="task-linear-invalid-assignee-1")
        payload["assigned_executor"] = {
            "executor_type": "codex",
            "executor_id": "executor-linear-1",
            "assignment_reason": "Ingress should not assign executors.",
        }

        status, response_payload = self._post_json("/ingress/linear", payload)
        task_status, task_payload = self._get_json("/tasks/task-linear-invalid-assignee-1")

        self.assertEqual(status, 400)
        self.assertTrue(response_payload["invalid_input"])
        self.assertIn("cannot pre-assign an executor", response_payload["error"].lower())
        self.assertEqual(task_status, 404)
        self.assertIn("not found", task_payload["error"].lower())

    def test_api_linear_ingress_rejects_invalid_payload_without_persisting_state(self) -> None:
        payload = _linear_ingress_payload("accepted_completion", task_id="task-linear-invalid-1")
        del payload["issue"]["title"]

        status, response_payload = self._post_json("/ingress/linear", payload)
        task_status, task_payload = self._get_json("/tasks/task-linear-invalid-1")

        self.assertEqual(status, 400)
        self.assertTrue(response_payload["invalid_input"])
        self.assertEqual(task_status, 404)
        self.assertIn("not found", task_payload["error"].lower())

    def test_api_linear_ingress_rejects_duplicate_task_id_consistently(self) -> None:
        payload = _linear_ingress_payload("accepted_completion", task_id="task-linear-duplicate-1")

        initial_status, _ = self._post_json("/ingress/linear", payload)
        duplicate_status, duplicate_payload = self._post_json("/ingress/linear", payload)
        history_status, history_payload = self._get_json("/tasks/task-linear-duplicate-1/evaluations")

        self.assertEqual(initial_status, 200)
        self.assertEqual(duplicate_status, 409)
        self.assertTrue(duplicate_payload["duplicate_task_id"])
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 1)

    def test_api_persists_accepted_completion_and_exposes_history(self) -> None:
        status, payload = self._post_json("/evaluate", _request_payload("accepted_completion"))
        task_id = payload["task_envelope"]["id"]

        task_status, task_payload = self._get_json(f"/tasks/{task_id}")
        history_status, history_payload = self._get_json(f"/tasks/{task_id}/evaluations")

        self.assertEqual(status, 200)
        self.assertEqual(payload["action"], "transition_applied")
        self.assertEqual(payload["task_envelope"]["status"], "completed")
        self.assertIn("evaluation_record", payload)
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["status"], "completed")
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 1)
        self.assertEqual(history_payload["evaluations"][0]["result"]["task_envelope"]["status"], "completed")


    def test_api_accepts_manual_ingress_submission_endpoint(self) -> None:
        status, payload = self._post_json("/ingress/manual", _manual_ingress_payload())

        self.assertEqual(status, 200)
        self.assertIn("task_envelope", payload)
        self.assertEqual(payload["task_envelope"]["origin"]["source_system"], "manual")
        self.assertTrue(payload["task_envelope"]["id"])

    def test_api_manual_ingress_rejects_completion_shaped_handoff(self) -> None:
        payload = _manual_ingress_payload(task_id="task-manual-invalid-completion-1")
        payload["acceptance_criteria_satisfied"] = True

        status, response_payload = self._post_json("/ingress/manual", payload)
        task_status, task_payload = self._get_json("/tasks/task-manual-invalid-completion-1")

        self.assertEqual(status, 400)
        self.assertTrue(response_payload["invalid_input"])
        self.assertIn("cannot assert acceptance_criteria_satisfied", response_payload["error"].lower())
        self.assertEqual(task_status, 404)
        self.assertIn("not found", task_payload["error"].lower())

    def test_api_manual_ingress_rejects_runtime_facts_and_execution_artifacts(self) -> None:
        payload = _manual_ingress_payload(task_id="task-manual-invalid-runtime-1")
        payload["runtime_facts"] = {"attempt_count": 1}

        status, response_payload = self._post_json("/ingress/manual", payload)
        task_status, task_payload = self._get_json("/tasks/task-manual-invalid-runtime-1")

        self.assertEqual(status, 400)
        self.assertTrue(response_payload["invalid_input"])
        self.assertIn("cannot submit runtime_facts", response_payload["error"].lower())
        self.assertEqual(task_status, 404)
        self.assertIn("not found", task_payload["error"].lower())

        payload = _manual_ingress_payload(task_id="task-manual-invalid-artifact-1")
        payload["linked_artifacts"] = [{"id": "artifact-pr-1", "type": "pull_request"}]

        status, response_payload = self._post_json("/ingress/manual", payload)
        task_status, task_payload = self._get_json("/tasks/task-manual-invalid-artifact-1")

        self.assertEqual(status, 400)
        self.assertTrue(response_payload["invalid_input"])
        self.assertIn("cannot attach repository execution artifacts", response_payload["error"].lower())
        self.assertEqual(task_status, 404)
        self.assertIn("not found", task_payload["error"].lower())

    def test_api_manual_ingress_rejects_assignment_truth(self) -> None:
        payload = _manual_ingress_payload(task_id="task-manual-invalid-assigned-1")
        payload["task_status"] = "assigned"

        status, response_payload = self._post_json("/ingress/manual", payload)
        task_status, task_payload = self._get_json("/tasks/task-manual-invalid-assigned-1")

        self.assertEqual(status, 400)
        self.assertTrue(response_payload["invalid_input"])
        self.assertIn("task_status must be one of", response_payload["error"].lower())
        self.assertEqual(task_status, 404)
        self.assertIn("not found", task_payload["error"].lower())

        payload = _manual_ingress_payload(task_id="task-manual-invalid-assignee-1")
        payload["assigned_executor"] = {
            "executor_type": "codex",
            "executor_id": "executor-manual-1",
            "assignment_reason": "Ingress should not assign executors.",
        }

        status, response_payload = self._post_json("/ingress/manual", payload)
        task_status, task_payload = self._get_json("/tasks/task-manual-invalid-assignee-1")

        self.assertEqual(status, 400)
        self.assertTrue(response_payload["invalid_input"])
        self.assertIn("cannot pre-assign an executor", response_payload["error"].lower())
        self.assertEqual(task_status, 404)
        self.assertIn("not found", task_payload["error"].lower())

    def test_api_accepts_openclaw_ingress_submission_endpoint(self) -> None:
        status, payload = self._post_json("/ingress/openclaw", _openclaw_ingress_payload())
        task_id = payload["task_envelope"]["id"]

        read_status, read_payload = self._get_json(f"/tasks/{task_id}/read-model")
        self.assertEqual(status, 200)
        self.assertEqual(payload["task_envelope"]["origin"]["source_system"], "openclaw")
        self.assertEqual(payload["task_envelope"]["origin"]["ingress_name"], "OpenClaw")
        self.assertEqual(read_status, 200)
        self.assertEqual(read_payload["task"]["extensions"]["openclaw"]["metadata"]["request_kind"], "openclaw")

    def test_api_github_sync_delegates_to_canonical_reevaluation(self) -> None:
        submit_status, submit_payload = self._post_json("/ingress/manual", _manual_ingress_payload())
        task_id = submit_payload["task_envelope"]["id"]

        status, payload = self._post_json("/sync/github", _github_sync_payload(task_id=task_id))
        task_status, task_payload = self._get_json(f"/tasks/{task_id}")
        history_status, history_payload = self._get_json(f"/tasks/{task_id}/evaluations")

        self.assertEqual(submit_status, 200)
        self.assertEqual(status, 200)
        self.assertEqual(task_status, 200)
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 2)
        artifacts = payload["task_envelope"]["artifacts"]["items"]
        self.assertEqual([artifact["type"] for artifact in artifacts], ["branch", "commit", "pull_request", "changed_file"])
        self.assertTrue(all(artifact["verification_status"] == "verified" for artifact in artifacts))
        self.assertEqual(
            task_payload["task"]["artifacts"]["items"][3]["changed_files"][0]["path"],
            "modules/api.py",
        )
        self.assertEqual(
            history_payload["evaluations"][1]["request"]["external_facts"]["github_facts"]["pull_request"]["number"],
            2,
        )

    def test_api_github_sync_rejects_runtime_facts_without_mutating_task(self) -> None:
        submit_status, submit_payload = self._post_json("/ingress/manual", _manual_ingress_payload())
        task_id = submit_payload["task_envelope"]["id"]
        payload = _github_sync_payload(task_id=task_id)
        payload["runtime_facts"] = {"executor_reported_success": True}

        status, response_payload = self._post_json("/sync/github", payload)
        task_status, task_payload = self._get_json(f"/tasks/{task_id}")
        history_status, history_payload = self._get_json(f"/tasks/{task_id}/evaluations")

        self.assertEqual(submit_status, 200)
        self.assertEqual(status, 400)
        self.assertTrue(response_payload["invalid_input"])
        self.assertIn("cannot submit runtime_facts", response_payload["error"].lower())
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["artifacts"]["items"], [])
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 1)

    def test_api_github_sync_resumes_completion_with_required_policy_when_prior_attempt_is_valid(self) -> None:
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_no_create_pull_request_gateway(),
        )
        payload = _manual_happy_path_overlay_payload()
        task_envelope = deepcopy(payload["request"]["task_envelope"])
        task_envelope["id"] = "task-api-github-sync-resume-1"
        task_envelope["title"] = "GitHub sync completion resume"
        task_envelope["description"] = "GitHub sync should resume a prior valid completion attempt."
        task_envelope["artifacts"]["items"] = []
        task_envelope["artifacts"]["completion_evidence"] = {
            "policy": "deferred",
            "status": "deferred",
            "required_artifact_types": ["pull_request", "commit"],
            "validated_artifact_ids": [],
            "validation_method": "deferred",
            "validated_at": None,
            "validator": None,
            "notes": None,
        }
        submit_status, submit_response = service.submit({"request": {"task_envelope": task_envelope}})
        task_id = submit_response["task_envelope"]["id"]

        stored_task = deepcopy(service.store.get_task(task_id))
        stored_task["status"] = "blocked"
        stored_task["assigned_executor"] = {
            "executor_type": "codex",
            "executor_id": "executor-api-github-sync-resume-1",
            "assignment_reason": "Exercise GitHub sync completion resume.",
        }
        execution_metadata = stored_task["observability"]["execution_metadata"]
        execution_metadata["advisory_completion_claims"] = [
            {
                "claim_id": "claim-api-github-sync-resume-1",
                "reported_at": "2026-04-13T10:00:00Z",
                "reported_by": "codex",
                "reason": "Executor reported completion pending GitHub reconciliation.",
                "metadata": {"attempt_id": "attempt-api-github-sync-resume-1"},
            }
        ]
        execution_metadata["execution_attempts"] = [
            {
                "attempt_id": "attempt-api-github-sync-resume-1",
                "recorded_at": "2026-04-13T10:00:05Z",
                "status": "succeeded",
                "reported_by": "codex",
                "completion_claim_id": "claim-api-github-sync-resume-1",
                "artifact_references": [
                    {
                        "reference_id": "attempt-api-github-sync-resume-1:pr",
                        "artifact_type": "pull_request",
                        "location": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/pull/2",
                        "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                        "metadata": {
                            "repository_host": "github.com",
                            "repository_owner": "KnoxAnalytics",
                            "repository_name": "HARNESS-DRYRUN",
                            "branch_name": "codex/e2e-test",
                            "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                            "pull_request_number": 2,
                            "state": "open",
                        },
                    },
                    {
                        "reference_id": "attempt-api-github-sync-resume-1:commit",
                        "artifact_type": "commit",
                        "location": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/commit/8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                        "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                        "metadata": {
                            "repository_host": "github.com",
                            "repository_owner": "KnoxAnalytics",
                            "repository_name": "HARNESS-DRYRUN",
                            "branch_name": "codex/e2e-test",
                            "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                        },
                    },
                ],
                "metadata": {
                    "executor_run_id": "stub-run-sync-1",
                    "attempt_validation": {
                        "status": "valid",
                        "validated_at": "2026-04-13T10:00:06Z",
                    },
                },
            }
        ]
        service.store.update_task(stored_task)
        self.assertEqual(submit_status, 200)
        reevaluate_status, _ = service.reevaluate(
            task_id,
            {"request": {"acceptance_criteria_satisfied": True}},
        )
        self.assertEqual(reevaluate_status, 200)

        service.reconciliation_registry = _registry_with_current_run_pull_request_gateway()
        sync_status, sync_response = service.submit_github_sync(_github_sync_payload(task_id=task_id))

        self.assertEqual(sync_status, 200)
        self.assertEqual(sync_response["action"], "transition_applied")
        self.assertTrue(sync_response["accepted_completion"])
        self.assertEqual(sync_response["task_envelope"]["status"], "completed")
        evidence = sync_response["task_envelope"]["artifacts"]["completion_evidence"]
        self.assertEqual(evidence["policy"], "required")
        self.assertEqual(evidence["status"], "satisfied")
        self.assertEqual(evidence["validation_method"], "external_reconciliation")

    def test_api_github_sync_infers_code_execution_evidence_requirements_when_missing(self) -> None:
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_no_create_pull_request_gateway(),
        )
        payload = _manual_happy_path_overlay_payload()
        task_envelope = deepcopy(payload["request"]["task_envelope"])
        task_envelope["id"] = "task-api-github-sync-infer-evidence-1"
        task_envelope["title"] = "GitHub sync infers missing code proof requirements"
        task_envelope["description"] = "GitHub sync should infer minimal PR and commit proof when ingress left evidence deferred."
        task_envelope["artifacts"]["items"] = []
        task_envelope["artifacts"]["completion_evidence"] = {
            "policy": "deferred",
            "status": "deferred",
            "required_artifact_types": [],
            "validated_artifact_ids": [],
            "validation_method": "deferred",
            "validated_at": None,
            "validator": None,
            "notes": None,
        }
        submit_status, submit_response = service.submit({"request": {"task_envelope": task_envelope}})
        task_id = submit_response["task_envelope"]["id"]

        stored_task = deepcopy(service.store.get_task(task_id))
        stored_task["status"] = "blocked"
        stored_task["assigned_executor"] = {
            "executor_type": "codex",
            "executor_id": "executor-api-github-sync-infer-evidence-1",
            "assignment_reason": "Exercise GitHub sync evidence inference for code execution proof.",
        }
        execution_metadata = stored_task["observability"]["execution_metadata"]
        execution_metadata["advisory_completion_claims"] = [
            {
                "claim_id": "claim-api-github-sync-infer-evidence-1",
                "reported_at": "2026-04-17T01:44:30Z",
                "reported_by": "codex",
                "reason": "Executor reported completion pending GitHub reconciliation.",
                "metadata": {"attempt_id": "attempt-api-github-sync-infer-evidence-1"},
            }
        ]
        execution_metadata["execution_attempts"] = [
            {
                "attempt_id": "attempt-api-github-sync-infer-evidence-1",
                "recorded_at": "2026-04-17T01:44:31Z",
                "status": "succeeded",
                "reported_by": "codex",
                "completion_claim_id": "claim-api-github-sync-infer-evidence-1",
                "artifact_references": [
                    {
                        "reference_id": "attempt-api-github-sync-infer-evidence-1:pr",
                        "artifact_type": "pull_request",
                        "location": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/pull/2",
                        "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                        "metadata": {
                            "repository_host": "github.com",
                            "repository_owner": "KnoxAnalytics",
                            "repository_name": "HARNESS-DRYRUN",
                            "branch_name": "codex/e2e-test",
                            "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                            "pull_request_number": 2,
                            "state": "open",
                        },
                    },
                    {
                        "reference_id": "attempt-api-github-sync-infer-evidence-1:commit",
                        "artifact_type": "commit",
                        "location": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/commit/8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                        "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                        "metadata": {
                            "repository_host": "github.com",
                            "repository_owner": "KnoxAnalytics",
                            "repository_name": "HARNESS-DRYRUN",
                            "branch_name": "codex/e2e-test",
                            "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                        },
                    },
                ],
                "metadata": {
                    "executor_run_id": "stub-run-sync-infer-evidence-1",
                    "attempt_validation": {
                        "status": "valid",
                        "validated_at": "2026-04-17T01:44:32Z",
                    },
                },
            }
        ]
        service.store.update_task(stored_task)
        self.assertEqual(submit_status, 200)
        reevaluate_status, _ = service.reevaluate(
            task_id,
            {"request": {"acceptance_criteria_satisfied": True}},
        )
        self.assertEqual(reevaluate_status, 200)

        service.reconciliation_registry = _registry_with_current_run_pull_request_gateway()
        sync_status, sync_response = service.submit_github_sync(_github_sync_payload(task_id=task_id))

        self.assertEqual(sync_status, 200)
        self.assertEqual(sync_response["action"], "transition_applied")
        self.assertTrue(sync_response["accepted_completion"])
        self.assertEqual(sync_response["task_envelope"]["status"], "completed")
        evidence = sync_response["task_envelope"]["artifacts"]["completion_evidence"]
        self.assertEqual(evidence["policy"], "required")
        self.assertEqual(evidence["required_artifact_types"], ["pull_request", "commit"])
        self.assertEqual(evidence["status"], "satisfied")
        self.assertEqual(evidence["validation_method"], "external_reconciliation")

    def test_api_github_sync_infers_code_execution_evidence_without_assigned_executor(self) -> None:
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_no_create_pull_request_gateway(),
        )
        payload = _manual_happy_path_overlay_payload()
        task_envelope = deepcopy(payload["request"]["task_envelope"])
        task_envelope["id"] = "task-api-github-sync-infer-evidence-no-assignment-1"
        task_envelope["title"] = "GitHub sync infers code proof without assignment"
        task_envelope["description"] = (
            "A successful code-bearing execution attempt should be enough to infer proof requirements "
            "even when ingress did not set assigned_executor."
        )
        task_envelope["artifacts"]["items"] = []
        task_envelope["artifacts"]["completion_evidence"] = {
            "policy": "deferred",
            "status": "deferred",
            "required_artifact_types": [],
            "validated_artifact_ids": [],
            "validation_method": "deferred",
            "validated_at": None,
            "validator": None,
            "notes": None,
        }
        submit_status, submit_response = service.submit({"request": {"task_envelope": task_envelope}})
        task_id = submit_response["task_envelope"]["id"]

        stored_task = deepcopy(service.store.get_task(task_id))
        stored_task["status"] = "blocked"
        stored_task["assigned_executor"] = None
        execution_metadata = stored_task["observability"]["execution_metadata"]
        execution_metadata["advisory_completion_claims"] = [
            {
                "claim_id": "claim-api-github-sync-infer-evidence-no-assignment-1",
                "reported_at": "2026-04-17T12:10:34Z",
                "reported_by": "hermes",
                "reason": "Executor reported completion pending GitHub reconciliation.",
                "metadata": {"attempt_id": "attempt-api-github-sync-infer-evidence-no-assignment-1"},
            }
        ]
        execution_metadata["execution_attempts"] = [
            {
                "attempt_id": "attempt-api-github-sync-infer-evidence-no-assignment-1",
                "recorded_at": "2026-04-17T12:10:35Z",
                "status": "succeeded",
                "reported_by": "hermes",
                "completion_claim_id": "claim-api-github-sync-infer-evidence-no-assignment-1",
                "artifact_references": [
                    {
                        "reference_id": "attempt-api-github-sync-infer-evidence-no-assignment-1:pr",
                        "artifact_type": "pull_request",
                        "location": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/pull/2",
                        "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                        "metadata": {
                            "repository_host": "github.com",
                            "repository_owner": "KnoxAnalytics",
                            "repository_name": "HARNESS-DRYRUN",
                            "branch_name": "codex/e2e-test",
                            "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                            "pull_request_number": 2,
                            "state": "open",
                        },
                    },
                    {
                        "reference_id": "attempt-api-github-sync-infer-evidence-no-assignment-1:commit",
                        "artifact_type": "commit",
                        "location": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/commit/8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                        "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                        "metadata": {
                            "repository_host": "github.com",
                            "repository_owner": "KnoxAnalytics",
                            "repository_name": "HARNESS-DRYRUN",
                            "branch_name": "codex/e2e-test",
                            "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                        },
                    },
                ],
                "metadata": {
                    "executor_run_id": "stub-run-sync-infer-evidence-no-assignment-1",
                    "attempt_validation": {
                        "status": "valid",
                        "validated_at": "2026-04-17T12:10:36Z",
                    },
                },
            }
        ]
        service.store.update_task(stored_task)
        self.assertEqual(submit_status, 200)
        reevaluate_status, _ = service.reevaluate(
            task_id,
            {"request": {"acceptance_criteria_satisfied": True}},
        )
        self.assertEqual(reevaluate_status, 200)

        service.reconciliation_registry = _registry_with_current_run_pull_request_gateway()
        sync_status, sync_response = service.submit_github_sync(_github_sync_payload(task_id=task_id))

        self.assertEqual(sync_status, 200)
        self.assertEqual(sync_response["action"], "transition_applied")
        self.assertTrue(sync_response["accepted_completion"])
        self.assertEqual(sync_response["task_envelope"]["status"], "completed")
        evidence = sync_response["task_envelope"]["artifacts"]["completion_evidence"]
        self.assertEqual(evidence["policy"], "required")
        self.assertEqual(evidence["required_artifact_types"], ["pull_request", "commit"])
        self.assertEqual(evidence["status"], "satisfied")
        self.assertEqual(evidence["validation_method"], "external_reconciliation")

    def test_api_github_sync_blocks_resumed_completion_when_acceptance_remains_unconfirmed(self) -> None:
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_no_create_pull_request_gateway(),
        )
        payload = _manual_happy_path_overlay_payload()
        task_envelope = deepcopy(payload["request"]["task_envelope"])
        task_envelope["id"] = "task-api-github-sync-resume-blocked-1"
        task_envelope["title"] = "GitHub sync stays blocked without acceptance proof"
        task_envelope["description"] = "GitHub sync should not crash when repository facts arrive before acceptance is proven."
        task_envelope["artifacts"]["items"] = []
        task_envelope["artifacts"]["completion_evidence"] = {
            "policy": "deferred",
            "status": "deferred",
            "required_artifact_types": ["pull_request", "commit", "changed_file"],
            "validated_artifact_ids": [],
            "validation_method": "deferred",
            "validated_at": None,
            "validator": None,
            "notes": None,
        }
        submit_status, submit_response = service.submit({"request": {"task_envelope": task_envelope}})
        task_id = submit_response["task_envelope"]["id"]

        stored_task = deepcopy(service.store.get_task(task_id))
        stored_task["status"] = "blocked"
        stored_task["assigned_executor"] = {
            "executor_type": "codex",
            "executor_id": "executor-api-github-sync-resume-blocked-1",
            "assignment_reason": "Exercise resumed completion while acceptance remains unconfirmed.",
        }
        execution_metadata = stored_task["observability"]["execution_metadata"]
        execution_metadata["advisory_completion_claims"] = [
            {
                "claim_id": "claim-api-github-sync-resume-blocked-1",
                "reported_at": "2026-04-13T10:00:00Z",
                "reported_by": "codex",
                "reason": "Executor reported completion pending GitHub reconciliation.",
                "metadata": {"attempt_id": "attempt-api-github-sync-resume-blocked-1"},
            }
        ]
        execution_metadata["execution_attempts"] = [
            {
                "attempt_id": "attempt-api-github-sync-resume-blocked-1",
                "recorded_at": "2026-04-13T10:00:05Z",
                "status": "succeeded",
                "reported_by": "codex",
                "completion_claim_id": "claim-api-github-sync-resume-blocked-1",
                "artifact_references": [
                    {
                        "reference_id": "attempt-api-github-sync-resume-blocked-1:pr",
                        "artifact_type": "pull_request",
                        "location": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/pull/2",
                        "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                        "metadata": {
                            "repository_host": "github.com",
                            "repository_owner": "KnoxAnalytics",
                            "repository_name": "HARNESS-DRYRUN",
                            "branch_name": "codex/e2e-test",
                            "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                            "pull_request_number": 2,
                            "state": "open",
                        },
                    },
                    {
                        "reference_id": "attempt-api-github-sync-resume-blocked-1:commit",
                        "artifact_type": "commit",
                        "location": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/commit/8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                        "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                        "metadata": {
                            "repository_host": "github.com",
                            "repository_owner": "KnoxAnalytics",
                            "repository_name": "HARNESS-DRYRUN",
                            "branch_name": "codex/e2e-test",
                            "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                        },
                    },
                ],
                "metadata": {
                    "executor_run_id": "stub-run-sync-blocked-1",
                    "attempt_validation": {
                        "status": "valid",
                        "validated_at": "2026-04-13T10:00:06Z",
                    },
                },
            }
        ]
        service.store.update_task(stored_task)
        self.assertEqual(submit_status, 200)

        service.reconciliation_registry = _registry_with_current_run_pull_request_gateway()
        sync_status, sync_response = service.submit_github_sync(_github_sync_payload(task_id=task_id))

        self.assertEqual(sync_status, 200)
        self.assertEqual(sync_response["action"], "no_op")
        self.assertFalse(sync_response["accepted_completion"])
        self.assertEqual(sync_response["task_envelope"]["status"], "blocked")
        self.assertEqual(
            sync_response["enforcement_result"]["verification_result"]["acceptance_criteria_assessment"][
                "automatic_completion_safe"
            ],
            True,
        )
        self.assertIn("acceptance criteria are not yet satisfied", " ".join(sync_response["reasons"]).lower())
        evidence = sync_response["task_envelope"]["artifacts"]["completion_evidence"]
        self.assertEqual(evidence["policy"], "required")
        self.assertEqual(evidence["status"], "satisfied")
        self.assertEqual(evidence["validation_method"], "external_reconciliation")

    def test_api_github_sync_recovers_after_transient_missing_branch_on_completion_claim(self) -> None:
        service = HarnessApiService(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reconciliation_registry=_registry_with_transient_missing_branch_gateway(),
        )
        payload = _manual_happy_path_overlay_payload()
        task_envelope = deepcopy(payload["request"]["task_envelope"])
        task_envelope["id"] = "task-api-github-sync-transient-branch-1"
        task_envelope["title"] = "GitHub sync resumes after transient branch miss"
        task_envelope["description"] = (
            "A branch visibility miss during completion claim reconciliation should not permanently fail "
            "a task that canonical GitHub sync can immediately prove."
        )
        task_envelope["artifacts"]["items"] = []
        task_envelope["artifacts"]["completion_evidence"] = {
            "policy": "deferred",
            "status": "deferred",
            "required_artifact_types": ["pull_request", "commit"],
            "validated_artifact_ids": [],
            "validation_method": "deferred",
            "validated_at": None,
            "validator": None,
            "notes": None,
        }
        submit_status, submit_response = service.submit({"request": {"task_envelope": task_envelope}})
        task_id = submit_response["task_envelope"]["id"]

        claim_status, claim_response = service.submit_completion_claim(
            task_id,
            {
                "request": {
                    "completion_claim": {
                        "claim_id": "claim-api-github-sync-transient-branch-1",
                        "reported_at": "2026-04-13T10:00:00Z",
                        "reported_by": "codex",
                        "reason": "Executor reported completion pending GitHub reconciliation.",
                        "metadata": {"attempt_id": "attempt-api-github-sync-transient-branch-1"},
                    },
                    "execution_attempt": {
                        "attempt_id": "attempt-api-github-sync-transient-branch-1",
                        "recorded_at": "2026-04-13T10:00:05Z",
                        "status": "succeeded",
                        "reported_by": "codex",
                        "artifact_references": [
                            {
                                "reference_id": "attempt-api-github-sync-transient-branch-1:commit",
                                "artifact_type": "commit",
                                "location": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/commit/8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                                "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                                "metadata": {
                                    "repository_host": "github.com",
                                    "repository_owner": "KnoxAnalytics",
                                    "repository_name": "HARNESS-DRYRUN",
                                    "branch_name": "codex/e2e-test",
                                    "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                                },
                            }
                        ],
                        "metadata": {
                            "executor_run_id": "stub-run-sync-transient-branch-1",
                            "pull_request_url": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/pull/2",
                        },
                    },
                    "external_facts": {
                        "expected_code_context": {
                            "repository_host": "github.com",
                            "repository_owner": "KnoxAnalytics",
                            "repository_name": "HARNESS-DRYRUN",
                            "branch_name": "codex/e2e-test",
                            "base_branch": "main",
                        }
                    },
                    "acceptance_criteria_satisfied": True,
                    "runtime_facts": {
                        "executor_reported_success": True,
                        "attempt_count": 1,
                        "latest_attempt_outcome": "completed",
                    },
                }
            },
        )
        sync_status, sync_response = service.submit_github_sync(_github_sync_payload(task_id=task_id))

        self.assertEqual(submit_status, 200)
        self.assertEqual(claim_status, 200)
        self.assertEqual(claim_response["action"], "reconciliation_blocked")
        self.assertEqual(claim_response["task_envelope"]["status"], "blocked")
        self.assertEqual(sync_status, 200)
        self.assertEqual(sync_response["action"], "transition_applied")
        self.assertTrue(sync_response["accepted_completion"])
        self.assertEqual(sync_response["task_envelope"]["status"], "completed")

    def test_api_exposes_supervision_queue_endpoint(self) -> None:
        create_status, create_payload = self._post_json("/evaluate", _request_payload("review_required"))

        status, payload = self._get_json("/supervision/queue")

        self.assertEqual(create_status, 200)
        self.assertEqual(status, 200)
        self.assertIn("generated_at", payload)
        queue_by_task_id = {item["task_id"]: item for item in payload["queue"]}
        queue_item = queue_by_task_id[create_payload["task_envelope"]["id"]]
        self.assertEqual(queue_item["attention_type"], "review_required")
        self.assertEqual(queue_item["suggested_action"], "resolve_review_gate")

    def test_api_openclaw_ingress_rejects_invalid_payload_without_persisting_state(self) -> None:
        payload = _openclaw_ingress_payload(task_id="task-openclaw-invalid-1")
        payload["context"] = "invalid"

        status, response_payload = self._post_json("/ingress/openclaw", payload)
        task_status, task_payload = self._get_json("/tasks/task-openclaw-invalid-1")

        self.assertEqual(status, 400)
        self.assertTrue(response_payload["invalid_input"])
        self.assertEqual(task_status, 404)
        self.assertIn("not found", task_payload["error"].lower())

    def test_api_openclaw_ingress_rejects_completion_shaped_handoff(self) -> None:
        payload = _openclaw_ingress_payload(task_id="task-openclaw-api-invalid-completion-1")
        payload["acceptance_criteria_satisfied"] = True

        status, response_payload = self._post_json("/ingress/openclaw", payload)
        task_status, task_payload = self._get_json("/tasks/task-openclaw-api-invalid-completion-1")

        self.assertEqual(status, 400)
        self.assertTrue(response_payload["invalid_input"])
        self.assertIn("cannot assert acceptance_criteria_satisfied", response_payload["error"].lower())
        self.assertEqual(task_status, 404)
        self.assertIn("not found", task_payload["error"].lower())

    def test_api_openclaw_ingress_rejects_planned_handoff_with_unresolved_conditions(self) -> None:
        payload = _openclaw_ingress_payload(task_id="task-openclaw-api-invalid-planned-1")
        payload["task"]["status"] = "planned"
        payload["task"]["objective_summary"] = "Produce a routing-ready implementation task."
        payload["task"]["objective_deliverable_type"] = "code_change"
        payload["task"]["objective_success_signal"] = "The task is defined enough to route without clarification."
        payload["metadata"]["plan_summary"] = "Single-task implementation handoff is ready for dispatcher review."
        payload["unresolved_conditions"] = ["Need repo confirmation"]

        status, response_payload = self._post_json("/ingress/openclaw", payload)
        task_status, task_payload = self._get_json("/tasks/task-openclaw-api-invalid-planned-1")

        self.assertEqual(status, 400)
        self.assertTrue(response_payload["invalid_input"])
        self.assertIn("cannot include unresolved_conditions", response_payload["error"].lower())
        self.assertEqual(task_status, 404)
        self.assertIn("not found", task_payload["error"].lower())

    def test_api_accepts_manual_happy_path_overlay_payload(self) -> None:
        payload = _manual_happy_path_overlay_payload()
        del payload["request"]["task_status"]

        status, response = self._post_json("/evaluate", payload)

        self.assertEqual(status, 200)
        self.assertEqual(response["action"], "transition_applied")
        self.assertEqual(response["target_status"], "completed")
        self.assertTrue(response["accepted_completion"])
        self.assertEqual(response["task_envelope"]["status"], "completed")
        self.assertEqual(
            response["enforcement_result"]["verification_result"]["outcome"],
            "accepted_completion",
        )

    def test_api_evaluate_existing_task_rejects_top_level_overlays(self) -> None:
        payload = _manual_happy_path_overlay_payload()
        del payload["request"]["task_status"]
        submit_payload = {"request": {"task_envelope": deepcopy(payload["request"]["task_envelope"])}}

        submit_status, submit_response = self._post_json("/tasks", submit_payload)
        evaluate_status, evaluate_response = self._post_json("/evaluate", payload)

        self.assertEqual(submit_status, 200)
        self.assertEqual(submit_response["task_envelope"]["status"], "intake_ready")
        self.assertEqual(evaluate_status, 400)
        self.assertTrue(evaluate_response["invalid_input"])
        self.assertIn("/tasks/task-http-happy-overlay-1/reevaluate", evaluate_response["error"])
        violation_sources = {violation["source"] for violation in evaluate_response["violations"]}
        self.assertEqual(
            violation_sources,
            {
                "request.assigned_executor",
                "request.linked_artifacts",
                "request.completion_evidence",
            },
        )

    def test_api_persists_blocked_result(self) -> None:
        status, payload = self._post_json("/evaluate", _request_payload("blocked_insufficient_evidence"))
        task_id = payload["task_envelope"]["id"]

        task_status, task_payload = self._get_json(f"/tasks/{task_id}")
        history_status, history_payload = self._get_json(f"/tasks/{task_id}/evaluations")

        self.assertEqual(status, 200)
        self.assertEqual(payload["target_status"], "blocked")
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["status"], "blocked")
        self.assertEqual(history_status, 200)
        self.assertEqual(history_payload["evaluations"][0]["result"]["target_status"], "blocked")

    def test_api_persists_reconciliation_mismatch_result(self) -> None:
        status, payload = self._post_json("/evaluate", _request_payload("blocked_reconciliation_mismatch"))
        task_id = payload["task_envelope"]["id"]

        task_status, task_payload = self._get_json(f"/tasks/{task_id}")
        history_status, history_payload = self._get_json(f"/tasks/{task_id}/evaluations")

        self.assertEqual(status, 200)
        self.assertEqual(payload["target_status"], "blocked")
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["status"], "blocked")
        self.assertEqual(history_status, 200)
        self.assertEqual(
            history_payload["evaluations"][0]["result"]["enforcement_result"]["verification_result"]["outcome"],
            "external_mismatch",
        )

    def test_api_persists_review_required_result(self) -> None:
        status, payload = self._post_json("/evaluate", _request_payload("review_required"))
        task_id = payload["task_envelope"]["id"]

        task_status, task_payload = self._get_json(f"/tasks/{task_id}")
        history_status, history_payload = self._get_json(f"/tasks/{task_id}/evaluations")

        self.assertEqual(status, 200)
        self.assertEqual(payload["action"], "review_required")
        self.assertEqual(payload["target_status"], "in_review")
        self.assertTrue(payload["requires_review"])
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["status"], "in_review")
        self.assertEqual(payload["task_envelope"]["status"], "in_review")
        self.assertEqual(history_status, 200)
        self.assertEqual(history_payload["evaluations"][0]["result"]["action"], "review_required")

    def test_api_review_required_intake_ready_request_does_not_reject_transition(self) -> None:
        payload = _request_payload("review_required")

        self.assertEqual(payload["request"]["task_envelope"]["status"], "intake_ready")

        status, response = self._post_json("/evaluate", payload)

        self.assertEqual(status, 200)
        self.assertEqual(response["action"], "review_required")
        self.assertEqual(response["target_status"], "in_review")
        self.assertEqual(response["task_envelope"]["status"], "in_review")
        self.assertNotEqual(response["action"], "transition_rejected")

    def test_api_rejects_invalid_input_without_persisting_state(self) -> None:
        invalid_payload = _request_payload("invalid_input")
        task_id = invalid_payload["request"]["task_envelope"]["id"]

        status, payload = self._post_json("/evaluate", invalid_payload)
        task_status, task_payload = self._get_json(f"/tasks/{task_id}")
        history_status, history_payload = self._get_json(f"/tasks/{task_id}/evaluations")

        self.assertEqual(status, 400)
        self.assertEqual(payload["action"], "invalid_input")
        self.assertTrue(payload["invalid_input"])
        self.assertEqual(task_status, 404)
        self.assertEqual(history_status, 404)
        self.assertIn("not found", task_payload["error"].lower())
        self.assertIn("not found", history_payload["error"].lower())

    def test_api_retrieves_append_only_evaluation_history(self) -> None:
        payload = _request_payload("accepted_completion")
        task_id = payload["request"]["task_envelope"]["id"]

        first_status, _ = self._post_json("/evaluate", payload)
        second_status, _ = self._post_json("/evaluate", payload)
        history_status, history_payload = self._get_json(f"/tasks/{task_id}/evaluations")

        self.assertEqual(first_status, 200)
        self.assertEqual(second_status, 200)
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 2)

    def test_api_returns_not_found_for_missing_task(self) -> None:
        task_status, task_payload = self._get_json("/tasks/missing-task")
        history_status, history_payload = self._get_json("/tasks/missing-task/evaluations")

        self.assertEqual(task_status, 404)
        self.assertEqual(history_status, 404)
        self.assertIn("not found", task_payload["error"].lower())
        self.assertIn("not found", history_payload["error"].lower())

    def test_api_rejects_malformed_json(self) -> None:
        request = Request(
            self.base_url + "/evaluate",
            data=b"{not-json",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request):
                self.fail("Expected malformed JSON request to be rejected")
        except HTTPError as error:
            self.assertEqual(error.code, 400)
            error.close()

    def test_api_sets_cors_headers_for_browser_clients(self) -> None:
        request = Request(self.base_url + "/tasks", method="OPTIONS")

        with urlopen(request) as response:
            self.assertEqual(response.status, 204)
            self.assertEqual(response.headers["Access-Control-Allow-Origin"], "*")
            self.assertIn("GET", response.headers["Access-Control-Allow-Methods"])

    def test_api_reevaluate_support_evidence_keeps_blocked_task_blocked_until_verified(self) -> None:
        initial_payload = _request_payload("blocked_insufficient_evidence")
        initial_status, initial_response = self._post_json("/evaluate", initial_payload)
        task_id = initial_response["task_envelope"]["id"]

        reevaluation_payload = {
            "request": {
                "new_artifacts": [_review_note_artifact()],
                "completion_evidence": {
                    "validated_artifact_ids": [
                        "artifact-pr-1",
                        "artifact-commit-1",
                        "artifact-review-note-1",
                    ]
                },
                "external_facts": deepcopy(_request_payload("accepted_completion")["request"]["external_facts"]),
                "claimed_completion": True,
                "acceptance_criteria_satisfied": True,
                "runtime_facts": deepcopy(initial_payload["request"]["runtime_facts"]),
            }
        }
        reevaluation_status, reevaluation_response = self._post_json(
            f"/tasks/{task_id}/reevaluate",
            reevaluation_payload,
        )
        history_status, history_payload = self._get_json(f"/tasks/{task_id}/evaluations")

        self.assertEqual(initial_status, 200)
        self.assertEqual(initial_response["task_envelope"]["status"], "blocked")
        self.assertEqual(reevaluation_status, 200)
        self.assertEqual(reevaluation_response["task_envelope"]["status"], "blocked")
        self.assertEqual(reevaluation_response["action"], "no_op")
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 2)

    def test_api_reevaluate_rejects_code_execution_artifacts_and_points_to_completion_claims(self) -> None:
        payload = _manual_happy_path_overlay_payload()
        submit_payload = {"request": {"task_envelope": deepcopy(payload["request"]["task_envelope"])}}

        submit_status, submit_response = self._post_json("/tasks", submit_payload)
        task_id = submit_response["task_envelope"]["id"]
        reevaluation_payload = {
            "request": {
                "new_artifacts": deepcopy(payload["request"]["linked_artifacts"]),
                "completion_evidence": deepcopy(payload["request"]["completion_evidence"]),
                "external_facts": deepcopy(payload["request"]["external_facts"]),
                "claimed_completion": True,
                "acceptance_criteria_satisfied": True,
                "runtime_facts": deepcopy(payload["request"]["runtime_facts"]),
            }
        }

        reevaluation_status, reevaluation_response = self._post_json(
            f"/tasks/{task_id}/reevaluate",
            reevaluation_payload,
        )

        self.assertEqual(submit_status, 200)
        self.assertEqual(submit_response["task_envelope"]["status"], "intake_ready")
        self.assertEqual(reevaluation_status, 400)
        self.assertTrue(reevaluation_response["invalid_input"])
        self.assertEqual(
            reevaluation_response["completion_claim_path"],
            f"/tasks/{task_id}/completion-claims",
        )
        self.assertTrue(
            any(
                violation["rule"] == "reevaluation_execution_artifact_not_allowed"
                for violation in reevaluation_response["violations"]
            )
        )

    def test_api_completion_claim_endpoint_intercepts_claim_and_routes_to_evaluation(self) -> None:
        payload = _manual_happy_path_overlay_payload()
        submit_payload = {"request": {"task_envelope": deepcopy(payload["request"]["task_envelope"])}}
        submit_status, submit_response = self._post_json("/tasks", submit_payload)
        task_id = submit_response["task_envelope"]["id"]

        claim_status, claim_response = self._post_json(
            f"/tasks/{task_id}/completion-claims",
            {
                "request": {
                    **_completion_claim_payload(claim_id="claim-api-1"),
                    "runtime_facts": {"executor_reported_success": True, "attempt_count": 1},
                }
            },
        )
        history_status, history_payload = self._get_json(f"/tasks/{task_id}/evaluations")

        self.assertEqual(submit_status, 200)
        self.assertEqual(claim_status, 200)
        self.assertFalse(claim_response["accepted_completion"])
        self.assertNotEqual(claim_response["task_envelope"]["status"], "completed")
        self.assertEqual(history_status, 200)
        claims = history_payload["evaluations"][-1]["request"]["task_envelope"]["observability"]["execution_metadata"][
            "advisory_completion_claims"
        ]
        self.assertEqual(claims[-1]["claim_id"], "claim-api-1")

    def test_api_reevaluate_rejects_submission_style_mutation_fields(self) -> None:
        payload = _manual_happy_path_overlay_payload()
        submit_payload = {"request": {"task_envelope": deepcopy(payload["request"]["task_envelope"])}}
        submit_status, submit_response = self._post_json("/tasks", submit_payload)
        task_id = submit_response["task_envelope"]["id"]

        reevaluation_status, reevaluation_response = self._post_json(
            f"/tasks/{task_id}/reevaluate",
            {
                "request": {
                    "task_envelope": deepcopy(submit_response["task_envelope"]),
                    "task_status": "completed",
                    "assigned_executor": {
                        "executor_type": "codex",
                        "executor_id": "executor-http-bad-reevaluate-1",
                    },
                    "linked_artifacts": deepcopy(payload["request"]["linked_artifacts"]),
                }
            },
        )

        self.assertEqual(submit_status, 200)
        self.assertEqual(reevaluation_status, 400)
        self.assertTrue(reevaluation_response["invalid_input"])
        self.assertIn(f"/tasks/{task_id}/reevaluate", reevaluation_response["error"])
        violation_sources = {violation["source"] for violation in reevaluation_response["violations"]}
        self.assertEqual(
            violation_sources,
            {
                "request.task_envelope",
                "request.task_status",
                "request.assigned_executor",
                "request.linked_artifacts",
            },
        )

    def test_api_reevaluate_strips_executor_verified_status_from_code_artifacts(self) -> None:
        task_envelope = create_task_envelope(
            {
                "id": "task-api-reevaluate-code-artifact-1",
                "title": "HTTP reevaluate code artifact trust",
                "description": "HTTP reevaluation should not self-certify code-bearing artifacts.",
                "origin": {
                    "source_system": "openclaw",
                    "source_type": "ingress_request",
                    "source_id": "req-api-reevaluate-code-artifact-1",
                },
                "acceptance_criteria": [
                    {
                        "id": "ac-1",
                        "description": "Completion requires a verified pull request.",
                        "required": True,
                    }
                ],
            },
            now="2026-04-07T19:00:00Z",
        )
        task_envelope["artifacts"]["completion_evidence"] = {
            "policy": "required",
            "status": "deferred",
            "required_artifact_types": ["pull_request"],
            "validated_artifact_ids": [],
            "validation_method": "deferred",
            "validated_at": None,
            "validator": None,
            "notes": None,
        }
        submit_status, submit_response = self._post_json("/tasks", {"request": {"task_envelope": task_envelope}})
        task_id = submit_response["task_envelope"]["id"]

        pr_artifact = deepcopy(_manual_happy_path_overlay_payload()["request"]["linked_artifacts"][0])
        pr_artifact["provenance"] = {
            "source_system": "codex",
            "source_type": "executor_report",
            "source_id": "reevaluate/self-certified-pr-api-1",
            "captured_by": "harness-api",
        }
        reevaluation_status, reevaluation_response = self._post_json(
            f"/tasks/{task_id}/reevaluate",
            {
                "request": {
                    "new_artifacts": [pr_artifact],
                    "completion_evidence": {
                        "status": "satisfied",
                        "validated_artifact_ids": [pr_artifact["id"]],
                        "validation_method": "manual_review",
                        "validated_at": "2026-04-07T19:05:00Z",
                        "validator": {
                            "source_system": "harness",
                            "source_type": "verification",
                            "source_id": "verification-api-reevaluate-code-1",
                            "captured_by": "operator",
                        },
                    },
                    "claimed_completion": True,
                    "acceptance_criteria_satisfied": True,
                }
            },
        )

        self.assertEqual(submit_status, 200)
        self.assertEqual(reevaluation_status, 200)
        self.assertFalse(reevaluation_response["accepted_completion"])
        stored_artifact = next(
            artifact
            for artifact in reevaluation_response["task_envelope"]["artifacts"]["items"]
            if artifact["id"] == pr_artifact["id"]
        )
        self.assertEqual(stored_artifact["verification_status"], "unverified")
        self.assertEqual(
            stored_artifact["metadata"]["submitted_verification_status"],
            "verified",
        )
        evidence = reevaluation_response["task_envelope"]["artifacts"]["completion_evidence"]
        self.assertEqual(evidence["validated_artifact_ids"], [])
        self.assertEqual(evidence["status"], "deferred")
        self.assertIsNone(evidence["validated_at"])
        self.assertIsNone(evidence["validator"])
        self.assertEqual(evidence["validation_method"], "deferred")

    def test_api_submit_strips_verified_status_from_initial_support_artifacts(self) -> None:
        payload = {"request": {"task_envelope": deepcopy(_manual_happy_path_overlay_payload()["request"]["task_envelope"])}}
        payload["request"]["task_envelope"]["artifacts"]["items"] = [
            {
                **_review_note_artifact("artifact-api-submit-review-note-1"),
                "provenance": {
                    "source_system": "codex",
                    "source_type": "executor_report",
                    "source_id": "submit/self-certified-review-note-api-1",
                    "captured_by": "harness-api",
                },
            }
        ]

        status, response = self._post_json("/tasks", payload)

        self.assertEqual(status, 200)
        stored_artifact = response["task_envelope"]["artifacts"]["items"][0]
        self.assertEqual(stored_artifact["verification_status"], "unverified")
        self.assertEqual(stored_artifact["metadata"]["submitted_verification_status"], "verified")

    def test_api_evaluate_strips_verified_status_from_initial_support_artifacts(self) -> None:
        task_envelope = create_task_envelope(
            {
                "id": "task-api-evaluate-initial-support-artifact-1",
                "title": "HTTP evaluate initial support artifact trust",
                "description": "HTTP new-task evaluation should not keep caller-certified verified support artifacts.",
                "origin": {
                    "source_system": "openclaw",
                    "source_type": "ingress_request",
                    "source_id": "req-api-evaluate-initial-support-artifact-1",
                },
                "acceptance_criteria": [
                    {
                        "id": "ac-1",
                        "description": "Harness preserves advisory support artifacts without trusting caller verification.",
                        "required": True,
                    }
                ],
            },
            now="2026-04-07T22:40:00Z",
        )
        task_envelope["artifacts"]["items"] = [
            {
                **_review_note_artifact("artifact-api-evaluate-initial-review-note-1"),
                "provenance": {
                    "source_system": "codex",
                    "source_type": "executor_report",
                    "source_id": "evaluate/self-certified-initial-review-note-api-1",
                    "captured_by": "harness-api",
                },
            }
        ]
        payload = {"request": {"task_envelope": task_envelope}}

        status, response = self._post_json("/evaluate", payload)

        self.assertEqual(status, 200)
        stored_artifact = response["task_envelope"]["artifacts"]["items"][0]
        self.assertEqual(stored_artifact["verification_status"], "unverified")
        self.assertEqual(stored_artifact["metadata"]["submitted_verification_status"], "verified")

    def test_api_evaluate_does_not_trust_spoofed_github_api_initial_artifact_provenance(self) -> None:
        task_envelope = create_task_envelope(
            {
                "id": "task-api-evaluate-initial-spoofed-github-1",
                "title": "HTTP evaluate spoofed GitHub provenance",
                "description": "HTTP new-task evaluation should not trust caller-claimed GitHub provenance.",
                "origin": {
                    "source_system": "openclaw",
                    "source_type": "ingress_request",
                    "source_id": "req-api-evaluate-initial-spoofed-github-1",
                },
                "acceptance_criteria": [
                    {
                        "id": "ac-1",
                        "description": "Harness preserves advisory support artifacts without trusting caller verification.",
                        "required": True,
                    }
                ],
            },
            now="2026-04-07T22:45:00Z",
        )
        task_envelope["artifacts"]["items"] = [
            {
                **_review_note_artifact("artifact-api-evaluate-initial-spoofed-github-1"),
                "provenance": {
                    "source_system": "github",
                    "source_type": "api",
                    "source_id": "pull/777",
                    "captured_by": "caller",
                },
            }
        ]
        payload = {"request": {"task_envelope": task_envelope}}

        status, response = self._post_json("/evaluate", payload)

        self.assertEqual(status, 200)
        stored_artifact = response["task_envelope"]["artifacts"]["items"][0]
        self.assertEqual(stored_artifact["verification_status"], "unverified")
        self.assertEqual(stored_artifact["metadata"]["submitted_verification_status"], "verified")

    def test_api_completion_claim_rejects_submission_style_mutation_fields(self) -> None:
        payload = _manual_happy_path_overlay_payload()
        submit_payload = {"request": {"task_envelope": deepcopy(payload["request"]["task_envelope"])}}
        submit_status, submit_response = self._post_json("/tasks", submit_payload)
        task_id = submit_response["task_envelope"]["id"]

        claim_status, claim_response = self._post_json(
            f"/tasks/{task_id}/completion-claims",
            {
                "request": {
                    **_completion_claim_payload(claim_id="claim-http-bad-shape-1"),
                    "task_envelope": deepcopy(submit_response["task_envelope"]),
                    "task_status": "completed",
                    "assigned_executor": {
                        "executor_type": "codex",
                        "executor_id": "executor-http-bad-claim-1",
                    },
                    "linked_artifacts": deepcopy(payload["request"]["linked_artifacts"]),
                }
            },
        )

        self.assertEqual(submit_status, 200)
        self.assertEqual(claim_status, 400)
        self.assertTrue(claim_response["invalid_input"])
        self.assertIn(f"/tasks/{task_id}/completion-claims", claim_response["error"])
        violation_sources = {violation["source"] for violation in claim_response["violations"]}
        self.assertEqual(
            violation_sources,
            {
                "request.task_envelope",
                "request.task_status",
                "request.assigned_executor",
                "request.linked_artifacts",
            },
        )

    def test_api_dispatch_endpoint_records_execution_attempt(self) -> None:
        payload = _manual_happy_path_overlay_payload()
        submit_payload = {
            "request": {
                "task_envelope": deepcopy(payload["request"]["task_envelope"]),
                "task_status": "dispatch_ready",
            }
        }
        submit_status, submit_response = self._post_json("/evaluate", submit_payload)
        task_id = submit_response["task_envelope"]["id"]

        dispatch_status, dispatch_response = self._post_json(
            f"/tasks/{task_id}/dispatch",
            {"request": {"executor": "codex"}},
        )

        self.assertEqual(submit_status, 200)
        self.assertEqual(submit_response["task_envelope"]["status"], "dispatch_ready")
        self.assertEqual(dispatch_status, 200)
        self.assertEqual(dispatch_response["dispatch"]["task_id"], task_id)

    def test_api_can_reevaluate_completed_task_back_to_blocked_for_contradictory_facts(self) -> None:
        initial_payload = _request_payload("accepted_completion")
        initial_status, initial_response = self._post_json("/evaluate", initial_payload)
        task_id = initial_response["task_envelope"]["id"]

        reevaluation_payload = {
            "request": {
                "external_facts": deepcopy(_request_payload("blocked_reconciliation_mismatch")["request"]["external_facts"]),
                "claimed_completion": True,
                "acceptance_criteria_satisfied": True,
                "runtime_facts": deepcopy(initial_payload["request"]["runtime_facts"]),
            }
        }
        reevaluation_status, reevaluation_response = self._post_json(
            f"/tasks/{task_id}/reevaluate",
            reevaluation_payload,
        )

        self.assertEqual(initial_status, 200)
        self.assertEqual(initial_response["task_envelope"]["status"], "completed")
        self.assertEqual(reevaluation_status, 200)
        self.assertEqual(reevaluation_response["task_envelope"]["status"], "blocked")
        self.assertEqual(
            reevaluation_response["enforcement_result"]["verification_result"]["outcome"],
            "external_mismatch",
        )

    def test_api_can_reevaluate_review_required_path_to_completed_after_manual_review(self) -> None:
        accepted_payload = _request_payload("accepted_completion")
        initial_payload = {
            "request": deepcopy(accepted_payload["request"]),
        }
        initial_payload["request"]["task_envelope"]["status"] = "blocked"
        initial_payload["request"]["task_envelope"]["timestamps"]["completed_at"] = None
        initial_payload["request"]["review_request"] = deepcopy(_request_payload("review_required")["request"]["review_request"])
        initial_payload["request"]["review_request"]["task_id"] = initial_payload["request"]["task_envelope"]["id"]
        initial_payload["request"]["external_facts"] = deepcopy(_request_payload("review_required")["request"]["external_facts"])

        initial_status, initial_response = self._post_json("/evaluate", initial_payload)
        task_id = initial_response["task_envelope"]["id"]

        reevaluation_payload = {
            "request": {
                "review_decision": _review_decision_payload(task_id),
            }
        }
        reevaluation_status, reevaluation_response = self._post_json(
            f"/tasks/{task_id}/reevaluate",
            reevaluation_payload,
        )

        self.assertEqual(initial_status, 200)
        self.assertEqual(initial_response["action"], "review_required")
        self.assertEqual(initial_response["task_envelope"]["status"], "in_review")
        self.assertEqual(reevaluation_status, 200)
        self.assertEqual(reevaluation_response["task_envelope"]["status"], "completed")
        self.assertIn(reevaluation_response["action"], {"transition_applied", "follow_up_authorized"})

    def test_api_authorize_redispatch_triggers_automatic_dispatch(self) -> None:
        initial_payload = _request_payload("review_required")
        initial_payload["request"]["review_request"]["allowed_outcomes"] = [
            "accept_completion",
            "authorize_redispatch",
        ]

        initial_status, initial_response = self._post_json("/evaluate", initial_payload)
        task_id = initial_response["task_envelope"]["id"]

        stored_task = deepcopy(self.server.RequestHandlerClass.service.store.get_task(task_id))
        stored_task["observability"]["execution_metadata"]["execution_attempts"] = [
            {
                "attempt_id": "attempt-1",
                "recorded_at": "2026-03-24T17:05:00Z",
                "status": "completed",
                "reported_by": "codex",
                "completion_claim_id": "claim-prior-1",
                "artifact_references": [],
                "metadata": {"dispatch_trigger": "manual_api"},
                "reevaluation": {
                    "evaluation_id": "evaluation-prior-1",
                    "linked_at": "2026-03-24T17:06:00Z",
                    "action": "review_required",
                },
            }
        ]
        self.server.RequestHandlerClass.service.store.update_task(stored_task)

        reevaluation_status, reevaluation_response = self._post_json(
            f"/tasks/{task_id}/reevaluate",
            {
                "request": {
                    "review_decision": _review_decision_payload(
                        task_id,
                        outcome=ReviewOutcome.AUTHORIZE_REDISPATCH,
                        allowed_outcomes=(
                            ReviewOutcome.ACCEPT_COMPLETION,
                            ReviewOutcome.AUTHORIZE_REDISPATCH,
                        ),
                    )
                }
            },
        )

        self.assertEqual(initial_status, 200)
        self.assertEqual(reevaluation_status, 200)
        self.assertEqual(reevaluation_response["target_status"], "failed")
        self.assertTrue(reevaluation_response["automatic_dispatch"]["attempted"])
        self.assertEqual(reevaluation_response["automatic_dispatch"]["status"], 200)
        self.assertEqual(reevaluation_response["automatic_dispatch"]["dispatch"]["attempt_id"], "attempt-2")
        self.assertEqual(reevaluation_response["task_envelope"]["status"], "failed")

    def test_api_authorize_retry_without_assignment_keeps_review_gate_active(self) -> None:
        initial_payload = _request_payload("review_required")
        initial_payload["request"]["review_request"]["allowed_outcomes"] = [
            "accept_completion",
            "authorize_retry",
        ]

        initial_status, initial_response = self._post_json("/evaluate", initial_payload)
        task_id = initial_response["task_envelope"]["id"]

        reevaluation_status, reevaluation_response = self._post_json(
            f"/tasks/{task_id}/reevaluate",
            {
                "request": {
                    "review_decision": _review_decision_payload(
                        task_id,
                        outcome=ReviewOutcome.AUTHORIZE_RETRY,
                        allowed_outcomes=(
                            ReviewOutcome.ACCEPT_COMPLETION,
                            ReviewOutcome.AUTHORIZE_RETRY,
                        ),
                    )
                }
            },
        )
        read_status, read_payload = self._get_json(f"/tasks/{task_id}/read-model")
        timeline_status, timeline_payload = self._get_json(f"/tasks/{task_id}/timeline")

        self.assertEqual(initial_status, 200)
        self.assertEqual(reevaluation_status, 200)
        self.assertEqual(reevaluation_response["action"], "transition_rejected")
        self.assertTrue(reevaluation_response["requires_review"])
        self.assertEqual(reevaluation_response["task_envelope"]["status"], "in_review")
        self.assertEqual(read_status, 200)
        self.assertEqual(read_payload["task"]["review_summary"]["status"], "requested")
        self.assertEqual(timeline_status, 200)
        self.assertTrue(
            any(event["event_type"] == "review_decision_rejected" for event in timeline_payload["timeline"])
        )
        self.assertFalse(any(event["event_type"] == "review_decided" for event in timeline_payload["timeline"]))

    def test_api_can_accept_completion_after_rejected_retry_attempt(self) -> None:
        initial_payload = _request_payload("review_required")
        initial_payload["request"]["review_request"]["allowed_outcomes"] = [
            "accept_completion",
            "authorize_retry",
        ]

        initial_status, initial_response = self._post_json("/evaluate", initial_payload)
        task_id = initial_response["task_envelope"]["id"]

        rejected_status, rejected_response = self._post_json(
            f"/tasks/{task_id}/reevaluate",
            {
                "request": {
                    "review_decision": _review_decision_payload(
                        task_id,
                        outcome=ReviewOutcome.AUTHORIZE_RETRY,
                        allowed_outcomes=(
                            ReviewOutcome.ACCEPT_COMPLETION,
                            ReviewOutcome.AUTHORIZE_RETRY,
                        ),
                    )
                }
            },
        )
        accepted_status, accepted_response = self._post_json(
            f"/tasks/{task_id}/reevaluate",
            {
                "request": {
                    "review_decision": _review_decision_payload(
                        task_id,
                        outcome=ReviewOutcome.ACCEPT_COMPLETION,
                        allowed_outcomes=(
                            ReviewOutcome.ACCEPT_COMPLETION,
                            ReviewOutcome.AUTHORIZE_RETRY,
                        ),
                    )
                }
            },
        )

        self.assertEqual(initial_status, 200)
        self.assertEqual(rejected_status, 200)
        self.assertEqual(rejected_response["action"], "transition_rejected")
        self.assertEqual(accepted_status, 200)
        self.assertEqual(accepted_response["action"], "transition_applied")
        self.assertEqual(accepted_response["task_envelope"]["status"], "completed")

    def test_api_reconciliation_authorize_redispatch_returns_post_dispatch_failure_truth(self) -> None:
        self.server.RequestHandlerClass.service.reconciliation_registry = _registry_with_no_create_pull_request_gateway()
        payload = _manual_happy_path_overlay_payload()
        submit_status, submit_response = self._post_json(
            "/tasks",
            {"request": {"task_envelope": deepcopy(payload["request"]["task_envelope"])}},
        )
        task_id = submit_response["task_envelope"]["id"]
        stored_task = deepcopy(self.server.RequestHandlerClass.service.store.get_task(task_id))
        stored_task["status"] = "assigned"
        stored_task["assigned_executor"] = {
            "executor_type": "codex",
            "executor_id": "executor-reconcile-redispatch-api-1",
            "assignment_reason": "Seed active assignment for reconciliation redispatch coverage.",
        }
        self.server.RequestHandlerClass.service.store.update_task(stored_task)

        valid_attempt_payload = _execution_attempt_payload(attempt_id="attempt-valid-no-pr-redispatch-api-1")
        valid_attempt_payload["execution_attempt"]["artifact_references"] = [
            {
                "reference_id": "attempt-valid-no-pr-redispatch-api-1:commit",
                "artifact_type": "commit",
                "location": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/commit/8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                "metadata": {
                    "repository_host": "github.com",
                    "repository_owner": "KnoxAnalytics",
                    "repository_name": "HARNESS-DRYRUN",
                    "branch_name": "codex/e2e-test",
                    "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                },
            }
        ]
        claim_status, claim_response = self._post_json(
            f"/tasks/{task_id}/completion-claims",
            {
                "request": {
                    **_completion_claim_payload(claim_id="claim-valid-no-pr-redispatch-api-1"),
                    **valid_attempt_payload,
                    "external_facts": deepcopy(payload["request"]["external_facts"]),
                    "runtime_facts": {"executor_reported_success": True, "attempt_count": 1},
                }
            },
        )

        review_request_payload = claim_response["evaluation_record"]["result"]["enforcement_result"]["review_request"]
        reevaluation_status, reevaluation_response = self._post_json(
            f"/tasks/{task_id}/reevaluate",
            {
                "request": {
                    "review_decision": _to_jsonable(
                        resolve_review_request(
                            ReviewRequest(
                                review_request_id=review_request_payload["review_request_id"],
                                task_id=review_request_payload["task_id"],
                                requested_at=review_request_payload["requested_at"],
                                requested_by=review_request_payload["requested_by"],
                                trigger=ReviewTrigger(review_request_payload["trigger"]),
                                summary=review_request_payload["summary"],
                                presented_sections=tuple(review_request_payload["presented_sections"]),
                                allowed_outcomes=tuple(
                                    ReviewOutcome(item) for item in review_request_payload["allowed_outcomes"]
                                ),
                                prior_review_ids=tuple(review_request_payload.get("prior_review_ids", ())),
                                metadata=dict(review_request_payload.get("metadata", {})),
                            ),
                            review_id="review-reconcile-redispatch-api-1",
                            reviewer=ReviewerIdentity(
                                reviewer_id="operator-1",
                                reviewer_name="Casey Reviewer",
                                authority_role="operator",
                            ),
                            outcome=ReviewOutcome.AUTHORIZE_REDISPATCH,
                            reasoning="Manual review authorized redispatch for a new grounded execution attempt.",
                        )
                    )
                }
            },
        )

        self.assertEqual(submit_status, 200)
        self.assertEqual(claim_status, 200)
        self.assertEqual(claim_response["task_envelope"]["status"], "in_review")
        self.assertEqual(reevaluation_status, 200)
        self.assertEqual(reevaluation_response["action"], "contract_violation_failed")
        self.assertEqual(reevaluation_response["target_status"], "failed")
        self.assertTrue(reevaluation_response["automatic_dispatch"]["attempted"])
        self.assertEqual(reevaluation_response["automatic_dispatch"]["dispatch"]["attempt_id"], "attempt-2")
        self.assertEqual(reevaluation_response["task_envelope"]["status"], "failed")

    def test_api_reevaluate_resumes_dispatch_ready_clarification_and_auto_dispatches(self) -> None:
        payload = _manual_ingress_payload(task_id="task-clarification-resume-dispatch-api-1")
        payload["task_status"] = "dispatch_ready"
        payload["unresolved_conditions"] = ["Need repository clarification before dispatch can begin."]

        submit_status, submit_response = self._post_json("/ingress/manual", payload)
        task_id = submit_response["task_envelope"]["id"]

        reevaluation_status, reevaluation_response = self._post_json(
            f"/tasks/{task_id}/reevaluate",
            {"request": {"claimed_completion": False, "acceptance_criteria_satisfied": False}},
        )

        self.assertEqual(submit_status, 200)
        self.assertEqual(submit_response["task_envelope"]["status"], "blocked")
        self.assertEqual(reevaluation_status, 200)
        self.assertNotIn(reevaluation_response["task_envelope"]["status"], {"blocked", "dispatch_ready"})
        self.assertTrue(reevaluation_response["automatic_dispatch"]["attempted"])
        self.assertEqual(reevaluation_response["automatic_dispatch"]["status"], 200)
        self.assertEqual(reevaluation_response["automatic_dispatch"]["dispatch"]["attempt_id"], "attempt-1")
        self.assertEqual(
            reevaluation_response["task_envelope"]["clarification"]["resume_target_status"],
            "dispatch_ready",
        )

    def test_api_reevaluate_resumes_assigned_clarification_to_active_assignment(self) -> None:
        submit_payload = {"request": {"task_envelope": deepcopy(_manual_happy_path_overlay_payload()["request"]["task_envelope"])}}
        submit_status, submit_response = self._post_json("/tasks", submit_payload)
        task_id = submit_response["task_envelope"]["id"]

        stored_task = deepcopy(self.server.RequestHandlerClass.service.store.get_task(task_id))
        stored_task["status"] = "assigned"
        stored_task["assigned_executor"] = {
            "executor_type": "codex",
            "executor_id": "executor-clarification-resume-api-1",
            "assignment_reason": "Resume active assignment after clarification.",
        }
        self.server.RequestHandlerClass.service.store.update_task(stored_task)

        blocked_status, blocked_response = self._post_json(
            f"/tasks/{task_id}/reevaluate",
            {"request": {"unresolved_conditions": ["Need clarification before the assigned work can continue."]}},
        )
        reevaluation_status, reevaluation_response = self._post_json(
            f"/tasks/{task_id}/reevaluate",
            {"request": {"claimed_completion": False, "acceptance_criteria_satisfied": False}},
        )

        self.assertEqual(submit_status, 200)
        self.assertEqual(blocked_status, 200)
        self.assertEqual(blocked_response["task_envelope"]["status"], "blocked")
        self.assertEqual(reevaluation_status, 200)
        self.assertEqual(reevaluation_response["task_envelope"]["status"], "assigned")
        self.assertEqual(
            reevaluation_response["task_envelope"]["assigned_executor"]["executor_id"],
            "executor-clarification-resume-api-1",
        )
        self.assertEqual(reevaluation_response["task_envelope"]["clarification"]["status"], "resolved")

    def test_api_reevaluate_rejects_review_decision_with_mismatched_target_status(self) -> None:
        initial_status, initial_response = self._post_json("/evaluate", _request_payload("review_required"))
        task_id = initial_response["task_envelope"]["id"]

        reevaluation_status, reevaluation_response = self._post_json(
            f"/tasks/{task_id}/reevaluate",
            {
                "request": {
                    "review_decision": _tampered_review_decision_payload(
                        task_id,
                        recommended_target_status="failed",
                        authorized_target_status="failed",
                    )
                }
            },
        )

        self.assertEqual(initial_status, 200)
        self.assertEqual(reevaluation_status, 400)
        self.assertTrue(reevaluation_response["invalid_input"])
        self.assertIn("review_decision", reevaluation_response["error"])

    def test_api_reevaluate_rejects_review_decision_without_active_review_gate(self) -> None:
        initial_status, initial_response = self._post_json("/evaluate", _request_payload("accepted_completion"))
        task_id = initial_response["task_envelope"]["id"]

        reevaluation_status, reevaluation_response = self._post_json(
            f"/tasks/{task_id}/reevaluate",
            {"request": {"review_decision": _review_decision_payload(task_id)}},
        )

        self.assertEqual(initial_status, 200)
        self.assertEqual(reevaluation_status, 400)
        self.assertTrue(reevaluation_response["invalid_input"])
        self.assertIn("active review", reevaluation_response["error"])

    def test_api_reevaluate_rejects_review_decision_backdated_before_request(self) -> None:
        initial_status, initial_response = self._post_json("/evaluate", _request_payload("review_required"))
        task_id = initial_response["task_envelope"]["id"]
        backdated = _review_decision_payload(task_id)
        backdated["record"]["reviewed_at"] = "2026-03-24T19:59:59Z"

        reevaluation_status, reevaluation_response = self._post_json(
            f"/tasks/{task_id}/reevaluate",
            {"request": {"review_decision": backdated}},
        )
        task_status, task_payload = self._get_json(f"/tasks/{task_id}")

        self.assertEqual(initial_status, 200)
        self.assertEqual(reevaluation_status, 400)
        self.assertTrue(reevaluation_response["invalid_input"])
        self.assertIn("reviewed_at must not be earlier than requested_at", reevaluation_response["error"])
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["status"], "in_review")

    def test_api_cannot_reevaluate_in_review_task_to_completed_without_manual_decision(self) -> None:
        initial_status, initial_response = self._post_json("/evaluate", _request_payload("review_required"))
        task_id = initial_response["task_envelope"]["id"]

        reevaluation_status, reevaluation_response = self._post_json(
            f"/tasks/{task_id}/reevaluate",
            {
                "request": {
                    "external_facts": deepcopy(_request_payload("accepted_completion")["request"]["external_facts"]),
                    "claimed_completion": True,
                    "acceptance_criteria_satisfied": True,
                    "runtime_facts": deepcopy(_request_payload("accepted_completion")["request"]["runtime_facts"]),
                }
            },
        )
        task_status, task_payload = self._get_json(f"/tasks/{task_id}")

        self.assertEqual(initial_status, 200)
        self.assertEqual(initial_response["task_envelope"]["status"], "in_review")
        self.assertEqual(reevaluation_status, 200)
        self.assertEqual(reevaluation_response["action"], "review_required")
        self.assertEqual(reevaluation_response["task_envelope"]["status"], "in_review")
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["status"], "in_review")

    def test_api_cannot_bypass_active_review_gate_via_evaluate_upsert(self) -> None:
        initial_status, initial_response = self._post_json("/evaluate", _request_payload("review_required"))
        task_id = initial_response["task_envelope"]["id"]

        overwrite_payload = _request_payload("accepted_completion")
        overwrite_payload["request"]["task_envelope"]["id"] = task_id
        overwrite_payload["request"]["task_envelope"]["status"] = "completed"
        overwrite_payload["request"]["task_envelope"]["timestamps"]["completed_at"] = "2026-03-24T18:00:00Z"

        overwrite_status, overwrite_response = self._post_json("/evaluate", overwrite_payload)
        task_status, task_payload = self._get_json(f"/tasks/{task_id}")

        self.assertEqual(initial_status, 200)
        self.assertEqual(initial_response["task_envelope"]["status"], "in_review")
        self.assertEqual(overwrite_status, 200)
        self.assertEqual(overwrite_response["action"], "review_required")
        self.assertEqual(overwrite_response["task_envelope"]["status"], "in_review")
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["status"], "in_review")

    def test_api_accepts_review_required_linear_facts_with_null_workflow_when_record_not_found(self) -> None:
        payload = _request_payload("review_required")

        status, response = self._post_json("/evaluate", payload)

        self.assertEqual(status, 200)
        self.assertEqual(response["action"], "review_required")

    def test_api_accepts_review_required_linear_facts_with_omitted_workflow_when_record_not_found(self) -> None:
        payload = _request_payload("review_required")
        del payload["request"]["external_facts"]["linear_facts"]["workflow"]

        status, response = self._post_json("/evaluate", payload)

        self.assertEqual(status, 200)
        self.assertEqual(response["action"], "review_required")

    def test_api_rejects_record_found_linear_facts_without_workflow(self) -> None:
        payload = _request_payload("accepted_completion")
        del payload["request"]["external_facts"]["linear_facts"]["workflow"]

        status, response = self._post_json("/evaluate", payload)

        self.assertEqual(status, 400)
        self.assertTrue(response["invalid_input"])
        self.assertEqual(
            response["error"],
            "Invalid external_facts.linear_facts.workflow: must be null/omitted when record_found=false, or an object with workflow_id and workflow_name when record_found=true",
        )

    def test_api_rejects_record_found_linear_facts_with_incomplete_workflow(self) -> None:
        payload = _request_payload("accepted_completion")
        payload["request"]["external_facts"]["linear_facts"]["workflow"] = {
            "workflow_id": "workflow-in-progress",
        }

        status, response = self._post_json("/evaluate", payload)

        self.assertEqual(status, 400)
        self.assertTrue(response["invalid_input"])
        self.assertEqual(
            response["error"],
            "Invalid external_facts.linear_facts.workflow: must be null/omitted when record_found=false, or an object with workflow_id and workflow_name when record_found=true",
        )

    def test_api_can_reevaluate_pending_task_to_completed_when_external_facts_arrive(self) -> None:
        initial_payload = _request_payload("accepted_completion")
        initial_payload["request"]["external_facts"] = None

        initial_status, initial_response = self._post_json("/evaluate", initial_payload)
        task_id = initial_payload["request"]["task_envelope"]["id"]

        reevaluation_payload = {
            "request": {
                "external_facts": deepcopy(_request_payload("accepted_completion")["request"]["external_facts"]),
                "claimed_completion": True,
                "acceptance_criteria_satisfied": True,
                "runtime_facts": deepcopy(initial_payload["request"]["runtime_facts"]),
            }
        }
        reevaluation_status, reevaluation_response = self._post_json(
            f"/tasks/{task_id}/reevaluate",
            reevaluation_payload,
        )

        self.assertEqual(initial_status, 200)
        self.assertEqual(initial_response["task_envelope"]["status"], "blocked")
        self.assertEqual(
            initial_response["enforcement_result"]["verification_result"]["outcome"],
            "blocked_unresolved_conditions",
        )
        self.assertEqual(reevaluation_status, 200)
        self.assertEqual(reevaluation_response["task_envelope"]["status"], "completed")
        self.assertEqual(
            reevaluation_response["task_envelope"]["coordination"]["linear"]["provenance"]["source"],
            "reevaluation_request.external_facts",
        )

    def test_api_persists_linear_coordination_when_record_not_found_and_when_conflicting(self) -> None:
        initial_payload = _request_payload("accepted_completion")
        initial_status, initial_response = self._post_json("/evaluate", initial_payload)
        task_id = initial_response["task_envelope"]["id"]

        missing_record_payload = {
            "request": {
                "external_facts": {
                    "linear_facts": {
                        "record_found": False,
                        "reasons": ["Linear record was not found during sync."],
                    }
                },
                "claimed_completion": True,
                "acceptance_criteria_satisfied": True,
                "runtime_facts": deepcopy(initial_payload["request"]["runtime_facts"]),
            }
        }
        missing_status, missing_response = self._post_json(f"/tasks/{task_id}/reevaluate", missing_record_payload)

        stale_record_payload = {
            "request": {
                "external_facts": deepcopy(_request_payload("blocked_reconciliation_mismatch")["request"]["external_facts"]),
                "claimed_completion": True,
                "acceptance_criteria_satisfied": True,
                "runtime_facts": deepcopy(initial_payload["request"]["runtime_facts"]),
            }
        }
        stale_status, stale_response = self._post_json(f"/tasks/{task_id}/reevaluate", stale_record_payload)

        self.assertEqual(initial_status, 200)
        self.assertEqual(missing_status, 200)
        self.assertFalse(missing_response["task_envelope"]["coordination"]["linear"]["record_found"])
        self.assertEqual(stale_status, 200)
        self.assertEqual(stale_response["task_envelope"]["coordination"]["linear"]["state"], "in_progress")

    def test_api_appends_long_running_support_artifacts_across_reevaluations(self) -> None:
        initial_payload = _request_payload("blocked_insufficient_evidence")
        initial_status, initial_response = self._post_json("/evaluate", initial_payload)
        task_id = initial_response["task_envelope"]["id"]

        first_reevaluation_status, _ = self._post_json(
            f"/tasks/{task_id}/reevaluate",
            {
                "request": {
                    "new_artifacts": [_progress_artifact()],
                    "external_facts": deepcopy(initial_payload["request"]["external_facts"]),
                    "claimed_completion": True,
                    "acceptance_criteria_satisfied": True,
                    "runtime_facts": deepcopy(initial_payload["request"]["runtime_facts"]),
                }
            },
        )
        second_reevaluation_status, _ = self._post_json(
            f"/tasks/{task_id}/reevaluate",
            {
                "request": {
                    "new_artifacts": [_handoff_artifact()],
                    "external_facts": deepcopy(initial_payload["request"]["external_facts"]),
                    "claimed_completion": True,
                    "acceptance_criteria_satisfied": True,
                    "runtime_facts": deepcopy(initial_payload["request"]["runtime_facts"]),
                }
            },
        )
        task_status, task_payload = self._get_json(f"/tasks/{task_id}")
        history_status, history_payload = self._get_json(f"/tasks/{task_id}/evaluations")

        artifact_types = [item["type"] for item in task_payload["task"]["artifacts"]["items"]]

        self.assertEqual(initial_status, 200)
        self.assertEqual(first_reevaluation_status, 200)
        self.assertEqual(second_reevaluation_status, 200)
        self.assertEqual(task_status, 200)
        self.assertEqual(history_status, 200)
        self.assertIn("progress_artifact", artifact_types)
        self.assertIn("handoff_artifact", artifact_types)
        self.assertEqual(len(history_payload["evaluations"]), 3)
        self.assertEqual(
            task_payload["task"]["artifacts"]["completion_evidence"]["validated_artifact_ids"],
            ["artifact-pr-1", "artifact-commit-1"],
        )

    def test_api_rejects_invalid_reevaluation_without_corrupting_store_state(self) -> None:
        initial_payload = _request_payload("accepted_completion")
        initial_status, initial_response = self._post_json("/evaluate", initial_payload)
        task_id = initial_response["task_envelope"]["id"]
        before_task_status, before_task_payload = self._get_json(f"/tasks/{task_id}")
        before_history_status, before_history_payload = self._get_json(f"/tasks/{task_id}/evaluations")

        invalid_status, invalid_payload = self._post_json(
            f"/tasks/{task_id}/reevaluate",
            {
                "request": {
                    "new_artifacts": [_review_note_artifact("artifact-pr-1")],
                    "claimed_completion": True,
                    "acceptance_criteria_satisfied": True,
                }
            },
        )
        after_task_status, after_task_payload = self._get_json(f"/tasks/{task_id}")
        after_history_status, after_history_payload = self._get_json(f"/tasks/{task_id}/evaluations")

        self.assertEqual(initial_status, 200)
        self.assertEqual(before_task_status, 200)
        self.assertEqual(before_history_status, 200)
        self.assertEqual(invalid_status, 400)
        self.assertTrue(invalid_payload["invalid_input"])
        self.assertEqual(after_task_status, 200)
        self.assertEqual(after_history_status, 200)
        self.assertEqual(before_task_payload["task"], after_task_payload["task"])
        self.assertEqual(before_history_payload["evaluations"], after_history_payload["evaluations"])


if __name__ == "__main__":
    unittest.main()
