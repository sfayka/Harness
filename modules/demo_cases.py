"""Canonical demo cases for local Harness evaluation."""

from __future__ import annotations

from modules.contracts.task_envelope_end_to_end import (
    build_canonical_fact_bundle,
    build_expected_code_context,
    build_github_completion_facts,
    build_linear_completion_facts,
)
from modules.contracts.task_envelope_review import ReviewOutcome, ReviewRequest, ReviewTrigger
from modules.contracts.task_envelope_verification import RuntimeVerificationFacts
from modules.evaluation import HarnessEvaluationRequest


def _valid_artifacts() -> dict:
    return {
        "items": [
            {
                "id": "artifact-pr-1",
                "type": "pull_request",
                "title": "Harness demo case",
                "description": None,
                "location": "https://github.com/example/harness/pull/300",
                "content_type": None,
                "external_id": "PR-300",
                "commit_sha": None,
                "pull_request_number": 300,
                "review_state": "approved",
                "provenance": {
                    "source_system": "github",
                    "source_type": "api",
                    "source_id": "pull/300",
                    "captured_by": "github-sync",
                },
                "verification_status": "verified",
                "repository": {
                    "host": "github.com",
                    "owner": "sfayka",
                    "name": "Harness",
                    "external_id": "repo-123",
                },
                "branch": {
                    "name": "codex/demo",
                    "base_branch": "main",
                    "head_commit_sha": "abcdef1234567890",
                },
                "changed_files": [],
                "external_refs": [],
                "captured_at": "2026-03-24T20:10:00Z",
                "metadata": {},
            },
            {
                "id": "artifact-commit-1",
                "type": "commit",
                "title": None,
                "description": None,
                "location": "https://github.com/example/harness/commit/abcdef1234567890",
                "content_type": None,
                "external_id": "commit-abcdef1234567890",
                "commit_sha": "abcdef1234567890",
                "pull_request_number": None,
                "review_state": None,
                "provenance": {
                    "source_system": "github",
                    "source_type": "api",
                    "source_id": "commit/abcdef1234567890",
                    "captured_by": "github-sync",
                },
                "verification_status": "verified",
                "repository": {
                    "host": "github.com",
                    "owner": "sfayka",
                    "name": "Harness",
                    "external_id": "repo-123",
                },
                "branch": None,
                "changed_files": [],
                "external_refs": [],
                "captured_at": "2026-03-24T20:11:00Z",
                "metadata": {},
            },
        ],
        "completion_evidence": {
            "policy": "required",
            "status": "satisfied",
            "required_artifact_types": ["pull_request", "commit"],
            "validated_artifact_ids": ["artifact-pr-1", "artifact-commit-1"],
            "validation_method": "external_reconciliation",
            "validated_at": "2026-03-24T20:14:00Z",
            "validator": {
                "source_system": "harness",
                "source_type": "verification",
                "source_id": "verification-run-demo-1",
                "captured_by": "github-sync",
            },
        },
    }


def _base_task(status: str = "executing") -> dict:
    assigned_executor = None
    completed_at = None
    if status in {"executing", "assigned"}:
        assigned_executor = {
            "executor_type": "codex",
            "executor_id": "executor-1",
            "assignment_reason": "Capability match.",
        }
    if status == "completed":
        completed_at = "2026-03-24T20:15:00Z"

    return {
        "id": f"task-demo-{status}-1",
        "title": "Harness demo task",
        "description": "Task used to demonstrate the Harness evaluation entry point.",
        "origin": {
            "source_system": "openclaw",
            "source_type": "ingress_request",
            "source_id": "req-demo-1",
            "ingress_id": None,
            "ingress_name": "OpenClaw",
            "requested_by": None,
        },
        "status": status,
        "timestamps": {
            "created_at": "2026-03-24T20:00:00Z",
            "updated_at": "2026-03-24T20:05:00Z",
            "completed_at": completed_at,
        },
        "status_history": [],
        "objective": {
            "summary": "Demonstrate the Harness evaluation path.",
            "deliverable_type": "code_change",
            "success_signal": "The evaluator returns a structured control-plane result.",
        },
        "constraints": [],
        "acceptance_criteria": [
            {
                "id": "ac-1",
                "description": "Completion is backed by valid evidence and normalized external facts.",
                "required": True,
            }
        ],
        "parent_task_id": None,
        "child_task_ids": [],
        "dependencies": [],
        "assigned_executor": assigned_executor,
        "required_capabilities": [],
        "priority": "normal",
        "artifacts": _valid_artifacts(),
        "observability": {
            "errors": [],
            "retries": {
                "attempt_count": 0,
                "max_attempts": 0,
                "last_retry_at": None,
            },
            "execution_metadata": {},
        },
    }


def _aligned_bundle(*, linear_state: str = "in_progress"):
    return build_canonical_fact_bundle(
        expected_code_context=build_expected_code_context(
            repository_owner="sfayka",
            repository_name="Harness",
            branch_name="codex/demo",
            base_branch="main",
        ),
        github_facts=build_github_completion_facts(
            repository_owner="sfayka",
            repository_name="Harness",
            branch_name="codex/demo",
            base_branch="main",
            pull_request_number=300,
            review_state="approved",
        ),
        linear_facts=build_linear_completion_facts(
            issue_id="lin-demo-1",
            issue_key="HAR-300",
            state=linear_state,
        ),
    )


def list_demo_cases() -> tuple[str, ...]:
    """Return the canonical demo-case names supported by the CLI."""

    return (
        "accepted_completion",
        "blocked_insufficient_evidence",
        "blocked_reconciliation_mismatch",
        "review_required",
        "invalid_input",
    )


def build_demo_request(case_name: str) -> HarnessEvaluationRequest:
    """Build a canonical demo request by name."""

    if case_name == "accepted_completion":
        return HarnessEvaluationRequest(
            task_envelope=_base_task(status="executing"),
            external_facts=_aligned_bundle(linear_state="in_progress"),
            claimed_completion=True,
            acceptance_criteria_satisfied=True,
            runtime_facts=RuntimeVerificationFacts(executor_reported_success=True, attempt_count=1),
        )

    if case_name == "blocked_insufficient_evidence":
        task = _base_task(status="completed")
        task["artifacts"]["completion_evidence"]["required_artifact_types"].append("review_note")
        return HarnessEvaluationRequest(
            task_envelope=task,
            external_facts=_aligned_bundle(linear_state="completed"),
            claimed_completion=True,
            acceptance_criteria_satisfied=True,
            runtime_facts=RuntimeVerificationFacts(executor_reported_success=True),
        )

    if case_name == "blocked_reconciliation_mismatch":
        return HarnessEvaluationRequest(
            task_envelope=_base_task(status="completed"),
            external_facts=_aligned_bundle(linear_state="in_progress"),
            claimed_completion=True,
            acceptance_criteria_satisfied=True,
            runtime_facts=RuntimeVerificationFacts(executor_reported_success=True),
        )

    if case_name == "review_required":
        task = _base_task(status="completed")
        review_request = ReviewRequest(
            review_request_id="review-request-demo-1",
            task_id=task["id"],
            requested_at="2026-03-24T20:20:00Z",
            requested_by="verification",
            trigger=ReviewTrigger.RECONCILIATION,
            summary="Linear record needs manual judgment.",
            presented_sections=("task_state", "evidence", "reconciliation"),
            allowed_outcomes=(ReviewOutcome.ACCEPT_COMPLETION, ReviewOutcome.KEEP_BLOCKED),
        )
        return HarnessEvaluationRequest(
            task_envelope=task,
            external_facts=build_canonical_fact_bundle(
                expected_code_context=build_expected_code_context(branch_name="codex/demo"),
                github_facts=build_github_completion_facts(branch_name="codex/demo", pull_request_number=300),
                linear_facts=build_linear_completion_facts(
                    record_found=False,
                    reasons=("Linear record is not yet resolvable.",),
                ),
            ),
            claimed_completion=True,
            acceptance_criteria_satisfied=True,
            runtime_facts=RuntimeVerificationFacts(executor_reported_success=True),
            review_request=review_request,
        )

    if case_name == "invalid_input":
        task = _base_task(status="completed")
        task["artifacts"]["completion_evidence"]["validated_artifact_ids"].append("artifact-missing")
        return HarnessEvaluationRequest(
            task_envelope=task,
            external_facts=_aligned_bundle(linear_state="completed"),
            claimed_completion=True,
            acceptance_criteria_satisfied=True,
            runtime_facts=RuntimeVerificationFacts(executor_reported_success=True),
        )

    raise ValueError(f"Unknown demo case {case_name!r}")


__all__ = [
    "build_demo_request",
    "list_demo_cases",
]
