"""Operational reconciliation handlers for post-execution failure recovery."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, Protocol
from urllib import error, parse, request


TaskEnvelope = dict[str, Any]


class ReconciliationFailureType(StrEnum):
    """Failure classes that may invoke a reconciliation handler."""

    MISSING_PR_AFTER_EXECUTION = "missing_pr_after_execution"


class ReconciliationAttemptStatus(StrEnum):
    """Operational reconciliation outcomes stored on the task."""

    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    RESOLVED = "resolved"
    FAILED = "failed"


class ReconciliationRuntimeError(ValueError):
    """Raised when reconciliation runtime inputs are malformed."""


@dataclass(frozen=True)
class ReconciliationCodeContext:
    """GitHub code context required to reconcile a missing pull request."""

    repository_host: str
    repository_owner: str
    repository_name: str
    branch_name: str
    base_branch: str | None
    commit_sha: str


@dataclass(frozen=True)
class ReconciliationRuntimeContext:
    """Context passed into one reconciliation handler."""

    task_envelope: TaskEnvelope
    failure_type: ReconciliationFailureType
    code_context: ReconciliationCodeContext


@dataclass(frozen=True)
class GitHubPullRequestRecord:
    """Normalized pull request facts returned from the GitHub API."""

    number: int
    url: str
    state: str | None = None
    review_state: str | None = None
    merged: bool = False
    repository_owner: str | None = None
    repository_name: str | None = None
    head_branch: str | None = None
    head_sha: str | None = None
    base_branch: str | None = None
    title: str | None = None
    body: str | None = None


@dataclass(frozen=True)
class MissingPrMatchPolicy:
    """Validation policy for matching a pull request to the current execution."""

    allow_open_pr_match: bool = True
    allow_closed_pr_match: bool = False
    require_head_sha_match: bool = True
    require_exact_branch_match: bool = True
    allow_commit_association_match: bool = True
    escalate_on_ambiguous_match: bool = True
    require_task_linkage: bool = False


@dataclass(frozen=True)
class ReconciliationHandlerResult:
    """Structured result returned by a reconciliation handler."""

    task_envelope: TaskEnvelope
    status: ReconciliationAttemptStatus
    attempt: dict[str, Any]
    pull_request: GitHubPullRequestRecord | None = None
    error: str | None = None


class GitHubPullRequestGateway(Protocol):
    """Boundary for GitHub-backed PR lookup and creation."""

    def branch_exists(self, *, owner: str, repo: str, branch_name: str) -> bool: ...

    def commit_exists(self, *, owner: str, repo: str, commit_sha: str) -> bool: ...

    def default_branch(self, *, owner: str, repo: str) -> str | None: ...

    def find_pull_requests_by_branch(
        self,
        *,
        owner: str,
        repo: str,
        branch_name: str,
    ) -> tuple[GitHubPullRequestRecord, ...]: ...

    def find_pull_requests_by_commit(
        self,
        *,
        owner: str,
        repo: str,
        commit_sha: str,
    ) -> tuple[GitHubPullRequestRecord, ...]: ...

    def create_pull_request(
        self,
        *,
        owner: str,
        repo: str,
        title: str,
        body: str,
        head: str,
        base: str,
    ) -> GitHubPullRequestRecord: ...


def default_reconciliation_state() -> dict[str, Any]:
    """Return the canonical default reconciliation state."""

    return {
        "status": ReconciliationAttemptStatus.NOT_REQUIRED.value,
        "active_failure_type": None,
        "attempts": [],
        "last_attempt_id": None,
        "last_pr_url": None,
        "last_error": None,
        "resolved_at": None,
        "failed_at": None,
    }


def ensure_reconciliation_state(task_envelope: TaskEnvelope) -> TaskEnvelope:
    """Ensure a task carries the canonical reconciliation object."""

    updated = deepcopy(task_envelope)
    reconciliation = updated.get("reconciliation")
    if not isinstance(reconciliation, dict):
        updated["reconciliation"] = default_reconciliation_state()
        return updated

    merged = default_reconciliation_state()
    merged.update(reconciliation)
    if not isinstance(merged.get("attempts"), list):
        merged["attempts"] = []
    updated["reconciliation"] = merged
    return updated


def task_has_pull_request_artifact(task_envelope: TaskEnvelope) -> bool:
    """Return whether the task already carries a pull request artifact."""

    artifacts = ((task_envelope.get("artifacts") or {}).get("items") or [])
    if not isinstance(artifacts, list):
        return False
    return any(isinstance(item, dict) and item.get("type") == "pull_request" for item in artifacts)


def _normalize_sha(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _parse_github_location(location: Any) -> tuple[str, str, str, str] | None:
    if not isinstance(location, str) or not location.strip():
        return None
    parsed = parse.urlparse(location)
    if parsed.netloc != "github.com":
        return None
    segments = [segment for segment in parsed.path.split("/") if segment]
    if len(segments) < 4:
        return None
    owner, repo, kind = segments[0], segments[1], segments[2]
    identifier = "/".join(segments[3:])
    return owner, repo, kind, identifier


def _repository_from_artifact(artifact: dict[str, Any]) -> tuple[str, str, str] | None:
    repository = artifact.get("repository")
    if not isinstance(repository, dict):
        return None
    host = str(repository.get("host") or "").strip() or "github.com"
    owner = str(repository.get("owner") or "").strip()
    name = str(repository.get("name") or "").strip()
    if not owner or not name:
        return None
    return host, owner, name


def _context_from_artifacts(task_envelope: TaskEnvelope) -> ReconciliationCodeContext | None:
    artifacts = ((task_envelope.get("artifacts") or {}).get("items") or [])
    if not isinstance(artifacts, list):
        return None

    repository_host: str | None = None
    repository_owner: str | None = None
    repository_name: str | None = None
    branch_name: str | None = None
    base_branch: str | None = None
    commit_sha: str | None = None

    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        repository = _repository_from_artifact(artifact)
        if repository is not None:
            repository_host, repository_owner, repository_name = repository
        branch = artifact.get("branch")
        if isinstance(branch, dict):
            branch_name = branch_name or _normalize_sha(branch.get("name"))
            base_branch = base_branch or _normalize_sha(branch.get("base_branch"))
            commit_sha = commit_sha or _normalize_sha(branch.get("head_commit_sha"))
        commit_sha = commit_sha or _normalize_sha(artifact.get("commit_sha"))
        location = _parse_github_location(artifact.get("location"))
        if location and location[2] in {"pull", "commit", "tree"}:
            repository_owner = repository_owner or location[0]
            repository_name = repository_name or location[1]
            repository_host = repository_host or "github.com"
            if location[2] == "commit":
                commit_sha = commit_sha or _normalize_sha(location[3])
            if location[2] == "tree":
                branch_name = branch_name or _normalize_sha(location[3])

    if not repository_owner or not repository_name or not branch_name or not commit_sha:
        return None

    return ReconciliationCodeContext(
        repository_host=repository_host or "github.com",
        repository_owner=repository_owner,
        repository_name=repository_name,
        branch_name=branch_name,
        base_branch=base_branch,
        commit_sha=commit_sha,
    )


def _context_from_external_facts(external_facts: Any) -> ReconciliationCodeContext | None:
    if not isinstance(external_facts, dict):
        return None

    expected_code_context = external_facts.get("expected_code_context")
    github_facts = external_facts.get("github_facts")

    repository_host = None
    repository_owner = None
    repository_name = None
    branch_name = None
    base_branch = None
    commit_sha = None

    if isinstance(expected_code_context, dict):
        repository_host = _normalize_sha(expected_code_context.get("repository_host")) or "github.com"
        repository_owner = _normalize_sha(expected_code_context.get("repository_owner"))
        repository_name = _normalize_sha(expected_code_context.get("repository_name"))
        branch_name = _normalize_sha(expected_code_context.get("branch_name"))
        base_branch = _normalize_sha(expected_code_context.get("base_branch"))

    if isinstance(github_facts, dict):
        repository = github_facts.get("repository")
        if isinstance(repository, dict):
            repository_host = repository_host or _normalize_sha(repository.get("host")) or "github.com"
            repository_owner = repository_owner or _normalize_sha(repository.get("owner"))
            repository_name = repository_name or _normalize_sha(repository.get("name"))
        branch = github_facts.get("branch")
        if isinstance(branch, dict):
            branch_name = branch_name or _normalize_sha(branch.get("name"))
            base_branch = base_branch or _normalize_sha(branch.get("base_branch"))
            commit_sha = commit_sha or _normalize_sha(branch.get("head_commit_sha"))
        commit = github_facts.get("commit")
        if isinstance(commit, dict):
            commit_sha = commit_sha or _normalize_sha(commit.get("sha"))

    if not repository_owner or not repository_name or not branch_name or not commit_sha:
        return None

    return ReconciliationCodeContext(
        repository_host=repository_host or "github.com",
        repository_owner=repository_owner,
        repository_name=repository_name,
        branch_name=branch_name,
        base_branch=base_branch,
        commit_sha=commit_sha,
    )


def _context_from_execution_attempt(task_envelope: TaskEnvelope) -> ReconciliationCodeContext | None:
    execution_metadata = ((task_envelope.get("observability") or {}).get("execution_metadata") or {})
    attempts = execution_metadata.get("execution_attempts") or []
    if not isinstance(attempts, list):
        return None

    latest_attempt = next((attempt for attempt in reversed(attempts) if isinstance(attempt, dict)), None)
    if latest_attempt is None:
        return None

    repository_host: str | None = None
    repository_owner: str | None = None
    repository_name: str | None = None
    branch_name: str | None = None
    base_branch: str | None = None
    commit_sha: str | None = None

    for artifact_reference in latest_attempt.get("artifact_references") or []:
        if not isinstance(artifact_reference, dict):
            continue
        metadata = artifact_reference.get("metadata")
        if isinstance(metadata, dict):
            repository_host = repository_host or _normalize_sha(metadata.get("repository_host")) or "github.com"
            repository_owner = repository_owner or _normalize_sha(metadata.get("repository_owner"))
            repository_name = repository_name or _normalize_sha(metadata.get("repository_name"))
            branch_name = branch_name or _normalize_sha(metadata.get("branch_name"))
            base_branch = base_branch or _normalize_sha(metadata.get("base_branch"))
            commit_sha = commit_sha or _normalize_sha(metadata.get("commit_sha"))
        commit_sha = commit_sha or _normalize_sha(artifact_reference.get("commit_sha"))
        location = _parse_github_location(artifact_reference.get("location"))
        if location is not None:
            repository_host = repository_host or "github.com"
            repository_owner = repository_owner or location[0]
            repository_name = repository_name or location[1]
            if location[2] == "tree":
                branch_name = branch_name or _normalize_sha(location[3])
            elif location[2] == "commit":
                commit_sha = commit_sha or _normalize_sha(location[3])
            elif location[2] == "pull":
                metadata = metadata if isinstance(metadata, dict) else {}
                branch_name = branch_name or _normalize_sha(metadata.get("branch_name"))

    if not repository_owner or not repository_name or not branch_name or not commit_sha:
        return None

    return ReconciliationCodeContext(
        repository_host=repository_host or "github.com",
        repository_owner=repository_owner,
        repository_name=repository_name,
        branch_name=branch_name,
        base_branch=base_branch,
        commit_sha=commit_sha,
    )


def resolve_code_context(
    task_envelope: TaskEnvelope,
    *,
    external_facts: Any = None,
) -> ReconciliationCodeContext:
    """Resolve repository, branch, base branch, and commit context for PR reconciliation."""

    for resolver in (
        lambda: _context_from_external_facts(external_facts),
        lambda: _context_from_artifacts(task_envelope),
        lambda: _context_from_execution_attempt(task_envelope),
    ):
        context = resolver()
        if context is not None:
            if context.repository_host != "github.com":
                raise ReconciliationRuntimeError("missing_pr_after_execution currently supports github.com repositories only")
            return context

    raise ReconciliationRuntimeError(
        "Unable to resolve repository, branch, and commit context for missing_pr_after_execution reconciliation"
    )


def _reconciliation_attempt_id(task_envelope: TaskEnvelope) -> str:
    reconciliation = (task_envelope.get("reconciliation") or {})
    attempts = reconciliation.get("attempts") or []
    if not isinstance(attempts, list):
        attempts = []
    return f"reconciliation-attempt-{len(attempts) + 1}"


def _policy_details(policy: MissingPrMatchPolicy) -> dict[str, Any]:
    return asdict(policy)


def _candidate_key(pull_request: GitHubPullRequestRecord) -> str:
    return str(pull_request.number)


def _normalized_text(value: str | None) -> str:
    return value.casefold() if isinstance(value, str) else ""


def _task_linkage_details(task_envelope: TaskEnvelope, pull_request: GitHubPullRequestRecord) -> dict[str, Any]:
    task_id = str(task_envelope.get("id") or "").strip()
    task_title = str(task_envelope.get("title") or "").strip()
    title = _normalized_text(pull_request.title)
    body = _normalized_text(pull_request.body)

    task_id_present = bool(task_id) and (task_id.casefold() in title or task_id.casefold() in body)
    task_title_present = bool(task_title) and (task_title.casefold() in title or task_title.casefold() in body)

    return {
        "task_id_present": task_id_present,
        "task_title_present": task_title_present,
        "linked": task_id_present or task_title_present,
    }


def _pull_request_artifact(
    *,
    task_envelope: TaskEnvelope,
    code_context: ReconciliationCodeContext,
    pull_request: GitHubPullRequestRecord,
    captured_at: str,
) -> dict[str, Any]:
    return {
        "id": f"artifact-pr-{pull_request.number}",
        "type": "pull_request",
        "title": f"{task_envelope.get('title') or task_envelope.get('id')} PR",
        "description": "Attached by Harness reconciliation after execution completed without a pull request artifact.",
        "location": pull_request.url,
        "content_type": None,
        "external_id": f"PR-{pull_request.number}",
        "commit_sha": None,
        "pull_request_number": pull_request.number,
        "review_state": pull_request.review_state,
        "provenance": {
            "source_system": "github",
            "source_type": "api",
            "source_id": f"pull/{pull_request.number}",
            "captured_by": "reconciliation_handler",
        },
        "verification_status": "verified",
        "repository": {
            "host": code_context.repository_host,
            "owner": code_context.repository_owner,
            "name": code_context.repository_name,
            "external_id": None,
        },
        "branch": {
            "name": code_context.branch_name,
            "base_branch": code_context.base_branch,
            "head_commit_sha": code_context.commit_sha,
        },
        "changed_files": [],
        "external_refs": [],
        "captured_at": captured_at,
        "metadata": {
            "attached_by": "missing_pr_after_execution",
            "pull_request_state": pull_request.state,
        },
    }


def _attach_pull_request_artifact(
    task_envelope: TaskEnvelope,
    *,
    code_context: ReconciliationCodeContext,
    pull_request: GitHubPullRequestRecord,
    captured_at: str,
) -> TaskEnvelope:
    updated = deepcopy(task_envelope)
    artifacts = updated.setdefault("artifacts", {}).setdefault("items", [])
    if not isinstance(artifacts, list):
        raise ReconciliationRuntimeError("task.artifacts.items must be a list")

    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        if artifact.get("type") != "pull_request":
            continue
        if artifact.get("pull_request_number") == pull_request.number or artifact.get("location") == pull_request.url:
            return updated

    artifacts.append(
        _pull_request_artifact(
            task_envelope=updated,
            code_context=code_context,
            pull_request=pull_request,
            captured_at=captured_at,
        )
    )
    return updated


def _record_reconciliation_attempt(
    task_envelope: TaskEnvelope,
    *,
    attempt: dict[str, Any],
    status: ReconciliationAttemptStatus,
    failure_type: ReconciliationFailureType,
    completed_at: str,
    pull_request_url: str | None = None,
    error_message: str | None = None,
) -> TaskEnvelope:
    updated = ensure_reconciliation_state(task_envelope)
    reconciliation = updated["reconciliation"]
    attempts = reconciliation.get("attempts")
    if not isinstance(attempts, list):
        attempts = []
        reconciliation["attempts"] = attempts
    attempts.append(deepcopy(attempt))
    reconciliation["status"] = status.value
    reconciliation["active_failure_type"] = None if status == ReconciliationAttemptStatus.RESOLVED else failure_type.value
    reconciliation["last_attempt_id"] = attempt.get("attempt_id")
    reconciliation["last_pr_url"] = pull_request_url
    reconciliation["last_error"] = error_message
    reconciliation["resolved_at"] = completed_at if status == ReconciliationAttemptStatus.RESOLVED else None
    reconciliation["failed_at"] = completed_at if status == ReconciliationAttemptStatus.FAILED else None
    updated["timestamps"]["updated_at"] = completed_at
    return updated


class MissingPrAfterExecutionHandler:
    """Reconcile a successful execution attempt that lacks a pull request artifact."""

    def __init__(
        self,
        *,
        github: GitHubPullRequestGateway,
        policy: MissingPrMatchPolicy | None = None,
    ) -> None:
        self.github = github
        self.policy = policy or MissingPrMatchPolicy()

    def _candidate_details(
        self,
        pull_request: GitHubPullRequestRecord,
        *,
        sources: set[str],
        accepted: bool,
        reasons: list[str],
        matched_by: list[str],
        task_linkage: dict[str, Any],
        code_context: ReconciliationCodeContext,
    ) -> dict[str, Any]:
        repository_match = (
            pull_request.repository_owner == code_context.repository_owner
            and pull_request.repository_name == code_context.repository_name
        )
        branch_match = pull_request.head_branch == code_context.branch_name
        head_sha_match = pull_request.head_sha == code_context.commit_sha
        commit_association_match = "commit" in sources
        state = (pull_request.state or "").lower() or None
        return {
            "number": pull_request.number,
            "url": pull_request.url,
            "state": pull_request.state,
            "merged": pull_request.merged,
            "review_state": pull_request.review_state,
            "title": pull_request.title,
            "repository": {
                "owner": pull_request.repository_owner,
                "name": pull_request.repository_name,
            },
            "head": {
                "branch": pull_request.head_branch,
                "sha": pull_request.head_sha,
            },
            "base_branch": pull_request.base_branch,
            "lookup_sources": sorted(sources),
            "validation": {
                "accepted": accepted,
                "matched_by": matched_by,
                "reasons": reasons,
                "signals": {
                    "repository_match": repository_match,
                    "branch_match": branch_match,
                    "state": state,
                    "state_acceptable": accepted or not any(
                        reason in {"closed_pr_not_allowed", "merged_pr_not_allowed", "unknown_pr_state"}
                        for reason in reasons
                    ),
                    "head_sha_match": head_sha_match,
                    "commit_association_match": commit_association_match,
                    "task_linkage": task_linkage,
                },
            },
        }

    def _validate_candidate(
        self,
        pull_request: GitHubPullRequestRecord,
        *,
        code_context: ReconciliationCodeContext,
        task_envelope: TaskEnvelope,
        sources: set[str],
    ) -> tuple[bool, list[str], list[str], dict[str, Any]]:
        reasons: list[str] = []
        matched_by: list[str] = []

        if pull_request.repository_owner != code_context.repository_owner or pull_request.repository_name != code_context.repository_name:
            reasons.append("repository_mismatch")

        if self.policy.require_exact_branch_match:
            if not pull_request.head_branch:
                reasons.append("missing_head_branch")
            elif pull_request.head_branch != code_context.branch_name:
                reasons.append("branch_mismatch")

        state = (pull_request.state or "").strip().lower()
        if not state:
            reasons.append("unknown_pr_state")
        elif state == "open":
            if not self.policy.allow_open_pr_match:
                reasons.append("open_pr_not_allowed")
        elif state == "closed":
            if pull_request.merged:
                reasons.append("merged_pr_not_allowed")
            elif not self.policy.allow_closed_pr_match:
                reasons.append("closed_pr_not_allowed")
        else:
            reasons.append("unknown_pr_state")

        head_sha_match = bool(pull_request.head_sha) and pull_request.head_sha == code_context.commit_sha
        commit_association_match = self.policy.allow_commit_association_match and "commit" in sources

        if self.policy.require_head_sha_match:
            if head_sha_match:
                matched_by.append("head_sha_match")
            elif commit_association_match:
                matched_by.append("commit_association_match")
            else:
                reasons.append("head_sha_mismatch" if pull_request.head_sha else "missing_head_sha")
        elif commit_association_match:
            matched_by.append("commit_association_match")

        task_linkage = _task_linkage_details(task_envelope, pull_request)
        if self.policy.require_task_linkage and not task_linkage["linked"]:
            reasons.append("task_linkage_missing")
        elif task_linkage["linked"]:
            matched_by.append("task_linkage")

        return not reasons, reasons, matched_by, task_linkage

    def _lookup_candidates(
        self,
        *,
        code_context: ReconciliationCodeContext,
        attempt: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        attempt["details"]["pull_request_lookup"]["searched_by_branch"] = True
        branch_candidates = self.github.find_pull_requests_by_branch(
            owner=code_context.repository_owner,
            repo=code_context.repository_name,
            branch_name=code_context.branch_name,
        )
        attempt["details"]["pull_request_lookup"]["searched_by_commit"] = True
        commit_candidates = self.github.find_pull_requests_by_commit(
            owner=code_context.repository_owner,
            repo=code_context.repository_name,
            commit_sha=code_context.commit_sha,
        )

        candidates: dict[str, dict[str, Any]] = {}
        for source, records in (("branch", branch_candidates), ("commit", commit_candidates)):
            for record in records:
                key = _candidate_key(record)
                entry = candidates.setdefault(key, {"pull_request": record, "sources": set()})
                entry["sources"].add(source)
                entry["pull_request"] = record
        return candidates

    def _select_existing_pull_request(
        self,
        *,
        task_envelope: TaskEnvelope,
        code_context: ReconciliationCodeContext,
        attempt: dict[str, Any],
    ) -> GitHubPullRequestRecord | None:
        candidates = self._lookup_candidates(code_context=code_context, attempt=attempt)
        candidate_details: list[dict[str, Any]] = []
        valid_candidates: list[GitHubPullRequestRecord] = []

        for key in sorted(candidates.keys(), key=lambda item: int(item)):
            candidate = candidates[key]["pull_request"]
            sources = candidates[key]["sources"]
            accepted, reasons, matched_by, task_linkage = self._validate_candidate(
                candidate,
                code_context=code_context,
                task_envelope=task_envelope,
                sources=sources,
            )
            candidate_details.append(
                self._candidate_details(
                    candidate,
                    sources=sources,
                    accepted=accepted,
                    reasons=reasons,
                    matched_by=matched_by,
                    task_linkage=task_linkage,
                    code_context=code_context,
                )
            )
            if accepted:
                valid_candidates.append(candidate)

        attempt["details"]["pull_request_candidates"] = candidate_details
        attempt["details"]["pull_request_lookup"]["candidate_count"] = len(candidate_details)
        attempt["details"]["pull_request_lookup"]["valid_candidate_count"] = len(valid_candidates)
        attempt["details"]["pull_request_lookup"]["found"] = bool(candidate_details)

        if len(valid_candidates) == 1:
            selected = valid_candidates[0]
            attempt["details"]["pull_request_lookup"]["source"] = "existing"
            attempt["details"]["pull_request_lookup"]["number"] = selected.number
            attempt["details"]["pull_request_lookup"]["url"] = selected.url
            attempt["details"]["final_decision"] = {
                "result": "attached_existing",
                "reason": "exactly_one_valid_current_run_candidate",
            }
            return selected

        if len(valid_candidates) > 1:
            attempt["details"]["pull_request_lookup"]["ambiguous"] = True
            attempt["details"]["final_decision"] = {
                "result": "ambiguous_existing_candidates",
                "reason": "multiple_valid_current_run_candidates",
            }
            if self.policy.escalate_on_ambiguous_match:
                raise ReconciliationRuntimeError(
                    "Ambiguous pull request candidates matched the current execution context"
                )
            return None

        attempt["details"]["final_decision"] = {
            "result": "no_valid_existing_candidate",
            "reason": "all_candidates_rejected_or_absent",
        }
        return None

    def handle(self, context: ReconciliationRuntimeContext, *, started_at: str) -> ReconciliationHandlerResult:
        attempt_id = _reconciliation_attempt_id(context.task_envelope)
        code_context = context.code_context
        completed_at = started_at
        attempt = {
            "attempt_id": attempt_id,
            "failure_type": context.failure_type.value,
            "handler_key": context.failure_type.value,
            "status": ReconciliationAttemptStatus.PENDING.value,
            "started_at": started_at,
            "completed_at": None,
            "details": {
                "repository": {
                    "host": code_context.repository_host,
                    "owner": code_context.repository_owner,
                    "name": code_context.repository_name,
                },
                "branch_name": code_context.branch_name,
                "base_branch": code_context.base_branch,
                "commit_sha": code_context.commit_sha,
                "policy": _policy_details(self.policy),
                "branch_exists": None,
                "commit_exists": None,
                "pull_request_lookup": {
                    "searched_by_branch": False,
                    "searched_by_commit": False,
                    "found": False,
                    "source": None,
                    "number": None,
                    "url": None,
                    "candidate_count": 0,
                    "valid_candidate_count": 0,
                    "ambiguous": False,
                },
                "pull_request_candidates": [],
                "created_pull_request": False,
                "final_decision": {
                    "result": None,
                    "reason": None,
                },
                "error": None,
            },
        }

        try:
            if not code_context.commit_sha.strip():
                raise ReconciliationRuntimeError("Commit SHA is required for missing_pr_after_execution reconciliation")

            branch_exists = self.github.branch_exists(
                owner=code_context.repository_owner,
                repo=code_context.repository_name,
                branch_name=code_context.branch_name,
            )
            attempt["details"]["branch_exists"] = branch_exists
            if not branch_exists:
                raise ReconciliationRuntimeError(
                    f"GitHub branch {code_context.branch_name!r} was not found in "
                    f"{code_context.repository_owner}/{code_context.repository_name}"
                )

            commit_exists = self.github.commit_exists(
                owner=code_context.repository_owner,
                repo=code_context.repository_name,
                commit_sha=code_context.commit_sha,
            )
            attempt["details"]["commit_exists"] = commit_exists
            if not commit_exists:
                raise ReconciliationRuntimeError(
                    f"GitHub commit {code_context.commit_sha!r} was not found in "
                    f"{code_context.repository_owner}/{code_context.repository_name}"
                )

            pull_request = self._select_existing_pull_request(
                task_envelope=context.task_envelope,
                code_context=code_context,
                attempt=attempt,
            )

            if pull_request is None:
                base_branch = code_context.base_branch or self.github.default_branch(
                    owner=code_context.repository_owner,
                    repo=code_context.repository_name,
                )
                if not base_branch:
                    raise ReconciliationRuntimeError(
                        f"Unable to resolve a base branch for {code_context.repository_owner}/{code_context.repository_name}"
                    )
                pull_request = self.github.create_pull_request(
                    owner=code_context.repository_owner,
                    repo=code_context.repository_name,
                    title=str(context.task_envelope.get("title") or context.task_envelope.get("id")),
                    body=(
                        f"Harness reconciliation created this pull request for task "
                        f"{context.task_envelope.get('id')} after execution completed without a PR artifact."
                    ),
                    head=code_context.branch_name,
                    base=base_branch,
                )
                source = "created"
                attempt["details"]["created_pull_request"] = True
                created_sources = {"created"}
                created_accepted, created_reasons, created_matched_by, created_task_linkage = self._validate_candidate(
                    pull_request,
                    code_context=code_context,
                    task_envelope=context.task_envelope,
                    sources=created_sources,
                )
                attempt["details"]["pull_request_candidates"].append(
                    self._candidate_details(
                        pull_request,
                        sources=created_sources,
                        accepted=created_accepted,
                        reasons=created_reasons,
                        matched_by=created_matched_by,
                        task_linkage=created_task_linkage,
                        code_context=code_context,
                    )
                )
                attempt["details"]["pull_request_lookup"]["candidate_count"] += 1
                if created_accepted:
                    attempt["details"]["pull_request_lookup"]["valid_candidate_count"] += 1
                    attempt["details"]["final_decision"] = {
                        "result": "created_new",
                        "reason": "no_valid_existing_candidate",
                    }
                else:
                    attempt["details"]["final_decision"] = {
                        "result": "created_candidate_rejected",
                        "reason": "created_pull_request_failed_validation",
                    }
                    raise ReconciliationRuntimeError(
                        "Created pull request did not satisfy current-run validation policy"
                    )
                code_context = ReconciliationCodeContext(
                    repository_host=code_context.repository_host,
                    repository_owner=code_context.repository_owner,
                    repository_name=code_context.repository_name,
                    branch_name=code_context.branch_name,
                    base_branch=base_branch,
                    commit_sha=code_context.commit_sha,
                )
            else:
                source = "existing"

            attempt["details"]["pull_request_lookup"]["found"] = True
            attempt["details"]["pull_request_lookup"]["source"] = source
            attempt["details"]["pull_request_lookup"]["number"] = pull_request.number
            attempt["details"]["pull_request_lookup"]["url"] = pull_request.url
            completed_at = _iso_now()
            attempt["status"] = ReconciliationAttemptStatus.RESOLVED.value
            attempt["completed_at"] = completed_at

            updated_task = _attach_pull_request_artifact(
                context.task_envelope,
                code_context=code_context,
                pull_request=pull_request,
                captured_at=completed_at,
            )
            updated_task = _record_reconciliation_attempt(
                updated_task,
                attempt=attempt,
                status=ReconciliationAttemptStatus.RESOLVED,
                failure_type=context.failure_type,
                completed_at=completed_at,
                pull_request_url=pull_request.url,
                error_message=None,
            )
            return ReconciliationHandlerResult(
                task_envelope=updated_task,
                status=ReconciliationAttemptStatus.RESOLVED,
                attempt=attempt,
                pull_request=pull_request,
                error=None,
            )
        except Exception as error_message:
            completed_at = _iso_now()
            attempt["status"] = ReconciliationAttemptStatus.FAILED.value
            attempt["completed_at"] = completed_at
            attempt["details"]["error"] = str(error_message)
            updated_task = _record_reconciliation_attempt(
                context.task_envelope,
                attempt=attempt,
                status=ReconciliationAttemptStatus.FAILED,
                failure_type=context.failure_type,
                completed_at=completed_at,
                pull_request_url=None,
                error_message=str(error_message),
            )
            return ReconciliationHandlerResult(
                task_envelope=updated_task,
                status=ReconciliationAttemptStatus.FAILED,
                attempt=attempt,
                pull_request=None,
                error=str(error_message),
            )


class ReconciliationHandlerRegistry:
    """Pluggable registry for operational reconciliation handlers."""

    def __init__(self, handlers: dict[ReconciliationFailureType, Any] | None = None) -> None:
        self._handlers = handlers or {}

    def register(self, failure_type: ReconciliationFailureType, handler: Any) -> None:
        self._handlers[failure_type] = handler

    def get(self, failure_type: ReconciliationFailureType) -> Any:
        handler = self._handlers.get(failure_type)
        if handler is None:
            raise ReconciliationRuntimeError(f"No reconciliation handler registered for {failure_type.value}")
        return handler

    def handle(
        self,
        failure_type: ReconciliationFailureType,
        *,
        task_envelope: TaskEnvelope,
        external_facts: Any = None,
        started_at: str,
    ) -> ReconciliationHandlerResult:
        context = ReconciliationRuntimeContext(
            task_envelope=ensure_reconciliation_state(task_envelope),
            failure_type=failure_type,
            code_context=resolve_code_context(task_envelope, external_facts=external_facts),
        )
        handler = self.get(failure_type)
        return handler.handle(context, started_at=started_at)


class GitHubRestPullRequestGateway:
    """GitHub REST API-backed pull request lookup and creation."""

    def __init__(self, *, token: str | None = None, timeout_seconds: float = 10.0) -> None:
        self._token = token or os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
        self._timeout_seconds = timeout_seconds

    def _request_json(
        self,
        path: str,
        *,
        method: str = "GET",
        body: dict[str, Any] | None = None,
    ) -> Any:
        url = f"https://api.github.com{path}"
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = request.Request(url=url, method=method, data=data, headers=headers)
        try:
            with request.urlopen(req, timeout=self._timeout_seconds) as response:
                payload = response.read().decode("utf-8")
                if not payload:
                    return {}
                return json.loads(payload)
        except error.HTTPError as http_error:
            response_body = http_error.read().decode("utf-8", errors="replace")
            if http_error.code == 404:
                return None
            raise ReconciliationRuntimeError(
                f"GitHub API request failed for {path}: HTTP {http_error.code} {response_body}".strip()
            ) from http_error
        except error.URLError as url_error:
            raise ReconciliationRuntimeError(
                f"GitHub API request failed for {path}: {url_error.reason}"
            ) from url_error

    @staticmethod
    def _normalize_pull_request(payload: dict[str, Any]) -> GitHubPullRequestRecord:
        number = payload.get("number")
        url = payload.get("html_url")
        if not isinstance(number, int) or not isinstance(url, str) or not url.strip():
            raise ReconciliationRuntimeError("GitHub pull request response was missing number or html_url")
        head = payload.get("head") if isinstance(payload.get("head"), dict) else {}
        base = payload.get("base") if isinstance(payload.get("base"), dict) else {}
        head_repo = head.get("repo") if isinstance(head.get("repo"), dict) else {}
        head_owner = head_repo.get("owner") if isinstance(head_repo.get("owner"), dict) else {}
        return GitHubPullRequestRecord(
            number=number,
            url=url,
            state=payload.get("state") if isinstance(payload.get("state"), str) else None,
            review_state=payload.get("review_decision") if isinstance(payload.get("review_decision"), str) else None,
            merged=bool(payload.get("merged")) or payload.get("merged_at") is not None,
            repository_owner=head_owner.get("login") if isinstance(head_owner.get("login"), str) else None,
            repository_name=head_repo.get("name") if isinstance(head_repo.get("name"), str) else None,
            head_branch=head.get("ref") if isinstance(head.get("ref"), str) else None,
            head_sha=head.get("sha") if isinstance(head.get("sha"), str) else None,
            base_branch=base.get("ref") if isinstance(base.get("ref"), str) else None,
            title=payload.get("title") if isinstance(payload.get("title"), str) else None,
            body=payload.get("body") if isinstance(payload.get("body"), str) else None,
        )

    def branch_exists(self, *, owner: str, repo: str, branch_name: str) -> bool:
        safe_branch = parse.quote(branch_name, safe="")
        return self._request_json(f"/repos/{owner}/{repo}/branches/{safe_branch}") is not None

    def commit_exists(self, *, owner: str, repo: str, commit_sha: str) -> bool:
        return self._request_json(f"/repos/{owner}/{repo}/commits/{commit_sha}") is not None

    def default_branch(self, *, owner: str, repo: str) -> str | None:
        response = self._request_json(f"/repos/{owner}/{repo}")
        if not isinstance(response, dict):
            return None
        default_branch = response.get("default_branch")
        return default_branch if isinstance(default_branch, str) and default_branch.strip() else None

    def find_pull_requests_by_branch(
        self,
        *,
        owner: str,
        repo: str,
        branch_name: str,
    ) -> tuple[GitHubPullRequestRecord, ...]:
        safe_head = parse.quote(f"{owner}:{branch_name}", safe="")
        response = self._request_json(f"/repos/{owner}/{repo}/pulls?state=all&head={safe_head}")
        if not isinstance(response, list) or not response:
            return ()
        return tuple(self._normalize_pull_request(item) for item in response if isinstance(item, dict))

    def find_pull_requests_by_commit(
        self,
        *,
        owner: str,
        repo: str,
        commit_sha: str,
    ) -> tuple[GitHubPullRequestRecord, ...]:
        response = self._request_json(f"/repos/{owner}/{repo}/commits/{commit_sha}/pulls")
        if not isinstance(response, list) or not response:
            return ()
        return tuple(self._normalize_pull_request(item) for item in response if isinstance(item, dict))

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
        response = self._request_json(
            f"/repos/{owner}/{repo}/pulls",
            method="POST",
            body={
                "title": title,
                "body": body,
                "head": head,
                "base": base,
            },
        )
        if not isinstance(response, dict):
            raise ReconciliationRuntimeError("GitHub create pull request response was malformed")
        return self._normalize_pull_request(response)


def build_default_reconciliation_registry() -> ReconciliationHandlerRegistry:
    """Build the default operational reconciliation handler registry."""

    registry = ReconciliationHandlerRegistry()
    registry.register(
        ReconciliationFailureType.MISSING_PR_AFTER_EXECUTION,
        MissingPrAfterExecutionHandler(github=GitHubRestPullRequestGateway()),
    )
    return registry


def _iso_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = [
    "GitHubPullRequestGateway",
    "GitHubPullRequestRecord",
    "GitHubRestPullRequestGateway",
    "MissingPrMatchPolicy",
    "MissingPrAfterExecutionHandler",
    "ReconciliationAttemptStatus",
    "ReconciliationFailureType",
    "ReconciliationHandlerRegistry",
    "ReconciliationHandlerResult",
    "ReconciliationRuntimeContext",
    "ReconciliationRuntimeError",
    "build_default_reconciliation_registry",
    "default_reconciliation_state",
    "ensure_reconciliation_state",
    "resolve_code_context",
    "task_has_pull_request_artifact",
]
