"""Reusable runtime scenario builders for E2E tests and unattended dry runs."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from typing import Any, Callable

from modules.contracts.task_envelope_review import ReviewOutcome, ReviewTrigger
from modules.intake import create_task_envelope


DEFAULT_NOW = "2026-04-01T10:00:00Z"
DEFAULT_OWNER = "KnoxAnalytics"
DEFAULT_REPO = "HARNESS-DRYRUN"
DEFAULT_BRANCH = "codex/e2e-test"
DEFAULT_COMMIT = "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705"
DEFAULT_PR_NUMBER = 2


@dataclass(frozen=True)
class RuntimeScenarioDefinition:
    """Canonical runtime scenario definition used by tests and dry-run automation."""

    name: str
    description: str
    expected_outcome: dict[str, Any]
    build_evaluate_payload: Callable[[dict[str, Any]], dict[str, Any]]


def to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {key: to_jsonable(val) for key, val in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): to_jsonable(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    return value


def build_create_task_payload(task_id: str, *, title: str | None = None, now: str = DEFAULT_NOW) -> dict:
    task_envelope = create_task_envelope(
        {
            "id": task_id,
            "title": title or f"Runtime scenario {task_id}",
            "description": "Deterministic E2E runtime scenario task.",
            "origin": {
                "source_system": "openclaw",
                "source_type": "ingress_request",
                "source_id": f"req-{task_id}",
            },
            "acceptance_criteria": [
                {
                    "id": "ac-1",
                    "description": "Harness should evaluate the runtime scenario deterministically.",
                    "required": True,
                }
            ],
        },
        now=now,
    )
    return {"request": {"task_envelope": task_envelope}}


def _repository(*, owner: str = DEFAULT_OWNER, name: str = DEFAULT_REPO, external_id: str = "repo-dryrun-1") -> dict:
    return {
        "host": "github.com",
        "owner": owner,
        "name": name,
        "external_id": external_id,
    }


def _branch(
    *,
    name: str = DEFAULT_BRANCH,
    base_branch: str = "main",
    head_commit_sha: str = DEFAULT_COMMIT,
) -> dict:
    return {
        "name": name,
        "base_branch": base_branch,
        "head_commit_sha": head_commit_sha,
    }


def build_linked_artifacts(
    *,
    repository_owner: str = DEFAULT_OWNER,
    repository_name: str = DEFAULT_REPO,
    branch_name: str = DEFAULT_BRANCH,
    commit_sha: str = DEFAULT_COMMIT,
    pull_request_number: int = DEFAULT_PR_NUMBER,
    pr_artifact_id: str = "artifact-pr-1",
    commit_artifact_id: str = "artifact-commit-1",
    review_state: str | None = "approved",
    include_changed_files_on_pr: bool = False,
    changed_files: list[dict[str, Any]] | None = None,
    commit_verification_status: str = "verified",
    pr_verification_status: str = "verified",
) -> list[dict]:
    pr_changed_files = deepcopy(changed_files or []) if include_changed_files_on_pr else []
    return [
        {
            "id": pr_artifact_id,
            "type": "pull_request",
            "title": "HARNESS-DRYRUN PR",
            "description": None,
            "location": f"https://github.com/{repository_owner}/{repository_name}/pull/{pull_request_number}",
            "content_type": None,
            "external_id": f"PR-{pull_request_number}",
            "commit_sha": None,
            "pull_request_number": pull_request_number,
            "review_state": review_state,
            "provenance": {
                "source_system": "github",
                "source_type": "api",
                "source_id": f"pull/{pull_request_number}",
                "captured_by": "github-sync",
            },
            "verification_status": pr_verification_status,
            "repository": _repository(owner=repository_owner, name=repository_name),
            "branch": _branch(name=branch_name, head_commit_sha=commit_sha),
            "changed_files": pr_changed_files,
            "external_refs": [],
            "captured_at": "2026-04-01T10:01:00Z",
            "metadata": {
                "pull_request_state": "open",
                "pull_request_merged": False,
            },
        },
        {
            "id": commit_artifact_id,
            "type": "commit",
            "title": None,
            "description": None,
            "location": f"https://github.com/{repository_owner}/{repository_name}/commit/{commit_sha}",
            "content_type": None,
            "external_id": f"commit-{commit_sha}",
            "commit_sha": commit_sha,
            "pull_request_number": None,
            "review_state": None,
            "provenance": {
                "source_system": "github",
                "source_type": "api",
                "source_id": f"commit/{commit_sha}",
                "captured_by": "github-sync",
            },
            "verification_status": commit_verification_status,
            "repository": _repository(owner=repository_owner, name=repository_name),
            "branch": None,
            "changed_files": [],
            "external_refs": [],
            "captured_at": "2026-04-01T10:01:10Z",
            "metadata": {},
        },
    ]


def build_completion_evidence(
    *,
    policy: str = "required",
    status: str = "satisfied",
    required_artifact_types: list[str] | None = None,
    validated_artifact_ids: list[str] | None = None,
    validation_method: str = "external_reconciliation",
) -> dict:
    return {
        "policy": policy,
        "status": status,
        "required_artifact_types": list(required_artifact_types or ["pull_request", "commit"]),
        "validated_artifact_ids": list(validated_artifact_ids or ["artifact-pr-1", "artifact-commit-1"]),
        "validation_method": validation_method,
        "validated_at": "2026-04-01T10:02:00Z",
        "validator": {
            "source_system": "harness",
            "source_type": "verification",
            "source_id": "verification-e2e-1",
            "captured_by": "harness-api",
        },
    }


def build_expected_code_context(
    *,
    repository_owner: str = DEFAULT_OWNER,
    repository_name: str = DEFAULT_REPO,
    branch_name: str = DEFAULT_BRANCH,
) -> dict:
    return {
        "repository_host": "github.com",
        "repository_owner": repository_owner,
        "repository_name": repository_name,
        "branch_name": branch_name,
        "base_branch": "main",
    }


def build_github_facts(
    *,
    artifact_found: bool = True,
    repository_owner: str = DEFAULT_OWNER,
    repository_name: str = DEFAULT_REPO,
    branch_name: str = DEFAULT_BRANCH,
    commit_sha: str = DEFAULT_COMMIT,
    pull_request_number: int = DEFAULT_PR_NUMBER,
    review_state: str | None = "approved",
    changed_files_match: bool | None = True,
    changed_files: list[dict[str, Any]] | None = None,
    reasons: list[str] | None = None,
) -> dict:
    payload: dict[str, Any] = {
        "artifact_found": artifact_found,
        "reasons": list(reasons or []),
    }
    if not artifact_found:
        return payload

    payload.update(
        {
            "repository": _repository(owner=repository_owner, name=repository_name),
            "branch": _branch(name=branch_name, head_commit_sha=commit_sha),
            "commit": {"sha": commit_sha},
            "pull_request": {
                "number": pull_request_number,
                "url": f"https://github.com/{repository_owner}/{repository_name}/pull/{pull_request_number}",
                "state": "open",
                "review_state": review_state,
            },
            "changed_files": {
                "matches_expected_scope": changed_files_match,
                "files": deepcopy(changed_files or [{"path": "modules/api.py", "change_type": "modified"}]),
            },
        }
    )
    return payload


def build_linear_facts(
    *,
    record_found: bool = True,
    state: str = "completed",
    issue_id: str = "lin-e2e-1",
    issue_key: str = "HAR-2",
    workflow_name: str | None = None,
    workflow_state_type: str | None = None,
    reasons: list[str] | None = None,
) -> dict:
    payload: dict[str, Any] = {
        "record_found": record_found,
        "reasons": list(reasons or []),
    }
    if not record_found:
        return payload

    payload.update(
        {
            "issue_id": issue_id,
            "issue_key": issue_key,
            "state": state,
            "workflow": {
                "workflow_id": f"workflow-{state}",
                "workflow_name": workflow_name or state,
                "state_type": workflow_state_type or state,
            },
        }
    )
    return payload


def build_runtime_facts(
    *,
    executor_reported_success: bool = True,
    executor_reported_failure: bool = False,
    attempt_count: int = 1,
) -> dict:
    return {
        "executor_reported_success": executor_reported_success,
        "executor_reported_failure": executor_reported_failure,
        "attempt_count": attempt_count,
    }


def build_review_request(task_id: str) -> dict:
    return {
        "review_request_id": f"review-request-{task_id}",
        "task_id": task_id,
        "requested_at": "2026-04-01T10:03:00Z",
        "requested_by": "verification",
        "trigger": ReviewTrigger.RECONCILIATION.value,
        "summary": "Manual review is required before completion can be accepted.",
        "presented_sections": ["task_state", "evidence", "reconciliation"],
        "allowed_outcomes": [
            ReviewOutcome.ACCEPT_COMPLETION.value,
            ReviewOutcome.KEEP_BLOCKED.value,
            ReviewOutcome.MARK_FAILED.value,
        ],
        "metadata": {},
    }


def build_review_decision(task_id: str, *, target_status: str = "completed") -> dict:
    review_request = build_review_request(task_id)
    return {
        "request": deepcopy(review_request),
        "record": {
            "review_id": f"review-{task_id}-1",
            "review_request_id": review_request["review_request_id"],
            "task_id": task_id,
            "reviewer": {
                "reviewer_id": "reviewer-1",
                "reviewer_name": "Harness Reviewer",
                "authority_role": "operator",
            },
            "reviewed_at": "2026-04-01T10:04:00Z",
            "outcome": ReviewOutcome.ACCEPT_COMPLETION.value if target_status == "completed" else ReviewOutcome.KEEP_BLOCKED.value,
            "reasoning": "Manual review resolved the pending gate.",
            "authorized_target_status": target_status,
            "follow_up_action": "none",
            "basis_refs": [],
            "preserves_history": True,
            "metadata": {},
        },
        "recommended_target_status": target_status,
        "follow_up_action": "none",
    }


def build_evaluate_payload(
    task_envelope: dict,
    *,
    task_status: str | None = None,
    linked_artifacts: list[dict] | None = None,
    completion_evidence: dict | None = None,
    external_facts: dict | None = None,
    claimed_completion: bool = True,
    acceptance_criteria_satisfied: bool = True,
    runtime_facts: dict | None = None,
    review_request: dict | None = None,
    review_decision: dict | None = None,
) -> dict:
    request: dict[str, Any] = {
        "task_envelope": deepcopy(task_envelope),
        "claimed_completion": claimed_completion,
        "acceptance_criteria_satisfied": acceptance_criteria_satisfied,
        "runtime_facts": deepcopy(runtime_facts or build_runtime_facts()),
    }
    if task_status is not None:
        request["task_status"] = task_status
    if linked_artifacts is not None:
        request["linked_artifacts"] = deepcopy(linked_artifacts)
    if completion_evidence is not None:
        request["completion_evidence"] = deepcopy(completion_evidence)
    if external_facts is not None:
        request["external_facts"] = deepcopy(external_facts)
    if review_request is not None:
        request["review_request"] = deepcopy(review_request)
    if review_decision is not None:
        request["review_decision"] = deepcopy(review_decision)
    return {"request": request}


def build_reevaluate_payload(
    *,
    new_artifacts: list[dict] | None = None,
    completion_evidence: dict | None = None,
    external_facts: dict | None = None,
    claimed_completion: bool = True,
    acceptance_criteria_satisfied: bool = True,
    runtime_facts: dict | None = None,
    review_request: dict | None = None,
    review_decision: dict | None = None,
) -> dict:
    request: dict[str, Any] = {
        "claimed_completion": claimed_completion,
        "acceptance_criteria_satisfied": acceptance_criteria_satisfied,
        "runtime_facts": deepcopy(runtime_facts or build_runtime_facts()),
    }
    if new_artifacts is not None:
        request["new_artifacts"] = deepcopy(new_artifacts)
    if completion_evidence is not None:
        request["completion_evidence"] = deepcopy(completion_evidence)
    if external_facts is not None:
        request["external_facts"] = deepcopy(external_facts)
    if review_request is not None:
        request["review_request"] = deepcopy(review_request)
    if review_decision is not None:
        request["review_decision"] = deepcopy(review_decision)
    return {"request": request}


def build_happy_path_overlays(*, linear_state: str = "completed") -> dict:
    return {
        "task_status": None,
        "linked_artifacts": build_linked_artifacts(),
        "completion_evidence": build_completion_evidence(),
        "external_facts": {
            "expected_code_context": build_expected_code_context(),
            "github_facts": build_github_facts(),
            "linear_facts": build_linear_facts(state=linear_state, workflow_state_type="completed"),
        },
        "runtime_facts": build_runtime_facts(),
    }


def build_mismatch_overlays() -> dict:
    wrong_repo = "HARNESS-WRONG-TARGET"
    return {
        "linked_artifacts": build_linked_artifacts(repository_name=wrong_repo),
        "completion_evidence": build_completion_evidence(),
        "external_facts": {
            "expected_code_context": build_expected_code_context(repository_name=DEFAULT_REPO),
            "github_facts": build_github_facts(repository_name=wrong_repo),
            "linear_facts": build_linear_facts(state="completed", workflow_state_type="completed"),
        },
        "runtime_facts": build_runtime_facts(),
    }


def build_review_required_overlays(task_id: str) -> dict:
    return {
        "linked_artifacts": build_linked_artifacts(),
        "completion_evidence": build_completion_evidence(),
        "external_facts": {
            "expected_code_context": build_expected_code_context(),
            "github_facts": build_github_facts(),
            "linear_facts": build_linear_facts(
                record_found=False,
                reasons=["Linear record is not yet resolvable."],
            ),
        },
        "runtime_facts": build_runtime_facts(),
        "review_request": build_review_request(task_id),
    }


def build_top_level_overlay_happy_path_payload(task_envelope: dict, *, linear_state: str = "completed") -> dict:
    overlays = build_happy_path_overlays(linear_state=linear_state)
    return build_evaluate_payload(
        task_envelope,
        linked_artifacts=overlays["linked_artifacts"],
        completion_evidence=overlays["completion_evidence"],
        external_facts=overlays["external_facts"],
        runtime_facts=overlays["runtime_facts"],
    )


def build_happy_path_evaluate_payload(task_envelope: dict) -> dict:
    return build_top_level_overlay_happy_path_payload(task_envelope)


def build_mismatch_evaluate_payload(task_envelope: dict) -> dict:
    overlays = build_mismatch_overlays()
    return build_evaluate_payload(
        task_envelope,
        linked_artifacts=overlays["linked_artifacts"],
        completion_evidence=overlays["completion_evidence"],
        external_facts=overlays["external_facts"],
        runtime_facts=overlays["runtime_facts"],
    )


def build_review_required_payload(task_envelope: dict) -> dict:
    overlays = build_review_required_overlays(str(task_envelope["id"]))
    return build_evaluate_payload(
        task_envelope,
        linked_artifacts=overlays["linked_artifacts"],
        completion_evidence=overlays["completion_evidence"],
        external_facts=overlays["external_facts"],
        runtime_facts=overlays["runtime_facts"],
        review_request=overlays["review_request"],
    )


CANONICAL_UNATTENDED_SCENARIOS: tuple[RuntimeScenarioDefinition, ...] = (
    RuntimeScenarioDefinition(
        name="happy_path",
        description="Evidence-backed completion should be accepted.",
        expected_outcome={
            "accepted_completion": True,
            "final_status": "completed",
            "requires_review": False,
        },
        build_evaluate_payload=build_happy_path_evaluate_payload,
    ),
    RuntimeScenarioDefinition(
        name="mismatch",
        description="Wrong-target reconciliation mismatch should fail terminally.",
        expected_outcome={
            "accepted_completion": False,
            "final_status": "failed",
            "requires_review": False,
        },
        build_evaluate_payload=build_mismatch_evaluate_payload,
    ),
    RuntimeScenarioDefinition(
        name="review_required",
        description="Unresolved external truth should require manual review.",
        expected_outcome={
            "accepted_completion": False,
            "final_status": "in_review",
            "requires_review": True,
        },
        build_evaluate_payload=build_review_required_payload,
    ),
)


__all__ = [
    "CANONICAL_UNATTENDED_SCENARIOS",
    "DEFAULT_BRANCH",
    "DEFAULT_COMMIT",
    "DEFAULT_NOW",
    "DEFAULT_OWNER",
    "DEFAULT_PR_NUMBER",
    "DEFAULT_REPO",
    "RuntimeScenarioDefinition",
    "build_completion_evidence",
    "build_create_task_payload",
    "build_evaluate_payload",
    "build_expected_code_context",
    "build_github_facts",
    "build_happy_path_evaluate_payload",
    "build_happy_path_overlays",
    "build_linked_artifacts",
    "build_linear_facts",
    "build_mismatch_evaluate_payload",
    "build_mismatch_overlays",
    "build_reevaluate_payload",
    "build_review_decision",
    "build_review_request",
    "build_review_required_overlays",
    "build_review_required_payload",
    "build_runtime_facts",
    "build_top_level_overlay_happy_path_payload",
    "to_jsonable",
]
