"""Normalized external fact models for GitHub and Linear."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class ExternalFactValidationError(ValueError):
    """Raised when normalized external fact models are malformed."""


def _require_non_empty(value: str | None, *, field_name: str) -> None:
    if value is None or not value.strip():
        raise ExternalFactValidationError(f"{field_name} is required")


@dataclass(frozen=True)
class RepositoryFact:
    """Normalized repository identity."""

    host: str
    owner: str
    name: str
    external_id: str | None = None


@dataclass(frozen=True)
class BranchFact:
    """Normalized branch identity."""

    name: str
    base_branch: str | None = None
    head_commit_sha: str | None = None


@dataclass(frozen=True)
class CommitFact:
    """Normalized commit reference."""

    sha: str
    url: str | None = None
    message_summary: str | None = None


@dataclass(frozen=True)
class PullRequestFact:
    """Normalized pull request presence/state."""

    number: int
    state: str | None = None
    review_state: str | None = None
    url: str | None = None
    merged: bool | None = None


@dataclass(frozen=True)
class ChangedFileFact:
    """Normalized changed-file summary entry."""

    path: str
    change_type: str
    additions: int | None = None
    deletions: int | None = None
    previous_path: str | None = None


@dataclass(frozen=True)
class ChangedFilesSummary:
    """Normalized changed-files summary for external facts."""

    files: tuple[ChangedFileFact, ...] = ()
    matches_expected_scope: bool | None = None


@dataclass(frozen=True)
class ArtifactReferenceFact:
    """External artifact reference relevant to completion/reconciliation."""

    artifact_type: str
    external_id: str
    url: str | None = None


@dataclass(frozen=True)
class GitHubArtifactFacts:
    """Normalized GitHub facts consumed by Harness policy code."""

    artifact_found: bool = True
    repository: RepositoryFact | None = None
    branch: BranchFact | None = None
    commit: CommitFact | None = None
    pull_request: PullRequestFact | None = None
    changed_files: ChangedFilesSummary | None = None
    artifact_refs: tuple[ArtifactReferenceFact, ...] = ()
    reasons: tuple[str, ...] = ()

    @property
    def repository_host(self) -> str | None:
        return self.repository.host if self.repository else None

    @property
    def repository_owner(self) -> str | None:
        return self.repository.owner if self.repository else None

    @property
    def repository_name(self) -> str | None:
        return self.repository.name if self.repository else None

    @property
    def branch_name(self) -> str | None:
        return self.branch.name if self.branch else None

    @property
    def pull_request_found(self) -> bool | None:
        return self.pull_request is not None

    @property
    def commit_found(self) -> bool | None:
        return self.commit is not None

    @property
    def review_state(self) -> str | None:
        return self.pull_request.review_state if self.pull_request else None

    @property
    def changed_files_match(self) -> bool | None:
        return self.changed_files.matches_expected_scope if self.changed_files else None


@dataclass(frozen=True)
class LinearProjectFact:
    """Normalized Linear project/workflow reference."""

    project_id: str
    project_name: str | None = None


@dataclass(frozen=True)
class LinearWorkflowFact:
    """Normalized Linear workflow/status reference."""

    workflow_id: str
    workflow_name: str
    state_type: str | None = None


@dataclass(frozen=True)
class LinearTaskReference:
    """Reference back from Linear to the Harness task identity."""

    harness_task_id: str | None = None
    external_ref: str | None = None


@dataclass(frozen=True)
class LinearFacts:
    """Normalized Linear facts consumed by Harness policy code."""

    record_found: bool = True
    issue_id: str | None = None
    issue_key: str | None = None
    state: str | None = None
    workflow: LinearWorkflowFact | None = None
    project: LinearProjectFact | None = None
    task_reference: LinearTaskReference | None = None
    reasons: tuple[str, ...] = ()


def validate_repository_fact(repository: RepositoryFact) -> RepositoryFact:
    """Validate repository identity."""

    _require_non_empty(repository.host, field_name="repository.host")
    _require_non_empty(repository.owner, field_name="repository.owner")
    _require_non_empty(repository.name, field_name="repository.name")
    return repository


def validate_branch_fact(branch: BranchFact) -> BranchFact:
    """Validate branch identity."""

    _require_non_empty(branch.name, field_name="branch.name")
    return branch


def validate_commit_fact(commit: CommitFact) -> CommitFact:
    """Validate commit reference."""

    _require_non_empty(commit.sha, field_name="commit.sha")
    return commit


def validate_pull_request_fact(pull_request: PullRequestFact) -> PullRequestFact:
    """Validate pull request reference."""

    if pull_request.number < 1:
        raise ExternalFactValidationError("pull_request.number must be >= 1")
    return pull_request


def validate_changed_files_summary(changed_files: ChangedFilesSummary) -> ChangedFilesSummary:
    """Validate changed-files summary."""

    for index, file_fact in enumerate(changed_files.files):
        _require_non_empty(file_fact.path, field_name=f"changed_files.files[{index}].path")
        _require_non_empty(file_fact.change_type, field_name=f"changed_files.files[{index}].change_type")
        if file_fact.additions is not None and file_fact.additions < 0:
            raise ExternalFactValidationError(f"changed_files.files[{index}].additions must be >= 0")
        if file_fact.deletions is not None and file_fact.deletions < 0:
            raise ExternalFactValidationError(f"changed_files.files[{index}].deletions must be >= 0")
    return changed_files


def validate_artifact_reference_fact(artifact_ref: ArtifactReferenceFact) -> ArtifactReferenceFact:
    """Validate external artifact reference."""

    _require_non_empty(artifact_ref.artifact_type, field_name="artifact_ref.artifact_type")
    _require_non_empty(artifact_ref.external_id, field_name="artifact_ref.external_id")
    return artifact_ref


def validate_github_facts(github_facts: GitHubArtifactFacts) -> GitHubArtifactFacts:
    """Validate normalized GitHub facts."""

    if not github_facts.artifact_found:
        if any(
            fact is not None
            for fact in (github_facts.repository, github_facts.branch, github_facts.commit, github_facts.pull_request)
        ):
            raise ExternalFactValidationError("artifact_found=False must not carry resolved GitHub artifact facts")
        return github_facts

    if github_facts.repository is not None:
        validate_repository_fact(github_facts.repository)
    if github_facts.branch is not None:
        validate_branch_fact(github_facts.branch)
    if github_facts.commit is not None:
        validate_commit_fact(github_facts.commit)
    if github_facts.pull_request is not None:
        validate_pull_request_fact(github_facts.pull_request)
    if github_facts.changed_files is not None:
        validate_changed_files_summary(github_facts.changed_files)
    for artifact_ref in github_facts.artifact_refs:
        validate_artifact_reference_fact(artifact_ref)

    if github_facts.branch is not None and github_facts.repository is None:
        raise ExternalFactValidationError("branch facts require repository identity")
    if github_facts.commit is not None and github_facts.repository is None:
        raise ExternalFactValidationError("commit facts require repository identity")
    if github_facts.pull_request is not None and github_facts.repository is None:
        raise ExternalFactValidationError("pull_request facts require repository identity")
    return github_facts


def validate_linear_facts(linear_facts: LinearFacts) -> LinearFacts:
    """Validate normalized Linear facts."""

    if not linear_facts.record_found:
        if any(
            value is not None
            for value in (
                linear_facts.issue_id,
                linear_facts.issue_key,
                linear_facts.state,
                linear_facts.workflow,
                linear_facts.project,
                linear_facts.task_reference,
            )
        ):
            raise ExternalFactValidationError("record_found=False must not carry resolved Linear record facts")
        return linear_facts

    if linear_facts.issue_id is None and linear_facts.issue_key is None:
        raise ExternalFactValidationError("Linear facts require issue_id or issue_key when record_found=True")
    if linear_facts.state is None:
        raise ExternalFactValidationError("Linear facts require state when record_found=True")
    if linear_facts.workflow is not None:
        _require_non_empty(linear_facts.workflow.workflow_id, field_name="linear.workflow.workflow_id")
        _require_non_empty(linear_facts.workflow.workflow_name, field_name="linear.workflow.workflow_name")
    if linear_facts.project is not None:
        _require_non_empty(linear_facts.project.project_id, field_name="linear.project.project_id")
    if linear_facts.task_reference is not None:
        if linear_facts.task_reference.harness_task_id is None and linear_facts.task_reference.external_ref is None:
            raise ExternalFactValidationError(
                "linear.task_reference requires harness_task_id or external_ref when provided"
            )
    return linear_facts


__all__ = [
    "ArtifactReferenceFact",
    "BranchFact",
    "ChangedFileFact",
    "ChangedFilesSummary",
    "CommitFact",
    "ExternalFactValidationError",
    "GitHubArtifactFacts",
    "LinearFacts",
    "LinearProjectFact",
    "LinearTaskReference",
    "LinearWorkflowFact",
    "PullRequestFact",
    "RepositoryFact",
    "validate_branch_fact",
    "validate_changed_files_summary",
    "validate_commit_fact",
    "validate_github_facts",
    "validate_linear_facts",
    "validate_pull_request_fact",
    "validate_repository_fact",
]
