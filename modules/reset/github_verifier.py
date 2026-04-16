"""Strict GitHub proof verification for the reset slice."""

from __future__ import annotations

import json
import os
import re
import ssl
from dataclasses import dataclass
from typing import Any, Protocol
from urllib import error, parse, request


class ResetGitHubVerificationError(ValueError):
    """Raised when GitHub verification cannot be executed."""


@dataclass(frozen=True)
class ResetGitHubVerdict:
    status: str
    reason: str
    details: dict[str, Any] | None = None


class ResetGitHubClient(Protocol):
    def branch_exists(self, owner: str, repo: str, branch_name: str) -> bool: ...

    def commit_exists(self, owner: str, repo: str, commit_sha: str) -> bool: ...

    def get_pull_request(self, owner: str, repo: str, pull_request_number: int) -> dict[str, Any] | None: ...


class GitHubRestResetClient:
    """Minimal GitHub REST client used by the reset verifier."""

    def __init__(self, *, token: str | None = None, timeout_seconds: float = 10.0) -> None:
        self.token = token or os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
        self.timeout_seconds = timeout_seconds
        self.ssl_context = _build_ssl_context()

    def _request_json(self, path: str) -> dict[str, Any] | None:
        headers = {"Accept": "application/vnd.github+json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = request.Request(f"https://api.github.com{path}", headers=headers)
        try:
            with request.urlopen(req, timeout=self.timeout_seconds, context=self.ssl_context) as response:
                payload = response.read().decode("utf-8")
                return json.loads(payload) if payload else {}
        except error.HTTPError as http_error:
            if http_error.code in {404, 422}:
                return None
            raise ResetGitHubVerificationError(f"GitHub request failed for {path}: HTTP {http_error.code}") from http_error
        except error.URLError as url_error:
            raise ResetGitHubVerificationError(f"GitHub request failed for {path}: {url_error.reason}") from url_error

    def branch_exists(self, owner: str, repo: str, branch_name: str) -> bool:
        safe_branch = parse.quote(branch_name, safe="")
        return self._request_json(f"/repos/{owner}/{repo}/branches/{safe_branch}") is not None

    def commit_exists(self, owner: str, repo: str, commit_sha: str) -> bool:
        return self._request_json(f"/repos/{owner}/{repo}/commits/{commit_sha}") is not None

    def get_pull_request(self, owner: str, repo: str, pull_request_number: int) -> dict[str, Any] | None:
        return self._request_json(f"/repos/{owner}/{repo}/pulls/{pull_request_number}")


class ResetGitHubVerifier:
    """Strict GitHub verification against the operator's acceptance bar."""

    def __init__(self, client: ResetGitHubClient | None = None) -> None:
        self.client = client or GitHubRestResetClient()

    def verify(
        self,
        *,
        expected_owner: str,
        expected_repo: str,
        expected_branch: str,
        branch_name: str,
        commit_sha: str,
        pull_request_number: int | None = None,
        pull_request_url: str | None = None,
        claimed_owner: str | None = None,
        claimed_repo: str | None = None,
    ) -> ResetGitHubVerdict:
        if claimed_owner is not None and claimed_owner != expected_owner:
            return ResetGitHubVerdict("retryable_invalid_proof", "claimed repository owner does not match the contract")
        if claimed_repo is not None and claimed_repo != expected_repo:
            return ResetGitHubVerdict("retryable_invalid_proof", "claimed repository name does not match the contract")
        if branch_name != expected_branch:
            return ResetGitHubVerdict("retryable_invalid_proof", "claimed branch does not match the contract")
        if not (pull_request_url or "").strip():
            return ResetGitHubVerdict("retryable_invalid_proof", "pull request url is required for verification")
        if not self.client.branch_exists(expected_owner, expected_repo, branch_name):
            return ResetGitHubVerdict("retryable_invalid_proof", "remote branch does not exist in the expected repository")
        if not self.client.commit_exists(expected_owner, expected_repo, commit_sha):
            return ResetGitHubVerdict("retryable_invalid_proof", "commit sha does not exist in the expected repository")
        if pull_request_number is None:
            derived_number = _parse_pull_request_number(pull_request_url)
            if derived_number is None:
                return ResetGitHubVerdict("retryable_invalid_proof", "pull request number is required for verification")
            pull_request_number = derived_number

        pull_request = self.client.get_pull_request(expected_owner, expected_repo, pull_request_number)
        if pull_request is None:
            return ResetGitHubVerdict("retryable_invalid_proof", "pull request does not exist in the expected repository")

        if pull_request_url and pull_request.get("html_url") != pull_request_url:
            return ResetGitHubVerdict("retryable_invalid_proof", "pull request url does not match the claimed pull request")

        head = pull_request.get("head") or {}
        head_repo = head.get("repo") or {}
        head_owner = ((head_repo.get("owner") or {}).get("login") or "").strip()
        head_repo_name = (head_repo.get("name") or "").strip()
        head_ref = (head.get("ref") or "").strip()
        head_sha = (head.get("sha") or "").strip()

        if head_owner != expected_owner or head_repo_name != expected_repo:
            return ResetGitHubVerdict("retryable_invalid_proof", "pull request head repository does not match the contract")
        if head_ref != branch_name:
            return ResetGitHubVerdict("retryable_invalid_proof", "pull request head branch does not match the claim")
        if head_sha.lower() != commit_sha.lower():
            return ResetGitHubVerdict("retryable_invalid_proof", "pull request head sha does not match the claim")

        state = (pull_request.get("state") or "").strip().lower()
        merged_at = pull_request.get("merged_at")
        if state == "closed" and merged_at is None:
            return ResetGitHubVerdict("retryable_invalid_proof", "pull request is closed without being merged")

        return ResetGitHubVerdict(
            "verified_done",
            "github proof verified",
            details={
                "pull_request_number": pull_request_number,
                "pull_request_url": pull_request.get("html_url"),
                "branch_name": head_ref,
                "commit_sha": head_sha,
                "state": state,
            },
        )


_PULL_REQUEST_URL_RE = re.compile(r"/pull/(?P<number>[1-9][0-9]*)/?$")


def _parse_pull_request_number(pull_request_url: str | None) -> int | None:
    if not isinstance(pull_request_url, str):
        return None
    match = _PULL_REQUEST_URL_RE.search(pull_request_url.strip())
    if match is None:
        return None
    return int(match.group("number"))


def _build_ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    try:
        import certifi  # type: ignore
    except ImportError:
        return context
    return ssl.create_default_context(cafile=certifi.where())


__all__ = [
    "GitHubRestResetClient",
    "ResetGitHubVerificationError",
    "ResetGitHubVerifier",
    "ResetGitHubVerdict",
]
