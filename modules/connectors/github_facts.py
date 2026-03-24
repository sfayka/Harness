"""GitHub connector scaffolding that translates vendor-shaped inputs into normalized facts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from modules.contracts.task_envelope_external_facts import (
    ArtifactReferenceFact,
    BranchFact,
    ChangedFileFact,
    ChangedFilesSummary,
    CommitFact,
    ExternalFactValidationError,
    GitHubArtifactFacts,
    PullRequestFact,
    RepositoryFact,
    validate_github_facts,
)


class GitHubConnectorInputError(ValueError):
    """Raised when GitHub-shaped connector input is malformed."""


def _require_mapping(payload: Any, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise GitHubConnectorInputError(f"{field_name} must be a mapping")
    return payload


def _optional_mapping(payload: Any, *, field_name: str) -> Mapping[str, Any] | None:
    if payload is None:
        return None
    return _require_mapping(payload, field_name=field_name)


def _require_string(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GitHubConnectorInputError(f"{field_name} is required")
    return value.strip()


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise GitHubConnectorInputError("Expected string or null value")
    stripped = value.strip()
    return stripped or None


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise GitHubConnectorInputError("Expected bool or null value")
    return value


def _optional_int(value: Any, *, field_name: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int):
        raise GitHubConnectorInputError(f"{field_name} must be an integer")
    return value


def _extract_owner(repository_payload: Mapping[str, Any]) -> str:
    owner_value = repository_payload.get("owner")
    if isinstance(owner_value, Mapping):
        return _require_string(owner_value.get("login"), field_name="repository.owner.login")
    if isinstance(owner_value, str):
        return _require_string(owner_value, field_name="repository.owner")
    full_name = repository_payload.get("full_name")
    if isinstance(full_name, str) and "/" in full_name:
        owner, _ = full_name.split("/", 1)
        return _require_string(owner, field_name="repository.full_name.owner")
    raise GitHubConnectorInputError("repository owner is required")


def _extract_repository_name(repository_payload: Mapping[str, Any]) -> str:
    name_value = repository_payload.get("name")
    if isinstance(name_value, str) and name_value.strip():
        return name_value.strip()
    full_name = repository_payload.get("full_name")
    if isinstance(full_name, str) and "/" in full_name:
        _, name = full_name.split("/", 1)
        return _require_string(name, field_name="repository.full_name.name")
    raise GitHubConnectorInputError("repository name is required")


def _normalize_change_type(status: str) -> str:
    status_map = {
        "added": "added",
        "modified": "modified",
        "removed": "deleted",
        "deleted": "deleted",
        "renamed": "renamed",
        "copied": "copied",
        "changed": "modified",
    }
    return status_map.get(status, "unknown")


def translate_github_repository(repository_payload: Mapping[str, Any]) -> RepositoryFact:
    """Translate a GitHub-shaped repository payload into a normalized repository fact."""

    repository_payload = _require_mapping(repository_payload, field_name="repository")
    repository = RepositoryFact(
        host=_optional_string(repository_payload.get("host")) or "github.com",
        owner=_extract_owner(repository_payload),
        name=_extract_repository_name(repository_payload),
        external_id=_optional_string(repository_payload.get("node_id") or repository_payload.get("id")),
    )
    return repository


def translate_github_branch(branch_payload: Mapping[str, Any]) -> BranchFact:
    """Translate a GitHub-shaped branch payload into a normalized branch fact."""

    branch_payload = _require_mapping(branch_payload, field_name="branch")
    commit_payload = _optional_mapping(branch_payload.get("commit"), field_name="branch.commit")
    target_payload = _optional_mapping(branch_payload.get("target"), field_name="branch.target")
    branch = BranchFact(
        name=_require_string(branch_payload.get("name") or branch_payload.get("ref"), field_name="branch.name"),
        base_branch=_optional_string(branch_payload.get("base_branch") or branch_payload.get("baseRefName")),
        head_commit_sha=_optional_string(
            branch_payload.get("head_commit_sha")
            or (commit_payload or {}).get("sha")
            or (target_payload or {}).get("oid")
        ),
    )
    return branch


def translate_github_commit(commit_payload: Mapping[str, Any]) -> CommitFact:
    """Translate a GitHub-shaped commit payload into a normalized commit fact."""

    commit_payload = _require_mapping(commit_payload, field_name="commit")
    nested_commit = _optional_mapping(commit_payload.get("commit"), field_name="commit.commit")
    commit = CommitFact(
        sha=_require_string(commit_payload.get("sha") or commit_payload.get("oid"), field_name="commit.sha"),
        url=_optional_string(commit_payload.get("html_url") or commit_payload.get("url")),
        message_summary=_optional_string(
            (nested_commit or {}).get("message") or commit_payload.get("message") or commit_payload.get("messageHeadline")
        ),
    )
    return commit


def translate_github_pull_request(pull_request_payload: Mapping[str, Any]) -> PullRequestFact:
    """Translate a GitHub-shaped pull request payload into a normalized pull request fact."""

    pull_request_payload = _require_mapping(pull_request_payload, field_name="pull_request")
    number = _optional_int(pull_request_payload.get("number"), field_name="pull_request.number")
    if number is None:
        raise GitHubConnectorInputError("pull_request.number is required")
    return PullRequestFact(
        number=number,
        state=_optional_string(pull_request_payload.get("state")),
        review_state=_optional_string(
            pull_request_payload.get("review_state")
            or pull_request_payload.get("reviewDecision")
            or pull_request_payload.get("review_decision")
        ),
        url=_optional_string(pull_request_payload.get("html_url") or pull_request_payload.get("url")),
        merged=_optional_bool(pull_request_payload.get("merged")),
    )


def translate_github_changed_files(files_payload: Sequence[Mapping[str, Any]] | None) -> ChangedFilesSummary | None:
    """Translate GitHub-shaped changed-file payloads into a normalized summary."""

    if files_payload is None:
        return None
    if not isinstance(files_payload, Sequence) or isinstance(files_payload, (str, bytes, bytearray)):
        raise GitHubConnectorInputError("files must be a sequence of mappings")

    files: list[ChangedFileFact] = []
    for index, file_payload in enumerate(files_payload):
        file_mapping = _require_mapping(file_payload, field_name=f"files[{index}]")
        status = _optional_string(file_mapping.get("status")) or "unknown"
        additions = _optional_int(file_mapping.get("additions"), field_name=f"files[{index}].additions")
        deletions = _optional_int(file_mapping.get("deletions"), field_name=f"files[{index}].deletions")
        files.append(
            ChangedFileFact(
                path=_require_string(file_mapping.get("filename") or file_mapping.get("path"), field_name=f"files[{index}].filename"),
                change_type=_normalize_change_type(status),
                additions=additions,
                deletions=deletions,
                previous_path=_optional_string(file_mapping.get("previous_filename") or file_mapping.get("previous_path")),
            )
        )

    return ChangedFilesSummary(files=tuple(files))


def translate_github_artifact_references(payload: Mapping[str, Any]) -> tuple[ArtifactReferenceFact, ...]:
    """Translate GitHub-shaped commit/PR references into normalized artifact refs."""

    payload = _require_mapping(payload, field_name="github_payload")
    refs: list[ArtifactReferenceFact] = []

    pull_request_payload = _optional_mapping(payload.get("pull_request"), field_name="pull_request")
    if pull_request_payload is not None:
        pull_request = translate_github_pull_request(pull_request_payload)
        refs.append(
            ArtifactReferenceFact(
                artifact_type="pull_request",
                external_id=f"PR-{pull_request.number}",
                url=pull_request.url,
            )
        )

    commit_payload = _optional_mapping(payload.get("commit"), field_name="commit")
    if commit_payload is not None:
        commit = translate_github_commit(commit_payload)
        refs.append(
            ArtifactReferenceFact(
                artifact_type="commit",
                external_id=commit.sha,
                url=commit.url,
            )
        )

    return tuple(refs)


def translate_github_artifact_facts(payload: Mapping[str, Any]) -> GitHubArtifactFacts:
    """Translate a GitHub-shaped payload bundle into validated normalized facts."""

    payload = _require_mapping(payload, field_name="github_payload")
    artifact_found = payload.get("artifact_found", True)
    if not isinstance(artifact_found, bool):
        raise GitHubConnectorInputError("artifact_found must be a boolean")

    repository_payload = _optional_mapping(payload.get("repository"), field_name="repository")
    branch_payload = _optional_mapping(payload.get("branch"), field_name="branch")
    commit_payload = _optional_mapping(payload.get("commit"), field_name="commit")
    pull_request_payload = _optional_mapping(payload.get("pull_request"), field_name="pull_request")
    changed_files_payload = payload.get("files")

    github_facts = GitHubArtifactFacts(
        artifact_found=artifact_found,
        repository=translate_github_repository(repository_payload) if repository_payload is not None else None,
        branch=translate_github_branch(branch_payload) if branch_payload is not None else None,
        commit=translate_github_commit(commit_payload) if commit_payload is not None else None,
        pull_request=translate_github_pull_request(pull_request_payload) if pull_request_payload is not None else None,
        changed_files=translate_github_changed_files(changed_files_payload),
        artifact_refs=translate_github_artifact_references(payload),
        reasons=tuple(payload.get("reasons", ())),
    )

    try:
        return validate_github_facts(github_facts)
    except ExternalFactValidationError as error:
        raise GitHubConnectorInputError(str(error)) from error


__all__ = [
    "GitHubConnectorInputError",
    "translate_github_artifact_facts",
    "translate_github_artifact_references",
    "translate_github_branch",
    "translate_github_changed_files",
    "translate_github_commit",
    "translate_github_pull_request",
    "translate_github_repository",
]
