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
_RESERVED_SHARED_BRANCH_NAMES = frozenset({"work", "main", "master", "develop", "development", "trunk", "default"})
_CODE_EXECUTION_ARTIFACT_TYPES = frozenset({"branch", "commit", "pull_request", "changed_file"})


class ReconciliationFailureType(StrEnum):
    """Failure classes that may invoke a reconciliation handler."""

    MISSING_PR_AFTER_EXECUTION = "missing_pr_after_execution"
    MISSING_COMMIT_AFTER_EXECUTION = "missing_commit_after_execution"


class ReconciliationAttemptStatus(StrEnum):
    """Operational reconciliation outcomes stored on the task."""

    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    RESOLVED = "resolved"
    FAILED = "failed"


class ReconciliationFailureDisposition(StrEnum):
    """Disposition for a reconciliation failure after classification."""

    REVIEW_REQUIRED = "review_required"
    BLOCKED_RETRYABLE = "blocked_retryable"
    TERMINAL_FAILED = "terminal_failed"


class ReconciliationRuntimeError(ValueError):
    """Raised when reconciliation runtime inputs are malformed."""

    def __init__(
        self,
        message: str,
        *,
        disposition: ReconciliationFailureDisposition = ReconciliationFailureDisposition.REVIEW_REQUIRED,
    ) -> None:
        super().__init__(message)
        self.disposition = disposition


class RetryableReconciliationRuntimeError(ReconciliationRuntimeError):
    """Raised when reconciliation is blocked by a retryable provider/platform failure."""

    def __init__(self, message: str) -> None:
        super().__init__(message, disposition=ReconciliationFailureDisposition.BLOCKED_RETRYABLE)


class TerminalReconciliationRuntimeError(ReconciliationRuntimeError):
    """Raised when reconciliation proves the execution outcome is terminally unusable."""

    def __init__(self, message: str) -> None:
        super().__init__(message, disposition=ReconciliationFailureDisposition.TERMINAL_FAILED)


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
    code_context_sources: dict[str, dict[str, Any]]
    code_context_source: str | None = None


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
    allow_non_head_commit_association_match: bool = False
    escalate_on_ambiguous_match: bool = True
    require_task_linkage: bool = False
    require_run_linkage_for_multiple_attempts: bool = True
    require_run_linkage_for_commit_association: bool = True


@dataclass(frozen=True)
class ReconciliationHandlerResult:
    """Structured result returned by a reconciliation handler."""

    task_envelope: TaskEnvelope
    status: ReconciliationAttemptStatus
    attempt: dict[str, Any]
    pull_request: GitHubPullRequestRecord | None = None
    error: str | None = None
    failure_disposition: ReconciliationFailureDisposition = ReconciliationFailureDisposition.REVIEW_REQUIRED
    target_status: str = "in_review"
    requires_review: bool = True


class GitHubPullRequestGateway(Protocol):
    """Boundary for GitHub-backed PR lookup and creation."""

    def branch_exists(self, *, owner: str, repo: str, branch_name: str) -> bool: ...

    def branch_head_commit_sha(self, *, owner: str, repo: str, branch_name: str) -> str | None: ...

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

    def get_pull_request(
        self,
        *,
        owner: str,
        repo: str,
        number: int,
    ) -> GitHubPullRequestRecord | None: ...


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


def task_has_valid_current_run_pull_request_artifact(
    task_envelope: TaskEnvelope,
    *,
    external_facts: Any = None,
) -> bool:
    """Return whether the task already carries a PR artifact that proves the current run."""

    return _current_run_pull_request_artifact(task_envelope, external_facts=external_facts) is not None


def _current_run_pull_request_artifact(
    task_envelope: TaskEnvelope,
    *,
    external_facts: Any = None,
) -> dict[str, Any] | None:
    """Return the verified current-run PR artifact when one is already attached."""

    artifacts = ((task_envelope.get("artifacts") or {}).get("items") or [])
    if not isinstance(artifacts, list):
        return None

    try:
        code_context = resolve_code_context(task_envelope, external_facts=external_facts)
    except ReconciliationRuntimeError:
        return None

    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        if artifact.get("type") != "pull_request":
            continue
        if str(artifact.get("verification_status") or "").strip().lower() != "verified":
            continue

        repository = _repository_from_artifact(artifact)
        if repository is None:
            continue
        _, owner, name = repository
        if owner != code_context.repository_owner or name != code_context.repository_name:
            continue

        branch = artifact.get("branch")
        if not isinstance(branch, dict):
            continue
        branch_name = _normalize_sha(branch.get("name"))
        head_commit_sha = _normalize_sha(branch.get("head_commit_sha"))
        if branch_name != code_context.branch_name:
            continue
        if branch_name is None or branch_name.casefold() in _RESERVED_SHARED_BRANCH_NAMES:
            continue
        if head_commit_sha != code_context.commit_sha:
            continue

        location = artifact.get("location")
        pull_request_number = artifact.get("pull_request_number")
        parsed_location = _parse_github_location(location)
        if parsed_location is None or parsed_location[2] != "pull" or not parsed_location[3].isdigit():
            continue
        if pull_request_number is None:
            continue
        if int(parsed_location[3]) != pull_request_number:
            continue

        metadata = artifact.get("metadata") if isinstance(artifact.get("metadata"), dict) else {}
        state = _normalize_sha(metadata.get("pull_request_state"))
        merged = metadata.get("pull_request_merged")
        if state is None or state.strip().lower() != "open":
            continue
        if merged is True:
            continue

        return artifact

    return None


def task_has_valid_current_run_commit_artifact(
    task_envelope: TaskEnvelope,
    *,
    external_facts: Any = None,
) -> bool:
    """Return whether the task already carries a commit artifact that proves the current run."""

    artifacts = ((task_envelope.get("artifacts") or {}).get("items") or [])
    if not isinstance(artifacts, list):
        return False

    try:
        code_context = resolve_code_context(task_envelope, external_facts=external_facts)
    except ReconciliationRuntimeError:
        return False
    if not code_context.commit_sha:
        return False

    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        if artifact.get("type") != "commit":
            continue
        if str(artifact.get("verification_status") or "").strip().lower() != "verified":
            continue

        repository = _repository_from_artifact(artifact)
        if repository is None:
            continue
        _, owner, name = repository
        if owner != code_context.repository_owner or name != code_context.repository_name:
            continue

        commit_sha = _normalize_sha(artifact.get("commit_sha"))
        if commit_sha != code_context.commit_sha:
            continue

        branch = artifact.get("branch")
        if isinstance(branch, dict):
            branch_name = _normalize_sha(branch.get("name"))
            if branch_name is not None and branch_name != code_context.branch_name:
                continue

        return True

    return False


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
        if str(artifact.get("type") or "").strip() not in _CODE_EXECUTION_ARTIFACT_TYPES:
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

    if not repository_owner or not repository_name or not branch_name:
        return None

    return ReconciliationCodeContext(
        repository_host=repository_host or "github.com",
        repository_owner=repository_owner,
        repository_name=repository_name,
        branch_name=branch_name,
        base_branch=base_branch,
        commit_sha=commit_sha or "",
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

    if not repository_owner or not repository_name or not branch_name:
        return None

    return ReconciliationCodeContext(
        repository_host=repository_host or "github.com",
        repository_owner=repository_owner,
        repository_name=repository_name,
        branch_name=branch_name,
        base_branch=base_branch,
        commit_sha=commit_sha or "",
    )


def _context_from_execution_attempt(task_envelope: TaskEnvelope) -> ReconciliationCodeContext | None:
    execution_metadata = ((task_envelope.get("observability") or {}).get("execution_metadata") or {})
    attempts = execution_metadata.get("execution_attempts") or []
    if not isinstance(attempts, list):
        return None

    latest_attempt = _latest_recorded_execution_attempt(attempts)
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
        if str(artifact_reference.get("artifact_type") or "").strip() not in _CODE_EXECUTION_ARTIFACT_TYPES:
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

    if not repository_owner or not repository_name or not branch_name:
        return None

    return ReconciliationCodeContext(
        repository_host=repository_host or "github.com",
        repository_owner=repository_owner,
        repository_name=repository_name,
        branch_name=branch_name,
        base_branch=base_branch,
        commit_sha=commit_sha or "",
    )


def _code_context_details(context: ReconciliationCodeContext) -> dict[str, Any]:
    return {
        "repository_host": context.repository_host,
        "repository_owner": context.repository_owner,
        "repository_name": context.repository_name,
        "branch_name": context.branch_name,
        "base_branch": context.base_branch,
        "commit_sha": context.commit_sha,
    }


def _code_context_conflicts(
    contexts: dict[str, ReconciliationCodeContext],
) -> tuple[dict[str, Any], ...]:
    compared_fields = (
        "repository_host",
        "repository_owner",
        "repository_name",
        "branch_name",
        "commit_sha",
    )
    items = list(contexts.items())
    conflicts: list[dict[str, Any]] = []
    for index, (left_source, left_context) in enumerate(items):
        for right_source, right_context in items[index + 1 :]:
            for field_name in compared_fields:
                left_value = getattr(left_context, field_name)
                right_value = getattr(right_context, field_name)
                if isinstance(left_value, str) and not left_value.strip():
                    continue
                if isinstance(right_value, str) and not right_value.strip():
                    continue
                if left_value == right_value:
                    continue
                conflicts.append(
                    {
                        "field": field_name,
                        "left_source": left_source,
                        "left_value": left_value,
                        "right_source": right_source,
                        "right_value": right_value,
                    }
                )
    return tuple(conflicts)


def _code_context_candidates(
    task_envelope: TaskEnvelope,
    *,
    external_facts: Any = None,
) -> dict[str, ReconciliationCodeContext]:
    source_contexts: dict[str, ReconciliationCodeContext] = {}
    for source_name, resolver in (
        ("external_facts", lambda: _context_from_external_facts(external_facts)),
        ("artifacts", lambda: _context_from_artifacts(task_envelope)),
        ("execution_attempt", lambda: _context_from_execution_attempt(task_envelope)),
    ):
        context = resolver()
        if context is None:
            continue
        if context.repository_host != "github.com":
            raise ReconciliationRuntimeError("reconciliation handlers currently support github.com repositories only")
        source_contexts[source_name] = context
    return source_contexts


def _resolved_code_context(
    task_envelope: TaskEnvelope,
    *,
    external_facts: Any = None,
) -> tuple[ReconciliationCodeContext, dict[str, dict[str, Any]], str]:
    source_contexts = _code_context_candidates(task_envelope, external_facts=external_facts)
    if not source_contexts:
        raise ReconciliationRuntimeError(
            "Unable to resolve repository, branch, and commit context for reconciliation"
        )

    conflicts = _code_context_conflicts(source_contexts)
    if conflicts:
        conflict_fields = ", ".join(sorted({str(item["field"]) for item in conflicts}))
        raise ReconciliationRuntimeError(
            f"Conflicting reconciliation code context across sources: {conflict_fields}"
        )

    merged_source = next(iter(source_contexts.values()))
    repository_host = merged_source.repository_host
    repository_owner = merged_source.repository_owner
    repository_name = merged_source.repository_name
    branch_name = merged_source.branch_name
    base_branch = merged_source.base_branch
    contributing_sources: list[str] = []
    for source_name, source_context in source_contexts.items():
        contributing_sources.append(source_name)
        repository_host = repository_host or source_context.repository_host
        repository_owner = repository_owner or source_context.repository_owner
        repository_name = repository_name or source_context.repository_name
        branch_name = branch_name or source_context.branch_name
        base_branch = base_branch or source_context.base_branch

    branch_source_name = (
        "execution_attempt"
        if "execution_attempt" in source_contexts and source_contexts["execution_attempt"].branch_name
        else next(
            (
                source_name
                for source_name, source_context in source_contexts.items()
                if source_context.branch_name
            ),
            contributing_sources[0],
        )
    )
    branch_source = source_contexts[branch_source_name]
    commit_sha = branch_source.commit_sha or ""
    if not commit_sha and branch_source_name != "execution_attempt":
        execution_context = source_contexts.get("execution_attempt")
        if (
            execution_context is not None
            and execution_context.commit_sha
            and execution_context.repository_host == (repository_host or "github.com")
            and execution_context.repository_owner == repository_owner
            and execution_context.repository_name == repository_name
            and execution_context.branch_name == branch_name
        ):
            commit_sha = execution_context.commit_sha

    selected_source = contributing_sources[0] if len(contributing_sources) == 1 else "merged"
    return (
        ReconciliationCodeContext(
            repository_host=repository_host or "github.com",
            repository_owner=repository_owner,
            repository_name=repository_name,
            branch_name=branch_name,
            base_branch=base_branch,
            commit_sha=commit_sha or "",
        ),
        {name: _code_context_details(context) for name, context in source_contexts.items()},
        selected_source,
    )


def resolve_code_context(
    task_envelope: TaskEnvelope,
    *,
    external_facts: Any = None,
) -> ReconciliationCodeContext:
    """Resolve repository, branch, base branch, and commit context for PR reconciliation."""

    context, _, _ = _resolved_code_context(task_envelope, external_facts=external_facts)
    return context


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


def _current_completion_claim(task_envelope: TaskEnvelope) -> dict[str, Any] | None:
    execution_metadata = ((task_envelope.get("observability") or {}).get("execution_metadata") or {})
    claims = execution_metadata.get("advisory_completion_claims") or []
    if not isinstance(claims, list):
        return None
    valid_claims = [claim for claim in claims if isinstance(claim, dict)]
    if not valid_claims:
        return None
    return max(
        valid_claims,
        key=lambda claim: (
            _parse_iso_timestamp(str(claim.get("reported_at") or "")),
            str(claim.get("claim_id") or ""),
        ),
    )


def _parse_iso_timestamp(value: str | None):
    from datetime import datetime, timezone

    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _latest_recorded_execution_attempt(attempts: list[dict[str, Any]]) -> dict[str, Any] | None:
    valid_attempts = [attempt for attempt in attempts if isinstance(attempt, dict)]
    if not valid_attempts:
        return None
    return max(
        valid_attempts,
        key=lambda attempt: (
            _parse_iso_timestamp(str(attempt.get("recorded_at") or "")),
            str(attempt.get("attempt_id") or ""),
        ),
    )


def _current_execution_attempt(task_envelope: TaskEnvelope) -> dict[str, Any] | None:
    execution_metadata = ((task_envelope.get("observability") or {}).get("execution_metadata") or {})
    attempts = execution_metadata.get("execution_attempts") or []
    if not isinstance(attempts, list):
        return None

    claim = _current_completion_claim(task_envelope)
    if claim is None:
        return _latest_recorded_execution_attempt(attempts)

    claim_metadata = claim.get("metadata") if isinstance(claim.get("metadata"), dict) else {}
    attempt_id = _normalize_sha(claim_metadata.get("attempt_id"))
    if attempt_id is not None:
        matching_attempt = _latest_recorded_execution_attempt(
            [
                attempt
                for attempt in attempts
                if isinstance(attempt, dict)
                and _normalize_sha(attempt.get("attempt_id")) == attempt_id
            ]
        )
        if matching_attempt is not None:
            return matching_attempt

    claim_id = _normalize_sha(claim.get("claim_id"))
    if claim_id is not None:
        matching_attempt = _latest_recorded_execution_attempt(
            [
                attempt
                for attempt in attempts
                if isinstance(attempt, dict)
                and _normalize_sha(attempt.get("completion_claim_id")) == claim_id
            ]
        )
        if matching_attempt is not None:
            return matching_attempt

    return _latest_recorded_execution_attempt(attempts)


def _execution_attempt_count(task_envelope: TaskEnvelope) -> int:
    execution_metadata = ((task_envelope.get("observability") or {}).get("execution_metadata") or {})
    attempts = execution_metadata.get("execution_attempts") or []
    if not isinstance(attempts, list):
        return 0
    return len([attempt for attempt in attempts if isinstance(attempt, dict)])


def _parse_harness_linkage_markers(text: str | None) -> dict[str, str]:
    if not isinstance(text, str) or not text.strip():
        return {}
    markers: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("Harness-"):
            continue
        key, separator, value = line.partition(":")
        if not separator:
            continue
        normalized_key = key.strip().casefold()
        normalized_value = value.strip()
        if normalized_value:
            markers[normalized_key] = normalized_value
    return markers


def _current_run_linkage_details(
    task_envelope: TaskEnvelope,
    *,
    code_context: ReconciliationCodeContext,
) -> dict[str, Any]:
    claim = _current_completion_claim(task_envelope)
    attempt = _current_execution_attempt(task_envelope)
    attempt_count = _execution_attempt_count(task_envelope)
    return {
        "task_id": _normalize_sha(task_envelope.get("id")),
        "task_title": _normalize_sha(task_envelope.get("title")),
        "attempt_id": _normalize_sha((attempt or {}).get("attempt_id")),
        "completion_claim_id": _normalize_sha((claim or {}).get("claim_id")),
        "branch_name": code_context.branch_name,
        "commit_sha": code_context.commit_sha,
        "attempt_count": attempt_count,
        "multiple_attempts": attempt_count > 1,
    }


def _run_linkage_details(
    task_envelope: TaskEnvelope,
    pull_request: GitHubPullRequestRecord,
    *,
    code_context: ReconciliationCodeContext,
) -> dict[str, Any]:
    current = _current_run_linkage_details(task_envelope, code_context=code_context)
    title_markers = _parse_harness_linkage_markers(pull_request.title)
    body_markers = _parse_harness_linkage_markers(pull_request.body)
    markers = {**title_markers, **body_markers}

    attempt_id = current["attempt_id"]
    completion_claim_id = current["completion_claim_id"]
    task_id = current["task_id"]
    branch_name = current["branch_name"]
    commit_sha = current["commit_sha"]

    attempt_id_present = bool(attempt_id) and markers.get("harness-attempt-id") == attempt_id
    completion_claim_id_present = bool(completion_claim_id) and markers.get("harness-completion-claim-id") == completion_claim_id
    task_id_present = bool(task_id) and markers.get("harness-task-id") == task_id
    branch_name_present = bool(branch_name) and markers.get("harness-branch") == branch_name
    commit_sha_present = bool(commit_sha) and markers.get("harness-commit-sha") == commit_sha

    return {
        "markers": markers,
        "attempt_id_present": attempt_id_present,
        "completion_claim_id_present": completion_claim_id_present,
        "task_id_marker_present": task_id_present,
        "branch_name_present": branch_name_present,
        "commit_sha_present": commit_sha_present,
        "linked": attempt_id_present or completion_claim_id_present,
        "current_run": current,
    }


def _created_pull_request_title(task_envelope: TaskEnvelope) -> str:
    task_id = str(task_envelope.get("id") or "").strip()
    task_title = str(task_envelope.get("title") or "").strip()
    if task_title and task_id and task_id not in task_title:
        return f"{task_title} ({task_id})"
    return task_title or task_id


def _created_pull_request_body(
    task_envelope: TaskEnvelope,
    *,
    code_context: ReconciliationCodeContext,
) -> str:
    run_linkage = _current_run_linkage_details(task_envelope, code_context=code_context)
    lines = [
        (
            "Harness reconciliation created this pull request after execution completed "
            "without a PR artifact."
        ),
    ]
    if run_linkage["task_id"]:
        lines.append(f"Harness-Task-ID: {run_linkage['task_id']}")
    if run_linkage["attempt_id"]:
        lines.append(f"Harness-Attempt-ID: {run_linkage['attempt_id']}")
    if run_linkage["completion_claim_id"]:
        lines.append(f"Harness-Completion-Claim-ID: {run_linkage['completion_claim_id']}")
    lines.append(f"Harness-Branch: {code_context.branch_name}")
    lines.append(f"Harness-Commit-SHA: {code_context.commit_sha}")
    return "\n".join(lines)


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


def _commit_artifact(
    *,
    task_envelope: TaskEnvelope,
    code_context: ReconciliationCodeContext,
    captured_at: str,
    pull_request_artifact: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pull_request_url = None
    pull_request_number = None
    if isinstance(pull_request_artifact, dict):
        pull_request_url = _normalize_sha(pull_request_artifact.get("location"))
        raw_pull_request_number = pull_request_artifact.get("pull_request_number")
        if isinstance(raw_pull_request_number, int):
            pull_request_number = raw_pull_request_number

    return {
        "id": f"artifact-commit-{code_context.commit_sha[:12]}",
        "type": "commit",
        "title": None,
        "description": "Attached by Harness reconciliation after execution completed without a commit artifact.",
        "location": (
            f"https://github.com/{code_context.repository_owner}/{code_context.repository_name}/commit/"
            f"{code_context.commit_sha}"
        ),
        "content_type": None,
        "external_id": f"commit-{code_context.commit_sha}",
        "commit_sha": code_context.commit_sha,
        "pull_request_number": pull_request_number,
        "review_state": None,
        "provenance": {
            "source_system": "github",
            "source_type": "api",
            "source_id": f"commit/{code_context.commit_sha}",
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
            "attached_by": "missing_commit_after_execution",
            "linked_pull_request_url": pull_request_url,
        },
    }


def _ensure_pull_request_artifact(
    task_envelope: TaskEnvelope,
    *,
    code_context: ReconciliationCodeContext,
    pull_request: GitHubPullRequestRecord,
    captured_at: str,
) -> tuple[TaskEnvelope, str]:
    updated = deepcopy(task_envelope)
    artifacts = updated.setdefault("artifacts", {}).setdefault("items", [])
    if not isinstance(artifacts, list):
        raise ReconciliationRuntimeError("task.artifacts.items must be a list")

    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            continue
        if artifact.get("type") != "pull_request":
            continue
        if artifact.get("pull_request_number") == pull_request.number or artifact.get("location") == pull_request.url:
            canonical_artifact = _pull_request_artifact(
                task_envelope=updated,
                code_context=code_context,
                pull_request=pull_request,
                captured_at=captured_at,
            )
            canonical_artifact["id"] = artifact.get("id") or canonical_artifact["id"]
            artifacts[index] = canonical_artifact
            return updated, str(canonical_artifact["id"])

    artifact = _pull_request_artifact(
        task_envelope=updated,
        code_context=code_context,
        pull_request=pull_request,
        captured_at=captured_at,
    )
    artifacts.append(artifact)
    return updated, str(artifact["id"])


def _ensure_commit_artifact(
    task_envelope: TaskEnvelope,
    *,
    code_context: ReconciliationCodeContext,
    captured_at: str,
    pull_request_artifact: dict[str, Any] | None = None,
) -> tuple[TaskEnvelope, str]:
    updated = deepcopy(task_envelope)
    artifacts = updated.setdefault("artifacts", {}).setdefault("items", [])
    if not isinstance(artifacts, list):
        raise ReconciliationRuntimeError("task.artifacts.items must be a list")

    expected_location = (
        f"https://github.com/{code_context.repository_owner}/{code_context.repository_name}/commit/{code_context.commit_sha}"
    )
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            continue
        if artifact.get("type") != "commit":
            continue
        if _normalize_sha(artifact.get("commit_sha")) == code_context.commit_sha or artifact.get("location") == expected_location:
            canonical_artifact = _commit_artifact(
                task_envelope=updated,
                code_context=code_context,
                captured_at=captured_at,
                pull_request_artifact=pull_request_artifact,
            )
            canonical_artifact["id"] = artifact.get("id") or canonical_artifact["id"]
            artifacts[index] = canonical_artifact
            return updated, str(canonical_artifact["id"])

    artifact = _commit_artifact(
        task_envelope=updated,
        code_context=code_context,
        captured_at=captured_at,
        pull_request_artifact=pull_request_artifact,
    )
    artifacts.append(artifact)
    return updated, str(artifact["id"])


def _mark_reconciled_artifact_validated(
    task_envelope: TaskEnvelope,
    *,
    artifact_id: str,
    artifact_type: str,
) -> TaskEnvelope:
    updated = deepcopy(task_envelope)
    completion_evidence = ((updated.get("artifacts") or {}).get("completion_evidence") or {})
    if not isinstance(completion_evidence, dict):
        return updated

    required_types = completion_evidence.get("required_artifact_types")
    if not isinstance(required_types, list) or artifact_type not in required_types:
        return updated

    validated_artifact_ids = completion_evidence.get("validated_artifact_ids")
    if not isinstance(validated_artifact_ids, list):
        validated_artifact_ids = []
        completion_evidence["validated_artifact_ids"] = validated_artifact_ids
    if artifact_id not in validated_artifact_ids:
        validated_artifact_ids.append(artifact_id)

    artifact_items = ((updated.get("artifacts") or {}).get("items") or [])
    artifact_type_by_id: dict[str, str] = {}
    if isinstance(artifact_items, list):
        for item in artifact_items:
            if not isinstance(item, dict):
                continue
            raw_id = item.get("id")
            raw_type = item.get("type")
            if raw_id is None or not isinstance(raw_type, str) or not raw_type.strip():
                continue
            artifact_type_by_id[str(raw_id)] = raw_type.strip()

    validated_types = {
        artifact_type_by_id.get(str(validated_id))
        for validated_id in validated_artifact_ids
    }
    validated_types.discard(None)

    completion_evidence["validation_method"] = "external_reconciliation"
    completion_evidence["validated_at"] = _iso_now()
    completion_evidence["validator"] = {
        "source_system": "harness",
        "source_type": "verification",
        "source_id": f"reconciliation-{artifact_type}",
        "captured_by": "reconciliation",
    }
    completion_evidence["status"] = (
        "satisfied"
        if all(
            isinstance(required_type, str) and required_type.strip() in validated_types
            for required_type in required_types
        )
        else "deferred"
    )
    updated["artifacts"]["completion_evidence"] = completion_evidence
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
        run_linkage: dict[str, Any],
        linkage_policy: dict[str, Any],
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
                    "run_linkage": run_linkage,
                    "linkage_policy": linkage_policy,
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
    ) -> tuple[
        bool,
        list[str],
        list[str],
        dict[str, Any],
        dict[str, Any],
        dict[str, Any],
    ]:
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
        non_head_commit_association_match = commit_association_match and not head_sha_match

        if self.policy.require_head_sha_match:
            if head_sha_match:
                matched_by.append("head_sha_match")
                if commit_association_match:
                    matched_by.append("commit_association_match")
            elif commit_association_match:
                matched_by.append("commit_association_match")
                if not self.policy.allow_non_head_commit_association_match:
                    reasons.append("commit_association_without_current_head_evidence")
            else:
                reasons.append("head_sha_mismatch" if pull_request.head_sha else "missing_head_sha")
        elif commit_association_match:
            matched_by.append("commit_association_match")

        task_linkage = _task_linkage_details(task_envelope, pull_request)
        if self.policy.require_task_linkage and not task_linkage["linked"]:
            reasons.append("task_linkage_missing")
        elif task_linkage["linked"]:
            matched_by.append("task_linkage")
        run_linkage = _run_linkage_details(task_envelope, pull_request, code_context=code_context)
        require_run_linkage = False
        linkage_reasons: list[str] = []
        if self.policy.require_run_linkage_for_multiple_attempts and run_linkage["current_run"]["multiple_attempts"]:
            require_run_linkage = True
            linkage_reasons.append("multiple_execution_attempts")
        if (
            self.policy.allow_non_head_commit_association_match
            and self.policy.require_run_linkage_for_commit_association
            and non_head_commit_association_match
        ):
            require_run_linkage = True
            linkage_reasons.append("commit_association_without_head_sha_match")

        if require_run_linkage:
            if not run_linkage["linked"]:
                reasons.append("run_linkage_missing")
            else:
                if run_linkage["attempt_id_present"]:
                    matched_by.append("attempt_linkage")
                if run_linkage["completion_claim_id_present"]:
                    matched_by.append("completion_claim_linkage")
        elif run_linkage["linked"]:
            if run_linkage["attempt_id_present"]:
                matched_by.append("attempt_linkage")
            if run_linkage["completion_claim_id_present"]:
                matched_by.append("completion_claim_linkage")

        linkage_policy = {
            "require_run_linkage": require_run_linkage,
            "reasons": linkage_reasons,
        }
        return not reasons, reasons, matched_by, task_linkage, run_linkage, linkage_policy

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
            accepted, reasons, matched_by, task_linkage, run_linkage, linkage_policy = self._validate_candidate(
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
                    run_linkage=run_linkage,
                    linkage_policy=linkage_policy,
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
                "context_resolution": {
                    "selected_source": context.code_context_source,
                    "sources": deepcopy(context.code_context_sources),
                    "conflicts": [],
                },
                "branch_name": code_context.branch_name,
                "base_branch": code_context.base_branch,
                "commit_sha": code_context.commit_sha,
                "policy": _policy_details(self.policy),
                "branch_exists": None,
                "branch_head_commit_sha": None,
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
                "created_pull_request_revalidated": False,
                "error_disposition": None,
                "final_decision": {
                    "result": None,
                    "reason": None,
                },
                "error": None,
            },
        }

        try:
            branch_exists = self.github.branch_exists(
                owner=code_context.repository_owner,
                repo=code_context.repository_name,
                branch_name=code_context.branch_name,
            )
            attempt["details"]["branch_exists"] = branch_exists
            if not branch_exists:
                raise TerminalReconciliationRuntimeError(
                    f"GitHub branch {code_context.branch_name!r} was not found in "
                    f"{code_context.repository_owner}/{code_context.repository_name}"
                )

            if not code_context.commit_sha.strip():
                branch_head_commit_sha = self.github.branch_head_commit_sha(
                    owner=code_context.repository_owner,
                    repo=code_context.repository_name,
                    branch_name=code_context.branch_name,
                )
                attempt["details"]["branch_head_commit_sha"] = branch_head_commit_sha
                if not branch_head_commit_sha:
                    raise TerminalReconciliationRuntimeError(
                        "Commit SHA is required for missing_pr_after_execution reconciliation and "
                        "could not be resolved from the branch head"
                    )
                code_context = ReconciliationCodeContext(
                    repository_host=code_context.repository_host,
                    repository_owner=code_context.repository_owner,
                    repository_name=code_context.repository_name,
                    branch_name=code_context.branch_name,
                    base_branch=code_context.base_branch,
                    commit_sha=branch_head_commit_sha,
                )
                attempt["details"]["commit_sha"] = branch_head_commit_sha

            commit_exists = self.github.commit_exists(
                owner=code_context.repository_owner,
                repo=code_context.repository_name,
                commit_sha=code_context.commit_sha,
            )
            attempt["details"]["commit_exists"] = commit_exists
            if not commit_exists:
                raise TerminalReconciliationRuntimeError(
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
                    title=_created_pull_request_title(context.task_envelope),
                    body=_created_pull_request_body(
                        context.task_envelope,
                        code_context=code_context,
                    ),
                    head=code_context.branch_name,
                    base=base_branch,
                )
                source = "created"
                attempt["details"]["created_pull_request"] = True
                created_sources = {"created_response"}
                created_accepted, created_reasons, created_matched_by, created_task_linkage, created_run_linkage, created_linkage_policy = self._validate_candidate(
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
                        run_linkage=created_run_linkage,
                        linkage_policy=created_linkage_policy,
                        code_context=code_context,
                    )
                )
                attempt["details"]["pull_request_lookup"]["candidate_count"] += 1
                if not created_accepted:
                    attempt["details"]["final_decision"] = {
                        "result": "created_candidate_rejected",
                        "reason": "created_pull_request_failed_validation",
                    }
                    raise ReconciliationRuntimeError(
                        "Created pull request did not satisfy current-run validation policy"
                    )
                persisted_pull_request = self.github.get_pull_request(
                    owner=code_context.repository_owner,
                    repo=code_context.repository_name,
                    number=pull_request.number,
                )
                if persisted_pull_request is None:
                    attempt["details"]["final_decision"] = {
                        "result": "created_pull_request_revalidation_failed",
                        "reason": "created_pull_request_not_visible_after_create",
                    }
                    raise ReconciliationRuntimeError(
                        "Created pull request could not be revalidated from persisted GitHub state"
                    )
                persisted_sources = {"created_persisted"}
                persisted_accepted, persisted_reasons, persisted_matched_by, persisted_task_linkage, persisted_run_linkage, persisted_linkage_policy = self._validate_candidate(
                    persisted_pull_request,
                    code_context=code_context,
                    task_envelope=context.task_envelope,
                    sources=persisted_sources,
                )
                attempt["details"]["pull_request_candidates"].append(
                    self._candidate_details(
                        persisted_pull_request,
                        sources=persisted_sources,
                        accepted=persisted_accepted,
                        reasons=persisted_reasons,
                        matched_by=persisted_matched_by,
                        task_linkage=persisted_task_linkage,
                        run_linkage=persisted_run_linkage,
                        linkage_policy=persisted_linkage_policy,
                        code_context=code_context,
                    )
                )
                attempt["details"]["pull_request_lookup"]["candidate_count"] += 1
                if not persisted_accepted:
                    attempt["details"]["final_decision"] = {
                        "result": "created_pull_request_revalidation_failed",
                        "reason": "persisted_pull_request_failed_validation",
                    }
                    raise ReconciliationRuntimeError(
                        "Created pull request did not satisfy current-run validation policy after read-back"
                    )
                attempt["details"]["created_pull_request_revalidated"] = True
                attempt["details"]["pull_request_lookup"]["valid_candidate_count"] += 1
                attempt["details"]["final_decision"] = {
                    "result": "created_new",
                    "reason": "no_valid_existing_candidate",
                }
                pull_request = persisted_pull_request
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

            updated_task, artifact_id = _ensure_pull_request_artifact(
                context.task_envelope,
                code_context=code_context,
                pull_request=pull_request,
                captured_at=completed_at,
            )
            updated_task = _mark_reconciled_artifact_validated(
                updated_task,
                artifact_id=artifact_id,
                artifact_type="pull_request",
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
            if isinstance(error_message, ReconciliationRuntimeError):
                failure_disposition = error_message.disposition
            else:
                failure_disposition = ReconciliationFailureDisposition.REVIEW_REQUIRED
            if failure_disposition == ReconciliationFailureDisposition.BLOCKED_RETRYABLE:
                target_status = "blocked"
            elif failure_disposition == ReconciliationFailureDisposition.TERMINAL_FAILED:
                target_status = "failed"
            else:
                target_status = "in_review"
            requires_review = target_status == "in_review"
            completed_at = _iso_now()
            attempt["status"] = ReconciliationAttemptStatus.FAILED.value
            attempt["completed_at"] = completed_at
            attempt["details"]["error"] = str(error_message)
            attempt["details"]["error_disposition"] = failure_disposition.value
            if attempt["details"]["final_decision"]["result"] is None:
                attempt["details"]["final_decision"] = {
                    "result": (
                        "blocked_retryable_failure"
                        if target_status == "blocked"
                        else "terminal_failed"
                        if target_status == "failed"
                        else "review_required_failure"
                    ),
                    "reason": (
                        "provider_platform_failure"
                        if target_status == "blocked"
                        else "objective_execution_contradiction"
                        if target_status == "failed"
                        else "reconciliation_runtime_error"
                    ),
                }
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
                failure_disposition=failure_disposition,
                target_status=target_status,
                requires_review=requires_review,
            )


class MissingCommitAfterExecutionHandler:
    """Reconcile a successful execution attempt that lacks a commit artifact."""

    def __init__(
        self,
        *,
        github: GitHubPullRequestGateway,
    ) -> None:
        self.github = github

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
                "context_resolution": {
                    "selected_source": context.code_context_source,
                    "sources": deepcopy(context.code_context_sources),
                    "conflicts": [],
                },
                "branch_name": code_context.branch_name,
                "base_branch": code_context.base_branch,
                "commit_sha": code_context.commit_sha,
                "branch_exists": None,
                "branch_head_commit_sha": None,
                "commit_exists": None,
                "pull_request_proof": {
                    "found": False,
                    "artifact_id": None,
                    "url": None,
                    "number": None,
                    "verification_status": None,
                },
                "created_commit_artifact": False,
                "error_disposition": None,
                "final_decision": {
                    "result": None,
                    "reason": None,
                },
                "error": None,
            },
        }

        try:
            branch_exists = self.github.branch_exists(
                owner=code_context.repository_owner,
                repo=code_context.repository_name,
                branch_name=code_context.branch_name,
            )
            attempt["details"]["branch_exists"] = branch_exists
            if not branch_exists:
                raise TerminalReconciliationRuntimeError(
                    f"GitHub branch {code_context.branch_name!r} was not found in "
                    f"{code_context.repository_owner}/{code_context.repository_name}"
                )

            if not code_context.commit_sha.strip():
                branch_head_commit_sha = self.github.branch_head_commit_sha(
                    owner=code_context.repository_owner,
                    repo=code_context.repository_name,
                    branch_name=code_context.branch_name,
                )
                attempt["details"]["branch_head_commit_sha"] = branch_head_commit_sha
                if not branch_head_commit_sha:
                    raise TerminalReconciliationRuntimeError(
                        "Commit SHA is required for missing_commit_after_execution reconciliation and "
                        "could not be resolved from the branch head"
                    )
                code_context = ReconciliationCodeContext(
                    repository_host=code_context.repository_host,
                    repository_owner=code_context.repository_owner,
                    repository_name=code_context.repository_name,
                    branch_name=code_context.branch_name,
                    base_branch=code_context.base_branch,
                    commit_sha=branch_head_commit_sha,
                )
                attempt["details"]["commit_sha"] = branch_head_commit_sha

            commit_exists = self.github.commit_exists(
                owner=code_context.repository_owner,
                repo=code_context.repository_name,
                commit_sha=code_context.commit_sha,
            )
            attempt["details"]["commit_exists"] = commit_exists
            if not commit_exists:
                raise TerminalReconciliationRuntimeError(
                    f"GitHub commit {code_context.commit_sha!r} was not found in "
                    f"{code_context.repository_owner}/{code_context.repository_name}"
                )

            pull_request_artifact = _current_run_pull_request_artifact(context.task_envelope)
            if pull_request_artifact is None:
                attempt["details"]["final_decision"] = {
                    "result": "missing_current_run_pull_request_proof",
                    "reason": "verified_pull_request_artifact_required",
                }
                raise TerminalReconciliationRuntimeError(
                    "A verified current-run pull request artifact is required for missing_commit_after_execution reconciliation"
                )

            raw_number = pull_request_artifact.get("pull_request_number")
            attempt["details"]["pull_request_proof"] = {
                "found": True,
                "artifact_id": pull_request_artifact.get("id"),
                "url": pull_request_artifact.get("location"),
                "number": raw_number if isinstance(raw_number, int) else None,
                "verification_status": pull_request_artifact.get("verification_status"),
            }

            updated_task, artifact_id = _ensure_commit_artifact(
                context.task_envelope,
                code_context=code_context,
                captured_at=completed_at,
                pull_request_artifact=pull_request_artifact,
            )
            updated_task = _mark_reconciled_artifact_validated(
                updated_task,
                artifact_id=artifact_id,
                artifact_type="commit",
            )
            attempt["details"]["created_commit_artifact"] = True
            attempt["details"]["final_decision"] = {
                "result": "attached_commit_artifact",
                "reason": "verified_pull_request_proof_and_commit_resolved",
            }
            attempt["status"] = ReconciliationAttemptStatus.RESOLVED.value
            attempt["completed_at"] = completed_at
            updated_task = _record_reconciliation_attempt(
                updated_task,
                attempt=attempt,
                status=ReconciliationAttemptStatus.RESOLVED,
                failure_type=context.failure_type,
                completed_at=completed_at,
                pull_request_url=_normalize_sha(pull_request_artifact.get("location")),
                error_message=None,
            )
            return ReconciliationHandlerResult(
                task_envelope=updated_task,
                status=ReconciliationAttemptStatus.RESOLVED,
                attempt=attempt,
                pull_request=None,
                error=None,
            )
        except Exception as error_message:
            if isinstance(error_message, ReconciliationRuntimeError):
                failure_disposition = error_message.disposition
            else:
                failure_disposition = ReconciliationFailureDisposition.REVIEW_REQUIRED
            if failure_disposition == ReconciliationFailureDisposition.BLOCKED_RETRYABLE:
                target_status = "blocked"
            elif failure_disposition == ReconciliationFailureDisposition.TERMINAL_FAILED:
                target_status = "failed"
            else:
                target_status = "in_review"
            requires_review = target_status == "in_review"
            completed_at = _iso_now()
            attempt["status"] = ReconciliationAttemptStatus.FAILED.value
            attempt["completed_at"] = completed_at
            attempt["details"]["error"] = str(error_message)
            attempt["details"]["error_disposition"] = failure_disposition.value
            if attempt["details"]["final_decision"]["result"] is None:
                attempt["details"]["final_decision"] = {
                    "result": (
                        "blocked_retryable_failure"
                        if target_status == "blocked"
                        else "terminal_failed"
                        if target_status == "failed"
                        else "review_required_failure"
                    ),
                    "reason": (
                        "provider_platform_failure"
                        if target_status == "blocked"
                        else "objective_execution_contradiction"
                        if target_status == "failed"
                        else "reconciliation_runtime_error"
                    ),
                }
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
                failure_disposition=failure_disposition,
                target_status=target_status,
                requires_review=requires_review,
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
        normalized_task = ensure_reconciliation_state(task_envelope)
        source_context_details: dict[str, dict[str, Any]] = {}
        source_context_conflicts: list[dict[str, Any]] = []
        try:
            candidate_contexts = _code_context_candidates(normalized_task, external_facts=external_facts)
            source_context_details = {
                name: _code_context_details(context) for name, context in candidate_contexts.items()
            }
            source_context_conflicts = list(_code_context_conflicts(candidate_contexts))
            code_context, resolved_source_contexts, selected_source = _resolved_code_context(
                normalized_task,
                external_facts=external_facts,
            )
        except ReconciliationRuntimeError as error:
            completed_at = _iso_now()
            attempt = {
                "attempt_id": _reconciliation_attempt_id(normalized_task),
                "failure_type": failure_type.value,
                "handler_key": failure_type.value,
                "status": ReconciliationAttemptStatus.FAILED.value,
                "started_at": started_at,
                "completed_at": completed_at,
                "details": {
                    "context_resolution": {
                        "selected_source": None,
                        "sources": source_context_details,
                        "conflicts": source_context_conflicts,
                    },
                    "final_decision": {
                        "result": "context_resolution_failed",
                        "reason": "conflicting_or_missing_code_context",
                    },
                    "error": str(error),
                    "error_disposition": error.disposition.value,
                },
            }
            updated_task = _record_reconciliation_attempt(
                normalized_task,
                attempt=attempt,
                status=ReconciliationAttemptStatus.FAILED,
                failure_type=failure_type,
                completed_at=completed_at,
                pull_request_url=None,
                error_message=str(error),
            )
            target_status = (
                "blocked"
                if error.disposition == ReconciliationFailureDisposition.BLOCKED_RETRYABLE
                else "failed"
                if error.disposition == ReconciliationFailureDisposition.TERMINAL_FAILED
                else "in_review"
            )
            requires_review = target_status == "in_review"
            return ReconciliationHandlerResult(
                task_envelope=updated_task,
                status=ReconciliationAttemptStatus.FAILED,
                attempt=attempt,
                pull_request=None,
                error=str(error),
                failure_disposition=error.disposition,
                target_status=target_status,
                requires_review=requires_review,
            )

        context = ReconciliationRuntimeContext(
            task_envelope=normalized_task,
            failure_type=failure_type,
            code_context=code_context,
            code_context_sources=resolved_source_contexts,
            code_context_source=selected_source,
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
            raise RetryableReconciliationRuntimeError(
                f"GitHub API request failed for {path}: HTTP {http_error.code} {response_body}".strip()
            ) from http_error
        except error.URLError as url_error:
            raise RetryableReconciliationRuntimeError(
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

    def branch_head_commit_sha(self, *, owner: str, repo: str, branch_name: str) -> str | None:
        safe_branch = parse.quote(branch_name, safe="")
        response = self._request_json(f"/repos/{owner}/{repo}/branches/{safe_branch}")
        if not isinstance(response, dict):
            return None
        commit = response.get("commit")
        if not isinstance(commit, dict):
            return None
        sha = commit.get("sha")
        return sha.strip() if isinstance(sha, str) and sha.strip() else None

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

    def get_pull_request(
        self,
        *,
        owner: str,
        repo: str,
        number: int,
    ) -> GitHubPullRequestRecord | None:
        response = self._request_json(f"/repos/{owner}/{repo}/pulls/{number}")
        if not isinstance(response, dict):
            return None
        return self._normalize_pull_request(response)


def build_default_reconciliation_registry() -> ReconciliationHandlerRegistry:
    """Build the default operational reconciliation handler registry."""

    registry = ReconciliationHandlerRegistry()
    github = GitHubRestPullRequestGateway()
    registry.register(
        ReconciliationFailureType.MISSING_PR_AFTER_EXECUTION,
        MissingPrAfterExecutionHandler(github=github),
    )
    registry.register(
        ReconciliationFailureType.MISSING_COMMIT_AFTER_EXECUTION,
        MissingCommitAfterExecutionHandler(github=github),
    )
    return registry


def _iso_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = [
    "GitHubPullRequestGateway",
    "GitHubPullRequestRecord",
    "GitHubRestPullRequestGateway",
    "MissingCommitAfterExecutionHandler",
    "MissingPrMatchPolicy",
    "MissingPrAfterExecutionHandler",
    "ReconciliationAttemptStatus",
    "ReconciliationFailureDisposition",
    "ReconciliationFailureType",
    "ReconciliationHandlerRegistry",
    "ReconciliationHandlerResult",
    "ReconciliationRuntimeContext",
    "ReconciliationRuntimeError",
    "RetryableReconciliationRuntimeError",
    "TerminalReconciliationRuntimeError",
    "build_default_reconciliation_registry",
    "default_reconciliation_state",
    "ensure_reconciliation_state",
    "resolve_code_context",
    "task_has_pull_request_artifact",
    "task_has_valid_current_run_commit_artifact",
    "task_has_valid_current_run_pull_request_artifact",
]
