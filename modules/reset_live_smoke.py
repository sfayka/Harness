"""Live smoke runner for reset verification against real Linear and GitHub."""

from __future__ import annotations

import argparse
import base64
import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import parse

from modules.hosted_dryrun_flow import JsonHttpClient
from modules.local_env import load_native_local_env
from modules.reset.contracts import ResetCompletionClaim, ResetVerificationContract
from modules.reset.github_verifier import ResetGitHubVerifier
from modules.reset.linear_client import LinearResetClient
from modules.reset.service import ResetVerificationService
from modules.reset.store import FileBackedResetStore

load_native_local_env()


DEFAULT_LINEAR_PROJECT_NAME = "HARNESS-DRYRUN"
DEFAULT_GITHUB_OWNER = "sfayka"
DEFAULT_GITHUB_REPO = "HARNESS-DRYRUN"
DEFAULT_BASE_BRANCH = "main"


class LiveResetSmokeError(ValueError):
    """Raised when live smoke setup or execution fails."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _compact_timestamp() -> str:
    return _utc_now().strftime("%Y%m%dT%H%M%SZ").lower()


@dataclass(frozen=True)
class LiveLinearProject:
    id: str
    name: str
    team_id: str
    team_key: str


@dataclass(frozen=True)
class LiveLinearIssue:
    id: str
    identifier: str
    url: str
    title: str
    state_name: str


@dataclass(frozen=True)
class LiveGitHubArtifact:
    owner: str
    repo: str
    branch_name: str
    commit_sha: str
    pull_request_number: int
    pull_request_url: str


@dataclass(frozen=True)
class LiveResetScenarioResult:
    name: str
    contract_id: str
    linear_issue_id: str
    linear_issue_identifier: str
    linear_issue_url: str
    pull_request_url: str
    branch_name: str
    commit_sha: str
    claim_verdict: str
    latest_reason: str | None
    final_harness_status: str
    final_linear_state: str
    repair_request_count: int
    tick_verdicts: tuple[str, ...] = ()


@dataclass(frozen=True)
class LiveResetSmokeSuiteResult:
    happy_path: LiveResetScenarioResult
    missing_pull_request: LiveResetScenarioResult
    wrong_sha_review: LiveResetScenarioResult


class _RecordingOpenClawClient:
    def __init__(self) -> None:
        self.repairs: list[tuple[str, str, str | None]] = []

    def request_repair(self, issue_id: str, *, reason: str, contract_id: str | None = None) -> None:
        self.repairs.append((issue_id, reason, contract_id))


class _LiveLinearClient:
    def __init__(self, *, api_key: str | None = None, http: JsonHttpClient | None = None) -> None:
        self.api_key = api_key or os.getenv("LINEAR_API_KEY")
        if not self.api_key:
            raise LiveResetSmokeError("LINEAR_API_KEY is required for live reset smoke tests")
        self.http = http or JsonHttpClient()

    def _graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        result = self.http.request_json(
            "POST",
            "https://api.linear.app/graphql",
            headers={"Authorization": self.api_key},
            payload={"query": query, "variables": variables},
        )
        if result.status >= 400:
            raise LiveResetSmokeError(f"Linear request failed with HTTP {result.status}: {result.payload}")
        if result.payload.get("errors"):
            raise LiveResetSmokeError(f"Linear GraphQL error: {result.payload['errors']}")
        data = result.payload.get("data")
        if not isinstance(data, dict):
            raise LiveResetSmokeError("Linear GraphQL response did not contain a data object")
        return data

    def resolve_project(self, project_name: str) -> LiveLinearProject:
        query = """
        query ProjectLookup($name: String!) {
          projects(filter: { name: { eq: $name } }) {
            nodes {
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
        """
        payload = self._graphql(query, {"name": project_name})
        projects = ((payload.get("projects") or {}).get("nodes")) or []
        if not projects:
            raise LiveResetSmokeError(f"Linear project {project_name!r} was not found")
        project = projects[0]
        teams = ((project.get("teams") or {}).get("nodes")) or []
        if not teams:
            raise LiveResetSmokeError(f"Linear project {project_name!r} has no attached team")
        team = teams[0]
        return LiveLinearProject(
            id=str(project["id"]),
            name=str(project["name"]),
            team_id=str(team["id"]),
            team_key=str(team["key"]),
        )

    def create_issue(self, *, project: LiveLinearProject, title: str, description: str) -> LiveLinearIssue:
        mutation = """
        mutation IssueCreate($input: IssueCreateInput!) {
          issueCreate(input: $input) {
            success
            issue {
              id
              identifier
              url
              title
              state { name }
            }
          }
        }
        """
        payload = self._graphql(
            mutation,
            {
                "input": {
                    "teamId": project.team_id,
                    "projectId": project.id,
                    "title": title,
                    "description": description,
                }
            },
        )
        issue = ((payload.get("issueCreate") or {}).get("issue")) or None
        if not isinstance(issue, dict):
            raise LiveResetSmokeError("Linear issueCreate did not return an issue")
        return LiveLinearIssue(
            id=str(issue["id"]),
            identifier=str(issue["identifier"]),
            url=str(issue["url"]),
            title=str(issue["title"]),
            state_name=str(((issue.get("state") or {}).get("name")) or ""),
        )

    def get_issue(self, issue_id: str) -> LiveLinearIssue:
        query = """
        query IssueLookup($id: String!) {
          issue(id: $id) {
            id
            identifier
            url
            title
            state { name }
          }
        }
        """
        payload = self._graphql(query, {"id": issue_id})
        issue = payload.get("issue")
        if not isinstance(issue, dict):
            raise LiveResetSmokeError(f"Linear issue {issue_id!r} was not found")
        return LiveLinearIssue(
            id=str(issue["id"]),
            identifier=str(issue["identifier"]),
            url=str(issue["url"]),
            title=str(issue["title"]),
            state_name=str(((issue.get("state") or {}).get("name")) or ""),
        )

    def wait_for_issue_state(
        self,
        issue_id: str,
        *,
        expected_state: str,
        timeout_seconds: float = 30.0,
        interval_seconds: float = 0.5,
    ) -> LiveLinearIssue:
        deadline = time.time() + timeout_seconds
        latest = self.get_issue(issue_id)
        while latest.state_name != expected_state and time.time() < deadline:
            time.sleep(interval_seconds)
            latest = self.get_issue(issue_id)
        if latest.state_name != expected_state:
            raise LiveResetSmokeError(
                f"Linear issue {latest.identifier} did not reach state {expected_state!r}; current state is {latest.state_name!r}"
            )
        return latest


class _LiveGitHubClient:
    def __init__(self, *, token: str | None = None, http: JsonHttpClient | None = None) -> None:
        self.token = token or os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
        if not self.token:
            raise LiveResetSmokeError("GITHUB_TOKEN or GH_TOKEN is required for live reset smoke tests")
        self.http = http or JsonHttpClient()

    def _request(self, method: str, path: str, *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        result = self.http.request_json(
            method,
            f"https://api.github.com{path}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
            },
            payload=payload,
        )
        if result.status >= 400:
            raise LiveResetSmokeError(f"GitHub request failed for {path}: HTTP {result.status}: {result.payload}")
        return result.payload

    def get_repository(self, owner: str, repo: str) -> dict[str, Any]:
        return self._request("GET", f"/repos/{owner}/{repo}")

    def get_ref_sha(self, owner: str, repo: str, ref_name: str) -> str:
        payload = self._request("GET", f"/repos/{owner}/{repo}/git/ref/heads/{parse.quote(ref_name, safe='')}")
        sha = ((payload.get("object") or {}).get("sha")) or ""
        if not isinstance(sha, str) or not sha:
            raise LiveResetSmokeError(f"GitHub ref lookup for {owner}/{repo}:{ref_name} returned no SHA")
        return sha

    def create_branch(self, owner: str, repo: str, *, branch_name: str, from_sha: str) -> None:
        self._request(
            "POST",
            f"/repos/{owner}/{repo}/git/refs",
            payload={"ref": f"refs/heads/{branch_name}", "sha": from_sha},
        )

    def create_file_commit(
        self,
        owner: str,
        repo: str,
        *,
        branch_name: str,
        file_path: str,
        content: str,
        commit_message: str,
    ) -> str:
        payload = self._request(
            "PUT",
            f"/repos/{owner}/{repo}/contents/{parse.quote(file_path, safe='/')}",
            payload={
                "message": commit_message,
                "branch": branch_name,
                "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
            },
        )
        commit_sha = ((payload.get("commit") or {}).get("sha")) or ""
        if not isinstance(commit_sha, str) or not commit_sha:
            raise LiveResetSmokeError("GitHub file commit did not return a commit SHA")
        return commit_sha

    def create_pull_request(
        self,
        owner: str,
        repo: str,
        *,
        title: str,
        body: str,
        head: str,
        base: str,
    ) -> tuple[int, str]:
        payload = self._request(
            "POST",
            f"/repos/{owner}/{repo}/pulls",
            payload={"title": title, "body": body, "head": head, "base": base},
        )
        number = int(payload["number"])
        url = str(payload["html_url"])
        return number, url

    def create_artifact(
        self,
        *,
        owner: str,
        repo: str,
        base_branch: str,
        branch_name: str,
        file_path: str,
        file_content: str,
        commit_message: str,
        pull_request_title: str,
        pull_request_body: str,
    ) -> LiveGitHubArtifact:
        from_sha = self.get_ref_sha(owner, repo, base_branch)
        self.create_branch(owner, repo, branch_name=branch_name, from_sha=from_sha)
        commit_sha = self.create_file_commit(
            owner,
            repo,
            branch_name=branch_name,
            file_path=file_path,
            content=file_content,
            commit_message=commit_message,
        )
        pull_request_number, pull_request_url = self.create_pull_request(
            owner,
            repo,
            title=pull_request_title,
            body=pull_request_body,
            head=branch_name,
            base=base_branch,
        )
        return LiveGitHubArtifact(
            owner=owner,
            repo=repo,
            branch_name=branch_name,
            commit_sha=commit_sha,
            pull_request_number=pull_request_number,
            pull_request_url=pull_request_url,
        )


def _make_service(*, store_root: str | Path) -> tuple[ResetVerificationService, _RecordingOpenClawClient]:
    openclaw = _RecordingOpenClawClient()
    service = ResetVerificationService(
        store=FileBackedResetStore(store_root),
        linear_client=LinearResetClient(),
        verifier=ResetGitHubVerifier(),
        openclaw_client=openclaw,
        retry_cooldown_seconds=0,
    )
    return service, openclaw


def _make_isolated_service(name: str) -> tuple[ResetVerificationService, _RecordingOpenClawClient]:
    store_root = Path(".harness-live-reset-smoke") / f"{name}-{_compact_timestamp()}"
    store_root.mkdir(parents=True, exist_ok=True)
    return _make_service(store_root=store_root)


def _make_contract_id(name: str) -> str:
    return f"live-reset-{name}-{_compact_timestamp()}"


def _issue_title(name: str) -> str:
    return f"[Harness Live Smoke] {name.replace('_', ' ')} {_compact_timestamp()}"


def _issue_description(name: str) -> str:
    return (
        "Automated Harness live reset smoke scenario.\n\n"
        f"Scenario: {name}\n"
        "This issue is expected to be mutated by Harness during verification."
    )


def _artifact_inputs(name: str, *, issue_identifier: str) -> dict[str, str]:
    suffix = _compact_timestamp()
    branch_name = f"codex/live-reset-{name}-{suffix}"
    file_path = f"proofs/live-reset-smoke/{name}-{suffix}.md"
    file_content = (
        f"# Harness live reset smoke\n\n"
        f"- Scenario: {name}\n"
        f"- Linear issue: {issue_identifier}\n"
        f"- Generated at: {_utc_now().isoformat()}\n"
    )
    return {
        "branch_name": branch_name,
        "file_path": file_path,
        "file_content": file_content,
        "commit_message": f"test: add live reset smoke proof for {name}",
        "pull_request_title": f"[Harness Live Smoke] {name} {issue_identifier}",
        "pull_request_body": (
            "Automated live reset smoke proof for Harness.\n\n"
            f"Scenario: {name}\n"
            f"Linear issue: {issue_identifier}\n"
        ),
    }


def _random_sha_different_from(reference_sha: str) -> str:
    if len(reference_sha) != 40:
        return "0" * 40
    replacement = "0" if reference_sha[-1].lower() != "0" else "1"
    return reference_sha[:-1] + replacement


def _build_claim(artifact: LiveGitHubArtifact, *, commit_sha: str | None = None, pr_number: int | None = None, pr_url: str | None = None) -> ResetCompletionClaim:
    return ResetCompletionClaim(
        repository_owner=artifact.owner,
        repository_name=artifact.repo,
        branch_name=artifact.branch_name,
        commit_sha=commit_sha or artifact.commit_sha,
        pull_request_number=pr_number or artifact.pull_request_number,
        pull_request_url=pr_url or artifact.pull_request_url,
    )


def _run_happy_path(
    *,
    service: ResetVerificationService,
    linear: _LiveLinearClient,
    github: _LiveGitHubClient,
    project: LiveLinearProject,
    owner: str,
    repo: str,
    base_branch: str,
    openclaw: _RecordingOpenClawClient,
) -> LiveResetScenarioResult:
    issue = linear.create_issue(
        project=project,
        title=_issue_title("happy_path"),
        description=_issue_description("happy_path"),
    )
    artifact = github.create_artifact(
        owner=owner,
        repo=repo,
        base_branch=base_branch,
        **_artifact_inputs("happy-path", issue_identifier=issue.identifier),
    )
    contract_id = _make_contract_id("happy")
    service.register_contract(
        ResetVerificationContract(
            contract_id=contract_id,
            linear_issue_id=issue.id,
            repository_owner=owner,
            repository_name=repo,
            branch_ref=artifact.branch_name,
        )
    )
    claim_result = service.submit_claim(contract_id, _build_claim(artifact))
    issue_after = linear.wait_for_issue_state(issue.id, expected_state="Done")
    contract_after = service.get_contract(contract_id)
    return LiveResetScenarioResult(
        name="happy_path",
        contract_id=contract_id,
        linear_issue_id=issue_after.id,
        linear_issue_identifier=issue_after.identifier,
        linear_issue_url=issue_after.url,
        pull_request_url=artifact.pull_request_url,
        branch_name=artifact.branch_name,
        commit_sha=artifact.commit_sha,
        claim_verdict=str(claim_result["status"]),
        latest_reason=contract_after.latest_reason,
        final_harness_status=contract_after.harness_status,
        final_linear_state=issue_after.state_name,
        repair_request_count=len(openclaw.repairs),
    )


def _run_missing_pull_request_path(
    *,
    service: ResetVerificationService,
    linear: _LiveLinearClient,
    github: _LiveGitHubClient,
    project: LiveLinearProject,
    owner: str,
    repo: str,
    base_branch: str,
    openclaw: _RecordingOpenClawClient,
) -> LiveResetScenarioResult:
    issue = linear.create_issue(
        project=project,
        title=_issue_title("missing_pull_request"),
        description=_issue_description("missing_pull_request"),
    )
    artifact = github.create_artifact(
        owner=owner,
        repo=repo,
        base_branch=base_branch,
        **_artifact_inputs("missing-pr", issue_identifier=issue.identifier),
    )
    contract_id = _make_contract_id("missing-pr")
    service.register_contract(
        ResetVerificationContract(
            contract_id=contract_id,
            linear_issue_id=issue.id,
            repository_owner=owner,
            repository_name=repo,
            branch_ref=artifact.branch_name,
        )
    )
    missing_number = artifact.pull_request_number + 900000
    missing_url = f"https://github.com/{owner}/{repo}/pull/{missing_number}"
    claim_result = service.submit_claim(
        contract_id,
        _build_claim(artifact, pr_number=missing_number, pr_url=missing_url),
    )
    issue_after = linear.wait_for_issue_state(issue.id, expected_state="In Progress")
    contract_after = service.get_contract(contract_id)
    return LiveResetScenarioResult(
        name="missing_pull_request",
        contract_id=contract_id,
        linear_issue_id=issue_after.id,
        linear_issue_identifier=issue_after.identifier,
        linear_issue_url=issue_after.url,
        pull_request_url=artifact.pull_request_url,
        branch_name=artifact.branch_name,
        commit_sha=artifact.commit_sha,
        claim_verdict=str(claim_result["status"]),
        latest_reason=contract_after.latest_reason,
        final_harness_status=contract_after.harness_status,
        final_linear_state=issue_after.state_name,
        repair_request_count=len(openclaw.repairs),
    )


def _run_wrong_sha_review_path(
    *,
    service: ResetVerificationService,
    linear: _LiveLinearClient,
    github: _LiveGitHubClient,
    project: LiveLinearProject,
    owner: str,
    repo: str,
    base_branch: str,
    openclaw: _RecordingOpenClawClient,
) -> LiveResetScenarioResult:
    issue = linear.create_issue(
        project=project,
        title=_issue_title("wrong_sha_review"),
        description=_issue_description("wrong_sha_review"),
    )
    artifact = github.create_artifact(
        owner=owner,
        repo=repo,
        base_branch=base_branch,
        **_artifact_inputs("wrong-sha-review", issue_identifier=issue.identifier),
    )
    contract_id = _make_contract_id("wrong-sha-review")
    service.register_contract(
        ResetVerificationContract(
            contract_id=contract_id,
            linear_issue_id=issue.id,
            repository_owner=owner,
            repository_name=repo,
            branch_ref=artifact.branch_name,
            retry_budget=1,
        )
    )
    wrong_sha = _random_sha_different_from(artifact.commit_sha)
    claim_result = service.submit_claim(contract_id, _build_claim(artifact, commit_sha=wrong_sha))
    tick_results = service.tick()
    issue_after = linear.wait_for_issue_state(issue.id, expected_state="In Review")
    contract_after = service.get_contract(contract_id)
    return LiveResetScenarioResult(
        name="wrong_sha_review",
        contract_id=contract_id,
        linear_issue_id=issue_after.id,
        linear_issue_identifier=issue_after.identifier,
        linear_issue_url=issue_after.url,
        pull_request_url=artifact.pull_request_url,
        branch_name=artifact.branch_name,
        commit_sha=artifact.commit_sha,
        claim_verdict=str(claim_result["status"]),
        latest_reason=contract_after.latest_reason,
        final_harness_status=contract_after.harness_status,
        final_linear_state=issue_after.state_name,
        repair_request_count=len(openclaw.repairs),
        tick_verdicts=tuple(result.status for result in tick_results),
    )


def run_live_reset_smoke_suite(
    *,
    linear_project_name: str = DEFAULT_LINEAR_PROJECT_NAME,
    github_owner: str = DEFAULT_GITHUB_OWNER,
    github_repo: str = DEFAULT_GITHUB_REPO,
    base_branch: str = DEFAULT_BASE_BRANCH,
) -> LiveResetSmokeSuiteResult:
    linear = _LiveLinearClient()
    github = _LiveGitHubClient()
    project = linear.resolve_project(linear_project_name)

    happy_service, happy_openclaw = _make_isolated_service("happy-path")
    happy = _run_happy_path(
        service=happy_service,
        linear=linear,
        github=github,
        project=project,
        owner=github_owner,
        repo=github_repo,
        base_branch=base_branch,
        openclaw=happy_openclaw,
    )

    missing_pr_service, missing_pr_openclaw = _make_isolated_service("missing-pr")
    missing_pr = _run_missing_pull_request_path(
        service=missing_pr_service,
        linear=linear,
        github=github,
        project=project,
        owner=github_owner,
        repo=github_repo,
        base_branch=base_branch,
        openclaw=missing_pr_openclaw,
    )

    wrong_sha_service, wrong_sha_openclaw = _make_isolated_service("wrong-sha-review")
    wrong_sha_review = _run_wrong_sha_review_path(
        service=wrong_sha_service,
        linear=linear,
        github=github,
        project=project,
        owner=github_owner,
        repo=github_repo,
        base_branch=base_branch,
        openclaw=wrong_sha_openclaw,
    )
    return LiveResetSmokeSuiteResult(
        happy_path=happy,
        missing_pull_request=missing_pr,
        wrong_sha_review=wrong_sha_review,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run live reset smoke tests against real Linear and GitHub.")
    parser.add_argument("--project", default=DEFAULT_LINEAR_PROJECT_NAME)
    parser.add_argument("--owner", default=DEFAULT_GITHUB_OWNER)
    parser.add_argument("--repo", default=DEFAULT_GITHUB_REPO)
    parser.add_argument("--base-branch", default=DEFAULT_BASE_BRANCH)
    args = parser.parse_args()

    result = run_live_reset_smoke_suite(
        linear_project_name=args.project,
        github_owner=args.owner,
        github_repo=args.repo,
        base_branch=args.base_branch,
    )
    print(json.dumps(asdict(result), indent=2, sort_keys=True))


__all__ = [
    "LiveResetScenarioResult",
    "LiveResetSmokeError",
    "LiveResetSmokeSuiteResult",
    "run_live_reset_smoke_suite",
]


if __name__ == "__main__":
    main()
