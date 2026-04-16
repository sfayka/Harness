"""Proof parsing for reset-slice worker completion output."""

from __future__ import annotations

import re
from dataclasses import dataclass


class ResetWorkerProofError(ValueError):
    """Raised when worker proof output is incomplete or malformed."""


@dataclass(frozen=True)
class ResetWorkerProof:
    repository_owner: str
    repository_name: str
    branch_name: str
    commit_sha: str
    pull_request_number: int
    pull_request_url: str


_REPOSITORY_RE = re.compile(
    r"^\s*Repository:\s*(?P<repository>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)\s*$",
    re.MULTILINE,
)
_BRANCH_RE = re.compile(r"^\s*Branch:\s*(?P<branch>.+?)\s*$", re.MULTILINE)
_COMMIT_SHA_RE = re.compile(r"^\s*Commit SHA:\s*(?P<sha>[0-9a-fA-F]{40})\s*$", re.MULTILINE)
_PR_URL_RE = re.compile(
    r"^\s*PR URL:\s*(?P<url>https://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)/pull/(?P<number>[1-9][0-9]*))/?\s*$",
    re.MULTILINE,
)


def _match_required(pattern: re.Pattern[str], payload: str, *, field_name: str) -> re.Match[str]:
    match = pattern.search(payload)
    if match is None:
        raise ResetWorkerProofError(f"{field_name} is required in worker proof output")
    return match


def parse_worker_proof_output(raw_output: str) -> ResetWorkerProof:
    if not isinstance(raw_output, str) or not raw_output.strip():
        raise ResetWorkerProofError("worker proof output is empty")

    repository_match = _match_required(_REPOSITORY_RE, raw_output, field_name="Repository")
    branch_match = _match_required(_BRANCH_RE, raw_output, field_name="Branch")
    commit_match = _match_required(_COMMIT_SHA_RE, raw_output, field_name="Commit SHA")
    pr_url_match = _match_required(_PR_URL_RE, raw_output, field_name="PR URL")

    repository_owner, repository_name = repository_match.group("repository").split("/", 1)
    pr_owner = pr_url_match.group("owner")
    pr_repo = pr_url_match.group("repo")
    if repository_owner != pr_owner or repository_name != pr_repo:
        raise ResetWorkerProofError("PR URL repository does not match Repository proof line")

    return ResetWorkerProof(
        repository_owner=repository_owner,
        repository_name=repository_name,
        branch_name=branch_match.group("branch").strip(),
        commit_sha=commit_match.group("sha").lower(),
        pull_request_number=int(pr_url_match.group("number")),
        pull_request_url=pr_url_match.group("url"),
    )


__all__ = ["ResetWorkerProof", "ResetWorkerProofError", "parse_worker_proof_output"]
