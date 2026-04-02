"""GitHub-backed validation for canonical artifact references."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Protocol
from urllib import error, parse, request

from modules.contracts.execution_advisory import ArtifactReference
from modules.contracts.task_envelope_external_facts import RepositoryFact


class GitHubArtifactValidationError(ValueError):
    """Raised when artifact validation inputs are malformed."""


@dataclass(frozen=True)
class GitHubArtifactValidationIssue:
    """Machine-readable issue emitted while validating one artifact reference."""

    code: str
    message: str
    reference_id: str
    artifact_type: str


@dataclass(frozen=True)
class GitHubArtifactValidationItemResult:
    """Validation result for one canonical artifact reference."""

    reference_id: str
    artifact_type: str
    exists: bool
    repository_matches: bool
    identity_matches: bool
    issues: tuple[GitHubArtifactValidationIssue, ...]


@dataclass(frozen=True)
class GitHubArtifactValidationResult:
    """Aggregate GitHub-backed validation results used as evidence input."""

    is_valid: bool
    item_results: tuple[GitHubArtifactValidationItemResult, ...]


class GitHubArtifactLookup(Protocol):
    """Lookup contract for resolving artifacts from GitHub."""

    def pull_request_exists(self, repository: RepositoryFact, number: int) -> bool: ...

    def commit_exists(self, repository: RepositoryFact, commit_sha: str) -> bool: ...

    def branch_exists(self, repository: RepositoryFact, branch_name: str) -> bool: ...


def _parse_github_location(location: str | None) -> tuple[str, str, str, str] | None:
    if location is None:
        return None
    parsed = parse.urlparse(location)
    if parsed.netloc != "github.com":
        return None

    segments = [segment for segment in parsed.path.split("/") if segment]
    if len(segments) < 4:
        return None
    owner, name, kind = segments[0], segments[1], segments[2]
    identifier = "/".join(segments[3:])
    return (owner, name, kind, identifier)


def _pull_request_number(reference: ArtifactReference) -> tuple[int | None, bool]:
    location_parts = _parse_github_location(reference.location)
    from_location: int | None = None
    if location_parts and location_parts[2] == "pull":
        try:
            from_location = int(location_parts[3])
        except ValueError:
            from_location = None

    from_external: int | None = None
    if reference.external_id:
        candidate = reference.external_id.strip()
        if candidate.upper().startswith("PR-"):
            candidate = candidate.split("-", 1)[1]
        try:
            from_external = int(candidate)
        except ValueError:
            from_external = None

    mismatch = from_location is not None and from_external is not None and from_location != from_external
    return (from_external or from_location, mismatch)


def _commit_sha(reference: ArtifactReference) -> tuple[str | None, bool]:
    location_parts = _parse_github_location(reference.location)
    from_location: str | None = None
    if location_parts and location_parts[2] == "commit":
        from_location = location_parts[3]

    from_reference = reference.commit_sha or reference.external_id
    if from_reference is not None:
        from_reference = from_reference.strip() or None

    mismatch = (
        from_location is not None
        and from_reference is not None
        and from_location.lower() != from_reference.lower()
    )
    return (from_reference or from_location, mismatch)


def _branch_name(reference: ArtifactReference) -> tuple[str | None, bool]:
    # Branch identifiers may only be representable in external_id.
    from_external = reference.external_id.strip() if reference.external_id else None
    location_parts = _parse_github_location(reference.location)
    from_location: str | None = None
    if location_parts and location_parts[2] == "tree":
        from_location = location_parts[3]

    mismatch = from_location is not None and from_external is not None and from_location != from_external
    return (from_external or from_location, mismatch)


def _repository_matches(reference: ArtifactReference, expected_repository: RepositoryFact) -> bool:
    location_parts = _parse_github_location(reference.location)
    if location_parts is None:
        return True
    owner, name, _, _ = location_parts
    return owner == expected_repository.owner and name == expected_repository.name


def validate_github_artifact_references(
    artifact_references: tuple[ArtifactReference, ...],
    *,
    expected_repository: RepositoryFact,
    lookup: GitHubArtifactLookup,
) -> GitHubArtifactValidationResult:
    """Validate canonical artifact references against real GitHub state."""

    if expected_repository.host != "github.com":
        raise GitHubArtifactValidationError("expected_repository.host must be github.com for GitHub-backed validation")

    results: list[GitHubArtifactValidationItemResult] = []

    for reference in artifact_references:
        issues: list[GitHubArtifactValidationIssue] = []
        repository_matches = _repository_matches(reference, expected_repository)
        if not repository_matches:
            issues.append(
                GitHubArtifactValidationIssue(
                    code="wrong_repository",
                    message="Artifact reference points to a different repository than expected",
                    reference_id=reference.reference_id,
                    artifact_type=reference.artifact_type,
                )
            )

        identity_matches = True
        exists = False
        artifact_type = reference.artifact_type

        if artifact_type == "pull_request":
            number, mismatch = _pull_request_number(reference)
            identity_matches = not mismatch
            if mismatch:
                issues.append(
                    GitHubArtifactValidationIssue(
                        code="mismatched_identifier",
                        message="Pull request reference has conflicting identifiers",
                        reference_id=reference.reference_id,
                        artifact_type=artifact_type,
                    )
                )
            if number is None:
                issues.append(
                    GitHubArtifactValidationIssue(
                        code="missing_identifier",
                        message="Pull request reference is missing a parseable pull request number",
                        reference_id=reference.reference_id,
                        artifact_type=artifact_type,
                    )
                )
            elif repository_matches:
                exists = lookup.pull_request_exists(expected_repository, number)

        elif artifact_type == "commit":
            sha, mismatch = _commit_sha(reference)
            identity_matches = not mismatch
            if mismatch:
                issues.append(
                    GitHubArtifactValidationIssue(
                        code="mismatched_identifier",
                        message="Commit reference has conflicting identifiers",
                        reference_id=reference.reference_id,
                        artifact_type=artifact_type,
                    )
                )
            if sha is None:
                issues.append(
                    GitHubArtifactValidationIssue(
                        code="missing_identifier",
                        message="Commit reference is missing commit sha",
                        reference_id=reference.reference_id,
                        artifact_type=artifact_type,
                    )
                )
            elif repository_matches:
                exists = lookup.commit_exists(expected_repository, sha)

        elif artifact_type == "branch":
            branch_name, mismatch = _branch_name(reference)
            identity_matches = not mismatch
            if mismatch:
                issues.append(
                    GitHubArtifactValidationIssue(
                        code="mismatched_identifier",
                        message="Branch reference has conflicting identifiers",
                        reference_id=reference.reference_id,
                        artifact_type=artifact_type,
                    )
                )
            if branch_name is None:
                issues.append(
                    GitHubArtifactValidationIssue(
                        code="missing_identifier",
                        message="Branch reference is missing branch name",
                        reference_id=reference.reference_id,
                        artifact_type=artifact_type,
                    )
                )
            elif repository_matches:
                exists = lookup.branch_exists(expected_repository, branch_name)
        else:
            issues.append(
                GitHubArtifactValidationIssue(
                    code="unsupported_artifact_type",
                    message=f"Artifact type {artifact_type!r} is not supported by GitHub-backed validator",
                    reference_id=reference.reference_id,
                    artifact_type=artifact_type,
                )
            )

        if not exists:
            issues.append(
                GitHubArtifactValidationIssue(
                    code="artifact_not_found",
                    message="GitHub artifact could not be resolved",
                    reference_id=reference.reference_id,
                    artifact_type=artifact_type,
                )
            )

        results.append(
            GitHubArtifactValidationItemResult(
                reference_id=reference.reference_id,
                artifact_type=artifact_type,
                exists=exists,
                repository_matches=repository_matches,
                identity_matches=identity_matches,
                issues=tuple(issues),
            )
        )

    return GitHubArtifactValidationResult(
        is_valid=all(item.exists and item.repository_matches and item.identity_matches for item in results),
        item_results=tuple(results),
    )


class GitHubRestArtifactLookup:
    """GitHub REST API-backed artifact lookup implementation."""

    def __init__(self, *, token: str | None = None, timeout_seconds: float = 10.0) -> None:
        self._token = token or os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
        self._timeout_seconds = timeout_seconds

    def _request_json(self, path: str) -> dict[str, Any] | None:
        url = f"https://api.github.com{path}"
        headers = {"Accept": "application/vnd.github+json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        req = request.Request(url=url, headers=headers)
        try:
            with request.urlopen(req, timeout=self._timeout_seconds) as response:
                payload = response.read().decode("utf-8")
                return json.loads(payload) if payload else {}
        except error.HTTPError as http_error:
            if http_error.code == 404:
                return None
            raise GitHubArtifactValidationError(f"GitHub lookup failed for {path}: HTTP {http_error.code}") from http_error
        except error.URLError as url_error:
            raise GitHubArtifactValidationError(f"GitHub lookup failed for {path}: {url_error.reason}") from url_error

    def pull_request_exists(self, repository: RepositoryFact, number: int) -> bool:
        response = self._request_json(f"/repos/{repository.owner}/{repository.name}/pulls/{number}")
        return response is not None

    def commit_exists(self, repository: RepositoryFact, commit_sha: str) -> bool:
        response = self._request_json(f"/repos/{repository.owner}/{repository.name}/commits/{commit_sha}")
        return response is not None

    def branch_exists(self, repository: RepositoryFact, branch_name: str) -> bool:
        safe_branch = parse.quote(branch_name, safe="")
        response = self._request_json(f"/repos/{repository.owner}/{repository.name}/branches/{safe_branch}")
        return response is not None


__all__ = [
    "GitHubArtifactLookup",
    "GitHubArtifactValidationError",
    "GitHubArtifactValidationIssue",
    "GitHubArtifactValidationItemResult",
    "GitHubArtifactValidationResult",
    "GitHubRestArtifactLookup",
    "validate_github_artifact_references",
]
