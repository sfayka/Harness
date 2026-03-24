"""Connector scaffolding for external-system translation."""

from .github_facts import (
    GitHubConnectorInputError,
    translate_github_artifact_facts,
    translate_github_artifact_references,
    translate_github_branch,
    translate_github_changed_files,
    translate_github_commit,
    translate_github_pull_request,
    translate_github_repository,
)

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
