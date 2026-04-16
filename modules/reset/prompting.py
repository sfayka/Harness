"""Prompt builder for simulated and live reset-slice dispatch scenarios."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResetDispatchPromptContext:
    contract_id: str
    linear_issue_id: str
    linear_issue_title: str
    repository_owner: str
    repository_name: str
    branch_name: str
    base_branch: str
    required_changed_path: str


def build_reset_dispatch_prompt(context: ResetDispatchPromptContext) -> str:
    return f"""You are executing one Harness verification dry run.

Issue context:
- Harness contract: `{context.contract_id}`
- Linear issue: `{context.linear_issue_id}`
- Linear title: `{context.linear_issue_title}`

Repository contract:
- Repository: `{context.repository_owner}/{context.repository_name}`
- Base branch: `{context.base_branch}`
- Required branch: `{context.branch_name}`
- Required changed file: `{context.required_changed_path}`

Rules:
- Work only in the contracted repository and branch context.
- Do not treat the task as complete until there is a real repository, branch, commit SHA, and PR URL.
- The PR must be mergeable operator proof, not a local-only branch or a stale link.

Final proof must include exactly these fields:
Repository: {context.repository_owner}/{context.repository_name}
Branch: {context.branch_name}
Commit SHA: <40-char-sha>
PR URL: <https://github.com/.../pull/...>
"""


__all__ = ["ResetDispatchPromptContext", "build_reset_dispatch_prompt"]
