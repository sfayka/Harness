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
from .linear_facts import (
    LinearConnectorInputError,
    translate_linear_facts,
    translate_linear_project,
    translate_linear_task_reference,
    translate_linear_workflow,
)
from .linear_ingress import (
    LinearIngressInputError,
    translate_linear_submission_payload,
)

__all__ = [
    "GitHubConnectorInputError",
    "LinearConnectorInputError",
    "LinearIngressInputError",
    "translate_github_artifact_facts",
    "translate_github_artifact_references",
    "translate_github_branch",
    "translate_github_changed_files",
    "translate_github_commit",
    "translate_github_pull_request",
    "translate_github_repository",
    "translate_linear_facts",
    "translate_linear_submission_payload",
    "translate_linear_project",
    "translate_linear_task_reference",
    "translate_linear_workflow",
]
