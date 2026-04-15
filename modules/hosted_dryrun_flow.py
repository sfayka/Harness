"""Operator helpers for low-friction hosted Harness dry runs.

This module automates the operator flow for a real hosted Harness run:

1. Fetch one Linear issue.
2. Submit it through canonical Linear ingress.
3. Save a local session record and render an exact Codex Cloud prompt.
4. Accept a GitHub PR URL after Codex Cloud completes.
5. Submit a completion claim and GitHub sync through canonical APIs.
6. Return the canonical inspection surfaces for the operator.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, parse, request


DEFAULT_HARNESS_BASE_URL = "https://harness-umber.vercel.app/backend"
DEFAULT_DASHBOARD_URL = "https://harness-umber.vercel.app/tasks"
DEFAULT_GITHUB_OWNER = "sfayka"
DEFAULT_GITHUB_REPO = "HARNESS-DRYRUN"
DEFAULT_GITHUB_HOST = "github.com"
DEFAULT_BASE_BRANCH = "main"
DEFAULT_TARGET_FILE = "docs/dry-run-proof.md"
DEFAULT_COMMIT_MESSAGE = "docs: add dry run proof"
DEFAULT_LABELS = ("linear", "dryrun", "codex-cloud")
LINEAR_API_URL = "https://api.linear.app/graphql"
GITHUB_API_URL = "https://api.github.com"


class DryRunFlowError(ValueError):
    """Raised when dry-run session input or remote state is invalid."""


@dataclass(frozen=True)
class RequestResult:
    status: int
    payload: dict[str, Any]


@dataclass(frozen=True)
class LinearIssueSnapshot:
    issue_id: str
    identifier: str
    title: str
    description: str
    priority: int | str | None
    state: dict[str, Any]
    project: dict[str, Any] | None


@dataclass(frozen=True)
class GitHubPullRequestSnapshot:
    owner: str
    repo: str
    number: int
    url: str
    state: str
    merged: bool
    branch_name: str
    base_branch: str
    commit_sha: str
    repository_node_id: str | None = None
    review_decision: str | None = None


@dataclass(frozen=True)
class GitHubCommitSnapshot:
    sha: str
    html_url: str
    message: str


@dataclass(frozen=True)
class GitHubChangedFile:
    filename: str
    status: str
    additions: int | None
    deletions: int | None
    previous_filename: str | None = None


@dataclass(frozen=True)
class DryRunSession:
    task_id: str
    linear_issue_id: str
    linear_issue_identifier: str
    linear_issue_title: str
    linear_issue_description: str
    harness_base_url: str = DEFAULT_HARNESS_BASE_URL
    dashboard_url: str = DEFAULT_DASHBOARD_URL
    github_host: str = DEFAULT_GITHUB_HOST
    github_owner: str = DEFAULT_GITHUB_OWNER
    github_repo: str = DEFAULT_GITHUB_REPO
    base_branch: str = DEFAULT_BASE_BRANCH
    target_file: str = DEFAULT_TARGET_FILE
    commit_message: str = DEFAULT_COMMIT_MESSAGE
    labels: tuple[str, ...] = DEFAULT_LABELS
    created_at: str = field(default_factory=lambda: isoformat_utc(now_utc()))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DryRunSession":
        labels = tuple(payload.get("labels") or DEFAULT_LABELS)
        return cls(
            task_id=str(payload["task_id"]),
            linear_issue_id=str(payload["linear_issue_id"]),
            linear_issue_identifier=str(payload["linear_issue_identifier"]),
            linear_issue_title=str(payload["linear_issue_title"]),
            linear_issue_description=str(payload["linear_issue_description"]),
            harness_base_url=str(payload.get("harness_base_url") or DEFAULT_HARNESS_BASE_URL),
            dashboard_url=str(payload.get("dashboard_url") or DEFAULT_DASHBOARD_URL),
            github_host=str(payload.get("github_host") or DEFAULT_GITHUB_HOST),
            github_owner=str(payload.get("github_owner") or DEFAULT_GITHUB_OWNER),
            github_repo=str(payload.get("github_repo") or DEFAULT_GITHUB_REPO),
            base_branch=str(payload.get("base_branch") or DEFAULT_BASE_BRANCH),
            target_file=str(payload.get("target_file") or DEFAULT_TARGET_FILE),
            commit_message=str(payload.get("commit_message") or DEFAULT_COMMIT_MESSAGE),
            labels=labels,
            created_at=str(payload.get("created_at") or isoformat_utc(now_utc())),
        )


class JsonHttpClient:
    """Tiny JSON client for public HTTP APIs."""

    def __init__(self, *, timeout_seconds: float = 20.0) -> None:
        self.timeout_seconds = timeout_seconds

    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> RequestResult:
        final_headers = dict(headers or {})
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            final_headers.setdefault("Content-Type", "application/json")

        req = request.Request(url, headers=final_headers, data=data, method=method)
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
                parsed = json.loads(raw) if raw else {}
                return RequestResult(status=response.status, payload=parsed)
        except error.HTTPError as http_error:
            try:
                raw = http_error.read().decode("utf-8")
                parsed = json.loads(raw) if raw else {}
            except Exception:
                parsed = {"error": f"HTTP {http_error.code}"}
            finally:
                http_error.close()
            return RequestResult(status=http_error.code, payload=parsed)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def isoformat_utc(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def compact_utc(value: datetime) -> str:
    return value.replace(microsecond=0).strftime("%Y%m%dT%H%M%SZ")


def task_id_for_issue(issue_identifier: str, *, at: datetime | None = None) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", issue_identifier.strip().lower()).strip("-")
    return f"dryrun-{slug}-{compact_utc(at or now_utc())}"


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_json_file(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_file(path: Path, payload: dict[str, Any]) -> None:
    ensure_directory(path.parent)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_linear_issue_query(issue_identifier: str) -> dict[str, Any]:
    return {
        "query": """
            query DryRunIssue($issueId: String!) {
              issue(id: $issueId) {
                id
                identifier
                title
                description
                priority
                state {
                  id
                  name
                  type
                }
                project {
                  id
                  name
                  teams {
                    nodes {
                      id
                      key
                      name
                    }
                  }
                }
              }
            }
        """,
        "variables": {"issueId": issue_identifier},
    }


def parse_linear_issue_response(payload: dict[str, Any]) -> LinearIssueSnapshot:
    issue = ((payload.get("data") or {}).get("issue")) or None
    if not isinstance(issue, dict):
        errors = payload.get("errors")
        if isinstance(errors, list) and errors:
            first = errors[0]
            if isinstance(first, dict) and first.get("message"):
                raise DryRunFlowError(str(first["message"]))
        raise DryRunFlowError("Linear issue lookup returned no issue")

    issue_id = str(issue.get("id") or "").strip()
    identifier = str(issue.get("identifier") or "").strip()
    title = str(issue.get("title") or "").strip()
    description = str(issue.get("description") or "").strip()
    if not issue_id or not identifier or not title or not description:
        raise DryRunFlowError("Linear issue lookup returned incomplete issue fields")

    state = issue.get("state")
    if not isinstance(state, dict):
        raise DryRunFlowError("Linear issue lookup returned no workflow state")

    project = issue.get("project")
    if project is not None and not isinstance(project, dict):
        raise DryRunFlowError("Linear issue lookup returned malformed project data")

    return LinearIssueSnapshot(
        issue_id=issue_id,
        identifier=identifier,
        title=title,
        description=description,
        priority=issue.get("priority"),
        state=state,
        project=project,
    )


def build_linear_ingress_payload(
    issue: LinearIssueSnapshot,
    *,
    task_id: str,
    github_owner: str,
    github_repo: str,
    github_host: str = DEFAULT_GITHUB_HOST,
    base_branch: str = DEFAULT_BASE_BRANCH,
    labels: tuple[str, ...] = DEFAULT_LABELS,
    target_file: str = DEFAULT_TARGET_FILE,
) -> dict[str, Any]:
    return {
        "issue": {
            "id": issue.issue_id,
            "identifier": issue.identifier,
            "title": issue.title,
            "description": issue.description,
        },
        "state": issue.state,
        "project": issue.project,
        "task_reference": {
            "harness_task_id": task_id,
            "external_ref": issue.identifier,
        },
        "labels": list(labels),
        "priority": issue.priority,
        "task_status": "dispatch_ready",
        "acceptance_criteria": [
            {
                "id": "artifact-proof",
                "description": "Completion is backed by a real branch, commit, and pull request in GitHub.",
                "required": True,
            },
            {
                "id": "target-file",
                "description": f"The pull request changes {target_file}.",
                "required": True,
            },
            {
                "id": "harness-sync",
                "description": "Harness ingests the completion claim and GitHub sync without relying on executor self-certification.",
                "required": True,
            },
        ],
        "external_facts": {
            "expected_code_context": {
                "repository_host": github_host,
                "repository_owner": github_owner,
                "repository_name": github_repo,
                "base_branch": base_branch,
            }
        },
        "claimed_completion": False,
        "acceptance_criteria_satisfied": False,
    }


def build_codex_cloud_prompt(session: DryRunSession) -> str:
    return f"""You are executing one real dry-run task for Harness.

Hard requirements:
- Print raw output for these commands first, in this exact order, with no commentary before them:
  1. `pwd`
  2. `git remote -v`
  3. `cat .codex-bootstrap-proof`
- If preflight is wrong or incomplete, stop and report `BLOCKED`.
- Work only in repository `{session.github_owner}/{session.github_repo}`.
- Make exactly one small change: create or update `{session.target_file}`.
- Use this exact commit message: `{session.commit_message}`
- Open a PR against `{session.base_branch}`.

Task context:
- Harness task id: `{session.task_id}`
- Linear issue: `{session.linear_issue_identifier}`
- Linear title: `{session.linear_issue_title}`
- Expected repository: `{session.github_owner}/{session.github_repo}`

File content requirements for `{session.target_file}`:
- Include the Harness task id `{session.task_id}`
- Include the Linear issue `{session.linear_issue_identifier}`
- State that this file exists to prove the dry-run produced a real artifact

When you finish, print only these final proof lines in exactly this format:
Repository: {session.github_owner}/{session.github_repo}
Branch: <branch-name>
Commit SHA: <40-char-sha>
PR URL: <https://github.com/.../pull/...>
"""


_GITHUB_PR_URL_RE = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)/pull/(?P<number>[1-9][0-9]*)/?$"
)


def parse_github_pull_request_url(url: str) -> tuple[str, str, int]:
    match = _GITHUB_PR_URL_RE.match(url.strip())
    if match is None:
        raise DryRunFlowError("PR URL must be a numeric GitHub pull request URL")
    return (
        match.group("owner"),
        match.group("repo"),
        int(match.group("number")),
    )


def summarize_pull_request_review_decision(reviews: list[dict[str, Any]]) -> str | None:
    latest_by_user: dict[int, str] = {}
    for review in reviews:
        if not isinstance(review, dict):
            continue
        user = review.get("user")
        state = str(review.get("state") or "").strip().upper()
        if not isinstance(user, dict) or not state:
            continue
        user_id = user.get("id")
        if not isinstance(user_id, int):
            continue
        latest_by_user[user_id] = state

    states = set(latest_by_user.values())
    if "CHANGES_REQUESTED" in states:
        return "changes_requested"
    if states and states.issubset({"APPROVED"}):
        return "approved"
    return None


def build_pull_request_snapshot(
    pull_payload: dict[str, Any],
    *,
    review_decision: str | None,
) -> GitHubPullRequestSnapshot:
    head = pull_payload.get("head")
    base = pull_payload.get("base")
    repo = pull_payload.get("base", {}).get("repo")
    if not isinstance(head, dict) or not isinstance(base, dict) or not isinstance(repo, dict):
        raise DryRunFlowError("GitHub pull request payload is missing branch metadata")

    owner = ((repo.get("owner") or {}).get("login")) if isinstance(repo.get("owner"), dict) else None
    repo_name = repo.get("name")
    number = pull_payload.get("number")
    html_url = pull_payload.get("html_url")
    state = pull_payload.get("state")
    branch_name = head.get("ref")
    base_branch = base.get("ref")
    head_sha = head.get("sha")
    if not all(isinstance(value, str) and value.strip() for value in (owner, repo_name, html_url, state, branch_name, base_branch, head_sha)):
        raise DryRunFlowError("GitHub pull request payload is missing required fields")
    if not isinstance(number, int) or number < 1:
        raise DryRunFlowError("GitHub pull request payload has invalid number")

    return GitHubPullRequestSnapshot(
        owner=owner.strip(),
        repo=repo_name.strip(),
        number=number,
        url=html_url.strip(),
        state=state.strip(),
        merged=bool(pull_payload.get("merged", False)),
        branch_name=branch_name.strip(),
        base_branch=base_branch.strip(),
        commit_sha=head_sha.strip(),
        repository_node_id=(str(repo.get("node_id")).strip() if repo.get("node_id") else None),
        review_decision=review_decision,
    )


def build_commit_snapshot(commit_payload: dict[str, Any]) -> GitHubCommitSnapshot:
    sha = str(commit_payload.get("sha") or "").strip()
    html_url = str(commit_payload.get("html_url") or "").strip()
    nested_commit = commit_payload.get("commit")
    message = ""
    if isinstance(nested_commit, dict):
        message = str(nested_commit.get("message") or "").strip()
    if not sha or not html_url or not message:
        raise DryRunFlowError("GitHub commit payload is missing required fields")
    return GitHubCommitSnapshot(sha=sha, html_url=html_url, message=message)


def build_changed_files(files_payload: list[dict[str, Any]]) -> tuple[GitHubChangedFile, ...]:
    files: list[GitHubChangedFile] = []
    for item in files_payload:
        if not isinstance(item, dict):
            continue
        filename = str(item.get("filename") or "").strip()
        status = str(item.get("status") or "").strip()
        if not filename or not status:
            continue
        additions = item.get("additions")
        deletions = item.get("deletions")
        files.append(
            GitHubChangedFile(
                filename=filename,
                status=status,
                additions=additions if isinstance(additions, int) else None,
                deletions=deletions if isinstance(deletions, int) else None,
                previous_filename=(str(item.get("previous_filename")).strip() if item.get("previous_filename") else None),
            )
        )
    if not files:
        raise DryRunFlowError("GitHub PR files lookup returned no changed files")
    return tuple(files)


def ensure_expected_file_present(
    changed_files: tuple[GitHubChangedFile, ...],
    *,
    expected_path: str,
) -> None:
    if not any(file.filename == expected_path for file in changed_files):
        raise DryRunFlowError(f"Expected changed file {expected_path!r} was not present in the PR")


def build_completion_claim_request(
    session: DryRunSession,
    pull_request: GitHubPullRequestSnapshot,
    commit: GitHubCommitSnapshot,
    *,
    at: datetime | None = None,
) -> dict[str, Any]:
    timestamp = isoformat_utc(at or now_utc())
    claim_token = compact_utc(at or now_utc()).lower()
    attempt_id = f"{pull_request.branch_name}:{commit.sha[:12]}"
    return {
        "request": {
            "completion_claim": {
                "claim_id": f"claim-{session.task_id}-{claim_token}",
                "reported_at": timestamp,
                "reported_by": "codex-cloud",
                "reason": "Codex Cloud reported completion with GitHub artifacts pending canonical sync.",
                "metadata": {"attempt_id": attempt_id},
            },
            "execution_attempt": {
                "attempt_id": attempt_id,
                "recorded_at": timestamp,
                "status": "succeeded",
                "reported_by": "codex-cloud",
                "artifact_references": [
                    {
                        "reference_id": f"{attempt_id}:commit",
                        "artifact_type": "commit",
                        "location": commit.html_url,
                        "commit_sha": commit.sha,
                        "metadata": {
                            "repository_host": session.github_host,
                            "repository_owner": session.github_owner,
                            "repository_name": session.github_repo,
                            "branch_name": pull_request.branch_name,
                            "commit_sha": commit.sha,
                        },
                    }
                ],
                "metadata": {
                    "executor_run_id": f"codex-cloud:{pull_request.branch_name}:{commit.sha[:12]}",
                    "pull_request_url": pull_request.url,
                },
            },
            "external_facts": {
                "expected_code_context": {
                    "repository_host": session.github_host,
                    "repository_owner": session.github_owner,
                    "repository_name": session.github_repo,
                    "branch_name": pull_request.branch_name,
                    "base_branch": pull_request.base_branch,
                }
            },
            "acceptance_criteria_satisfied": True,
            "runtime_facts": {
                "executor_reported_success": True,
                "attempt_count": 1,
            },
        }
    }


def build_github_sync_request(
    session: DryRunSession,
    pull_request: GitHubPullRequestSnapshot,
    commit: GitHubCommitSnapshot,
    changed_files: tuple[GitHubChangedFile, ...],
    *,
    at: datetime | None = None,
) -> dict[str, Any]:
    timestamp = isoformat_utc(at or now_utc())
    return {
        "task_id": session.task_id,
        "captured_at": timestamp,
        "expected_code_context": {
            "repository_host": session.github_host,
            "repository_owner": session.github_owner,
            "repository_name": session.github_repo,
            "branch_name": pull_request.branch_name,
            "base_branch": pull_request.base_branch,
        },
        "github": {
            "repository": {
                "host": session.github_host,
                "owner": session.github_owner,
                "name": session.github_repo,
                "node_id": pull_request.repository_node_id,
            },
            "branch": {
                "name": pull_request.branch_name,
                "baseRefName": pull_request.base_branch,
                "target": {"oid": commit.sha},
            },
            "commit": {
                "sha": commit.sha,
                "html_url": commit.html_url,
                "commit": {"message": commit.message},
            },
            "pull_request": {
                "number": pull_request.number,
                "state": pull_request.state,
                "reviewDecision": pull_request.review_decision,
                "html_url": pull_request.url,
                "merged": pull_request.merged,
            },
            "files": [
                {
                    "filename": file.filename,
                    "status": file.status,
                    "additions": file.additions,
                    "deletions": file.deletions,
                    **({"previous_filename": file.previous_filename} if file.previous_filename else {}),
                }
                for file in changed_files
            ],
        },
    }


def build_operator_summary(
    session: DryRunSession,
    *,
    read_model: dict[str, Any],
    timeline: dict[str, Any],
    evaluations: dict[str, Any],
) -> dict[str, Any]:
    return {
        "task_id": session.task_id,
        "dashboard_url": session.dashboard_url,
        "read_model_url": f"{session.harness_base_url}/tasks/{session.task_id}/read-model",
        "timeline_url": f"{session.harness_base_url}/tasks/{session.task_id}/timeline",
        "evaluations_url": f"{session.harness_base_url}/tasks/{session.task_id}/evaluations",
        "read_model": read_model,
        "timeline": timeline,
        "evaluations": evaluations,
    }


def fetch_linear_issue(
    client: JsonHttpClient,
    *,
    linear_token: str,
    issue_identifier: str,
) -> LinearIssueSnapshot:
    result = client.request_json(
        "POST",
        LINEAR_API_URL,
        headers={"Authorization": linear_token},
        payload=build_linear_issue_query(issue_identifier),
    )
    if result.status != 200:
        raise DryRunFlowError(f"Linear lookup failed with HTTP {result.status}")
    return parse_linear_issue_response(result.payload)


def fetch_github_pull_request_bundle(
    client: JsonHttpClient,
    *,
    github_token: str,
    pr_url: str,
) -> tuple[GitHubPullRequestSnapshot, GitHubCommitSnapshot, tuple[GitHubChangedFile, ...]]:
    owner, repo, number = parse_github_pull_request_url(pr_url)
    auth_headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {github_token}",
    }
    pr_result = client.request_json(
        "GET",
        f"{GITHUB_API_URL}/repos/{owner}/{repo}/pulls/{number}",
        headers=auth_headers,
    )
    if pr_result.status != 200:
        raise DryRunFlowError(f"GitHub PR lookup failed with HTTP {pr_result.status}")

    reviews_result = client.request_json(
        "GET",
        f"{GITHUB_API_URL}/repos/{owner}/{repo}/pulls/{number}/reviews",
        headers=auth_headers,
    )
    review_decision: str | None = None
    if reviews_result.status == 200 and isinstance(reviews_result.payload, list):
        review_decision = summarize_pull_request_review_decision(reviews_result.payload)

    pull_request = build_pull_request_snapshot(pr_result.payload, review_decision=review_decision)

    commit_result = client.request_json(
        "GET",
        f"{GITHUB_API_URL}/repos/{owner}/{repo}/commits/{parse.quote(pull_request.commit_sha, safe='')}",
        headers=auth_headers,
    )
    if commit_result.status != 200:
        raise DryRunFlowError(f"GitHub commit lookup failed with HTTP {commit_result.status}")

    files_result = client.request_json(
        "GET",
        f"{GITHUB_API_URL}/repos/{owner}/{repo}/pulls/{number}/files",
        headers=auth_headers,
    )
    if files_result.status != 200 or not isinstance(files_result.payload, list):
        raise DryRunFlowError(f"GitHub PR files lookup failed with HTTP {files_result.status}")

    return (
        pull_request,
        build_commit_snapshot(commit_result.payload),
        build_changed_files(files_result.payload),
    )


def post_linear_ingress(
    client: JsonHttpClient,
    *,
    session: DryRunSession,
    issue: LinearIssueSnapshot,
) -> RequestResult:
    payload = build_linear_ingress_payload(
        issue,
        task_id=session.task_id,
        github_owner=session.github_owner,
        github_repo=session.github_repo,
        github_host=session.github_host,
        base_branch=session.base_branch,
        labels=session.labels,
        target_file=session.target_file,
    )
    return client.request_json(
        "POST",
        f"{session.harness_base_url}/ingress/linear",
        payload=payload,
    )


def post_completion_claim(
    client: JsonHttpClient,
    *,
    session: DryRunSession,
    pull_request: GitHubPullRequestSnapshot,
    commit: GitHubCommitSnapshot,
) -> RequestResult:
    payload = build_completion_claim_request(session, pull_request, commit)
    return client.request_json(
        "POST",
        f"{session.harness_base_url}/tasks/{parse.quote(session.task_id, safe='')}/completion-claims",
        payload=payload,
    )


def post_github_sync(
    client: JsonHttpClient,
    *,
    session: DryRunSession,
    pull_request: GitHubPullRequestSnapshot,
    commit: GitHubCommitSnapshot,
    changed_files: tuple[GitHubChangedFile, ...],
) -> RequestResult:
    payload = build_github_sync_request(session, pull_request, commit, changed_files)
    return client.request_json(
        "POST",
        f"{session.harness_base_url}/sync/github",
        payload=payload,
    )


def fetch_task_inspection(
    client: JsonHttpClient,
    *,
    session: DryRunSession,
) -> dict[str, RequestResult]:
    base_path = f"{session.harness_base_url}/tasks/{parse.quote(session.task_id, safe='')}"
    return {
        "read_model": client.request_json("GET", f"{base_path}/read-model"),
        "timeline": client.request_json("GET", f"{base_path}/timeline"),
        "evaluations": client.request_json("GET", f"{base_path}/evaluations"),
    }


__all__ = [
    "DEFAULT_BASE_BRANCH",
    "DEFAULT_COMMIT_MESSAGE",
    "DEFAULT_DASHBOARD_URL",
    "DEFAULT_GITHUB_HOST",
    "DEFAULT_GITHUB_OWNER",
    "DEFAULT_GITHUB_REPO",
    "DEFAULT_HARNESS_BASE_URL",
    "DEFAULT_LABELS",
    "DEFAULT_TARGET_FILE",
    "DryRunFlowError",
    "DryRunSession",
    "GitHubChangedFile",
    "GitHubCommitSnapshot",
    "GitHubPullRequestSnapshot",
    "JsonHttpClient",
    "LinearIssueSnapshot",
    "RequestResult",
    "build_codex_cloud_prompt",
    "build_completion_claim_request",
    "build_github_sync_request",
    "build_linear_ingress_payload",
    "build_operator_summary",
    "build_pull_request_snapshot",
    "compact_utc",
    "ensure_directory",
    "ensure_expected_file_present",
    "fetch_github_pull_request_bundle",
    "fetch_linear_issue",
    "fetch_task_inspection",
    "isoformat_utc",
    "now_utc",
    "parse_github_pull_request_url",
    "parse_linear_issue_response",
    "post_completion_claim",
    "post_github_sync",
    "post_linear_ingress",
    "read_json_file",
    "summarize_pull_request_review_decision",
    "task_id_for_issue",
    "write_json_file",
]
