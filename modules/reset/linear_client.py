"""Thin Linear GraphQL client for reset-slice writeback."""

from __future__ import annotations

import json
import os
import ssl
import time
from typing import Any
from urllib import error, request


class LinearClientError(ValueError):
    """Raised when Linear API interaction fails."""


class LinearResetClient:
    """Minimal Linear client that updates issue state and writes Harness comments."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_url: str = "https://api.linear.app/graphql",
        timeout_seconds: float = 10.0,
        state_confirmation_attempts: int = 2,
        state_confirmation_delay_seconds: float = 0.5,
    ) -> None:
        self.api_key = api_key or os.getenv("LINEAR_API_KEY")
        self.api_url = api_url
        self.timeout_seconds = timeout_seconds
        self.state_confirmation_attempts = max(1, int(state_confirmation_attempts))
        self.state_confirmation_delay_seconds = max(0.0, float(state_confirmation_delay_seconds))
        self.ssl_context = _build_ssl_context()

    def _graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise LinearClientError("LINEAR_API_KEY is required")
        req = request.Request(
            self.api_url,
            data=json.dumps({"query": query, "variables": variables}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": self.api_key},
        )
        try:
            with request.urlopen(req, timeout=self.timeout_seconds, context=self.ssl_context) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as http_error:
            raise LinearClientError(f"Linear request failed: HTTP {http_error.code}") from http_error
        except error.URLError as url_error:
            raise LinearClientError(f"Linear request failed: {url_error.reason}") from url_error

        if payload.get("errors"):
            message = "; ".join(str(item.get("message", "unknown error")) for item in payload["errors"])
            raise LinearClientError(f"Linear GraphQL error: {message}")
        return payload["data"]

    def _get_issue_context(self, issue_ref: str) -> dict[str, Any]:
        query = """
        query IssueContext($id: String!) {
          issue(id: $id) {
            id
            identifier
            url
            title
            state { id name type }
            team {
              id
              name
              states {
                nodes {
                  id
                  name
                  type
                }
              }
            }
          }
        }
        """
        payload = self._graphql(query, {"id": issue_ref})
        issue = payload.get("issue")
        if not isinstance(issue, dict):
            raise LinearClientError(f"Linear issue {issue_ref!r} was not found")
        return issue

    @staticmethod
    def _state_id_for_name(issue: dict[str, Any], desired_state_name: str) -> str:
        team = issue.get("team") if isinstance(issue.get("team"), dict) else {}
        states = team.get("states") if isinstance(team.get("states"), dict) else {}
        for state in states.get("nodes") or ():
            if isinstance(state, dict) and str(state.get("name") or "").lower() == desired_state_name.lower():
                return str(state["id"])
        raise LinearClientError(f"Linear team state {desired_state_name!r} is not available on issue team")

    @staticmethod
    def _require_mutation_success(payload: dict[str, Any], mutation_name: str) -> None:
        mutation = payload.get(mutation_name)
        if not isinstance(mutation, dict) or mutation.get("success") is not True:
            raise LinearClientError(f"Linear {mutation_name} did not succeed")

    def update_issue(self, issue_ref: str, *, state: str | None, harness_status: str, comment: str) -> dict[str, Any]:
        issue = self._get_issue_context(issue_ref)
        issue_id = str(issue["id"])

        if state:
            state_id = self._state_id_for_name(issue, state)
            update_mutation = """
            mutation UpdateIssue($id: String!, $input: IssueUpdateInput!) {
              issueUpdate(id: $id, input: $input) {
                success
              }
            }
            """
            current_state_name = ""
            for attempt_index in range(self.state_confirmation_attempts):
                update_result = self._graphql(update_mutation, {"id": issue_id, "input": {"stateId": state_id}})
                self._require_mutation_success(update_result, "issueUpdate")
                issue = self._get_issue_context(issue_id)
                current_state_name = str(((issue.get("state") or {}).get("name")) or "")
                if current_state_name.lower() == state.lower():
                    break
                if attempt_index + 1 < self.state_confirmation_attempts:
                    time.sleep(self.state_confirmation_delay_seconds)
            else:
                raise LinearClientError(
                    f"Linear issue state did not update to {state!r}; current state is {current_state_name!r}"
                )

        comment_body = f"Harness status: {harness_status}\n\n{comment}"
        comment_mutation = """
        mutation CreateComment($input: CommentCreateInput!) {
          commentCreate(input: $input) {
            success
          }
        }
        """
        comment_result = self._graphql(comment_mutation, {"input": {"issueId": issue_id, "body": comment_body}})
        self._require_mutation_success(comment_result, "commentCreate")
        return {
            "issue_id": issue_id,
            "issue_identifier": issue["identifier"],
            "issue_url": issue["url"],
            "state": state,
            "harness_status": harness_status,
        }


def _build_ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    try:
        import certifi  # type: ignore
    except ImportError:
        return context
    return ssl.create_default_context(cafile=certifi.where())


__all__ = ["LinearClientError", "LinearResetClient"]
