"""GitHub-shaped sync adapter for canonical Harness reevaluation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from modules.contracts.task_envelope_external_facts import (
    BranchFact,
    ChangedFilesSummary,
    CommitFact,
    GitHubArtifactFacts,
    PullRequestFact,
    RepositoryFact,
)

from .github_facts import GitHubConnectorInputError, translate_github_artifact_facts


class GitHubSyncInputError(ValueError):
    """Raised when a GitHub sync payload cannot be normalized canonically."""


def _require_mapping(payload: Any, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise GitHubSyncInputError(f"{field_name} must be a mapping")
    return payload


def _optional_mapping(payload: Any, *, field_name: str) -> Mapping[str, Any] | None:
    if payload is None:
        return None
    return _require_mapping(payload, field_name=field_name)


def _require_string(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GitHubSyncInputError(f"{field_name} is required")
    return value.strip()


def _optional_string(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise GitHubSyncInputError(f"{field_name} must be a string when provided")
    stripped = value.strip()
    return stripped or None


def _optional_boolean(value: Any, *, field_name: str, default: bool = False) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise GitHubSyncInputError(f"{field_name} must be a boolean")
    return value


def _to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _to_jsonable(val) for key, val in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _to_jsonable(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    return value


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _artifact_id_suffix(value: str) -> str:
    return value.replace("/", "-").replace(" ", "-")


def _changed_files_payload(changed_files: ChangedFilesSummary | None) -> list[dict[str, Any]]:
    if changed_files is None:
        return []
    return [
        {
            "path": file_fact.path,
            "change_type": file_fact.change_type,
            "additions": file_fact.additions,
            "deletions": file_fact.deletions,
            "previous_path": file_fact.previous_path,
        }
        for file_fact in changed_files.files
    ]


def _repository_payload(repository: RepositoryFact | None) -> dict[str, Any] | None:
    return _to_jsonable(repository) if repository is not None else None


def _branch_payload(branch: BranchFact | None) -> dict[str, Any] | None:
    return _to_jsonable(branch) if branch is not None else None


def _derive_branch_location(repository: RepositoryFact | None, branch: BranchFact | None) -> str | None:
    if repository is None or branch is None:
        return None
    return f"https://{repository.host}/{repository.owner}/{repository.name}/tree/{branch.name}"


def _derive_commit_location(repository: RepositoryFact | None, commit: CommitFact | None) -> str | None:
    if commit is None:
        return None
    if commit.url:
        return commit.url
    if repository is None:
        return None
    return f"https://{repository.host}/{repository.owner}/{repository.name}/commit/{commit.sha}"


def _derive_pull_request_location(repository: RepositoryFact | None, pull_request: PullRequestFact | None) -> str | None:
    if pull_request is None:
        return None
    if pull_request.url:
        return pull_request.url
    if repository is None:
        return None
    return f"https://{repository.host}/{repository.owner}/{repository.name}/pull/{pull_request.number}"


def _derive_changed_file_location(
    *,
    repository: RepositoryFact | None,
    branch: BranchFact | None,
    commit: CommitFact | None,
    path: str,
) -> str | None:
    if repository is None:
        return None
    revision = None
    if commit is not None and commit.sha:
        revision = commit.sha
    elif branch is not None and branch.name:
        revision = branch.name
    if revision is None:
        return None
    return f"https://{repository.host}/{repository.owner}/{repository.name}/blob/{revision}/{path}"


def _branch_artifact(
    *,
    repository: RepositoryFact | None,
    branch: BranchFact,
    captured_at: str,
    captured_by: str,
) -> dict[str, Any]:
    return {
        "id": f"artifact-branch-{_artifact_id_suffix(branch.name)}",
        "type": "branch",
        "title": "GitHub branch sync",
        "description": "Attached by GitHub sync through canonical reevaluation.",
        "location": _derive_branch_location(repository, branch),
        "content_type": None,
        "external_id": branch.name,
        "commit_sha": None,
        "pull_request_number": None,
        "review_state": None,
        "provenance": {
            "source_system": "github",
            "source_type": "api",
            "source_id": f"branch/{branch.name}",
            "captured_by": captured_by,
        },
        "verification_status": "verified",
        "repository": _repository_payload(repository),
        "branch": _branch_payload(branch),
        "changed_files": [],
        "external_refs": [],
        "captured_at": captured_at,
        "metadata": {},
    }


def _commit_artifact(
    *,
    repository: RepositoryFact | None,
    branch: BranchFact | None,
    commit: CommitFact,
    captured_at: str,
    captured_by: str,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if commit.message_summary is not None:
        metadata["message_summary"] = commit.message_summary

    return {
        "id": f"artifact-commit-{commit.sha[:12]}",
        "type": "commit",
        "title": None,
        "description": "Attached by GitHub sync through canonical reevaluation.",
        "location": _derive_commit_location(repository, commit),
        "content_type": None,
        "external_id": f"commit-{commit.sha}",
        "commit_sha": commit.sha,
        "pull_request_number": None,
        "review_state": None,
        "provenance": {
            "source_system": "github",
            "source_type": "api",
            "source_id": f"commit/{commit.sha}",
            "captured_by": captured_by,
        },
        "verification_status": "verified",
        "repository": _repository_payload(repository),
        "branch": _branch_payload(branch),
        "changed_files": [],
        "external_refs": [],
        "captured_at": captured_at,
        "metadata": metadata,
    }


def _pull_request_artifact(
    *,
    repository: RepositoryFact | None,
    branch: BranchFact | None,
    pull_request: PullRequestFact,
    changed_files: ChangedFilesSummary | None,
    captured_at: str,
    captured_by: str,
) -> dict[str, Any]:
    return {
        "id": f"artifact-pr-{pull_request.number}",
        "type": "pull_request",
        "title": "GitHub pull request sync",
        "description": "Attached by GitHub sync through canonical reevaluation.",
        "location": _derive_pull_request_location(repository, pull_request),
        "content_type": None,
        "external_id": f"PR-{pull_request.number}",
        "commit_sha": None,
        "pull_request_number": pull_request.number,
        "review_state": pull_request.review_state,
        "provenance": {
            "source_system": "github",
            "source_type": "api",
            "source_id": f"pull/{pull_request.number}",
            "captured_by": captured_by,
        },
        "verification_status": "verified",
        "repository": _repository_payload(repository),
        "branch": _branch_payload(branch),
        "changed_files": _changed_files_payload(changed_files),
        "external_refs": [],
        "captured_at": captured_at,
        "metadata": {
            "pull_request_state": pull_request.state,
            "pull_request_merged": pull_request.merged,
        },
    }


def _changed_file_artifacts(
    *,
    repository: RepositoryFact | None,
    branch: BranchFact | None,
    commit: CommitFact | None,
    pull_request: PullRequestFact | None,
    changed_files: ChangedFilesSummary | None,
    captured_at: str,
    captured_by: str,
) -> tuple[dict[str, Any], ...]:
    if changed_files is None:
        return ()

    artifacts: list[dict[str, Any]] = []
    commit_sha = None
    if commit is not None:
        commit_sha = commit.sha
    elif branch is not None:
        commit_sha = branch.head_commit_sha

    for index, file_fact in enumerate(changed_files.files, start=1):
        artifacts.append(
            {
                "id": f"artifact-changed-file-{_artifact_id_suffix(file_fact.path)}-{index}",
                "type": "changed_file",
                "title": "GitHub changed-file sync",
                "description": "Attached by GitHub sync through canonical reevaluation.",
                "location": _derive_changed_file_location(
                    repository=repository,
                    branch=branch,
                    commit=commit,
                    path=file_fact.path,
                ),
                "content_type": None,
                "external_id": file_fact.path,
                "commit_sha": commit_sha,
                "pull_request_number": pull_request.number if pull_request is not None else None,
                "review_state": None,
                "provenance": {
                    "source_system": "github",
                    "source_type": "api",
                    "source_id": f"contents/{file_fact.path}",
                    "captured_by": captured_by,
                },
                "verification_status": "verified",
                "repository": _repository_payload(repository),
                "branch": _branch_payload(branch),
                "changed_files": [
                    {
                        "path": file_fact.path,
                        "change_type": file_fact.change_type,
                        "additions": file_fact.additions,
                        "deletions": file_fact.deletions,
                        "previous_path": file_fact.previous_path,
                    }
                ],
                "external_refs": [],
                "captured_at": captured_at,
                "metadata": {},
            }
        )
    return tuple(artifacts)


def _new_artifacts_from_github_facts(
    github_facts: GitHubArtifactFacts,
    *,
    captured_at: str,
    captured_by: str,
) -> tuple[dict[str, Any], ...]:
    artifacts: list[dict[str, Any]] = []
    repository = github_facts.repository
    branch = github_facts.branch
    commit = github_facts.commit
    pull_request = github_facts.pull_request

    if branch is not None:
        artifacts.append(
            _branch_artifact(
                repository=repository,
                branch=branch,
                captured_at=captured_at,
                captured_by=captured_by,
            )
        )
    if commit is not None:
        artifacts.append(
            _commit_artifact(
                repository=repository,
                branch=branch,
                commit=commit,
                captured_at=captured_at,
                captured_by=captured_by,
            )
        )
    if pull_request is not None:
        artifacts.append(
            _pull_request_artifact(
                repository=repository,
                branch=branch,
                pull_request=pull_request,
                changed_files=github_facts.changed_files,
                captured_at=captured_at,
                captured_by=captured_by,
            )
        )
    artifacts.extend(
        _changed_file_artifacts(
            repository=repository,
            branch=branch,
            commit=commit,
            pull_request=pull_request,
            changed_files=github_facts.changed_files,
            captured_at=captured_at,
            captured_by=captured_by,
        )
    )
    return tuple(artifacts)


def _validate_github_sync_contract(payload: Mapping[str, Any]) -> None:
    _require_string(payload.get("task_id"), field_name="task_id")
    _require_mapping(payload.get("github"), field_name="github")

    if _optional_boolean(payload.get("claimed_completion"), field_name="claimed_completion"):
        raise GitHubSyncInputError(
            "GitHub sync cannot claim completion; completion must flow through executor/reporting paths"
        )
    if _optional_boolean(payload.get("acceptance_criteria_satisfied"), field_name="acceptance_criteria_satisfied"):
        raise GitHubSyncInputError(
            "GitHub sync cannot assert acceptance_criteria_satisfied; completion policy remains separate from artifact sync"
        )
    runtime_facts = _optional_mapping(payload.get("runtime_facts"), field_name="runtime_facts")
    if runtime_facts:
        raise GitHubSyncInputError(
            "GitHub sync cannot submit runtime_facts; executor telemetry must flow through completion-claim paths"
        )
    if payload.get("completion_evidence") is not None:
        raise GitHubSyncInputError(
            "GitHub sync cannot submit completion_evidence; evidence validation remains Harness-owned"
        )
    if payload.get("review_request") is not None or payload.get("review_decision") is not None:
        raise GitHubSyncInputError("GitHub sync cannot submit review mutations")
    if payload.get("new_artifacts") is not None or payload.get("external_facts") is not None:
        raise GitHubSyncInputError(
            "GitHub sync cannot carry canonical new_artifacts or external_facts; use the GitHub-shaped sync fields only"
        )
    unresolved_conditions = payload.get("unresolved_conditions")
    if unresolved_conditions not in (None, [], ()):
        raise GitHubSyncInputError("GitHub sync cannot submit unresolved_conditions")
    _optional_mapping(payload.get("expected_code_context"), field_name="expected_code_context")
    _optional_string(payload.get("captured_at"), field_name="captured_at")
    _optional_string(payload.get("captured_by"), field_name="captured_by")


def translate_github_sync_reevaluation_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Translate a GitHub sync payload into a canonical ``POST /tasks/<id>/reevaluate`` body."""

    payload = _require_mapping(payload, field_name="github_sync_payload")
    _validate_github_sync_contract(payload)

    task_id = _require_string(payload.get("task_id"), field_name="task_id")
    github_payload = _require_mapping(payload.get("github"), field_name="github")
    expected_code_context = _optional_mapping(payload.get("expected_code_context"), field_name="expected_code_context")
    captured_at = _optional_string(payload.get("captured_at"), field_name="captured_at") or _iso_now()
    captured_by = _optional_string(payload.get("captured_by"), field_name="captured_by") or "github-sync"

    try:
        github_facts = translate_github_artifact_facts(github_payload)
        canonical_payload = {
            "request": {
                "external_facts": {
                    **({"expected_code_context": dict(expected_code_context)} if expected_code_context is not None else {}),
                    "github_facts": _to_jsonable(github_facts),
                },
                "new_artifacts": list(
                    _new_artifacts_from_github_facts(
                        github_facts,
                        captured_at=captured_at,
                        captured_by=captured_by,
                    )
                ),
                "claimed_completion": False,
                "acceptance_criteria_satisfied": False,
            }
        }
    except GitHubConnectorInputError as error:
        raise GitHubSyncInputError(str(error)) from error

    return {
        "task_id": task_id,
        "request": canonical_payload["request"],
    }


__all__ = [
    "GitHubSyncInputError",
    "translate_github_sync_reevaluation_payload",
]
