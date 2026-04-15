#!/usr/bin/env python
"""Low-friction operator flow for a real hosted Harness dry run."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.hosted_dryrun_flow import (
    DEFAULT_BASE_BRANCH,
    DEFAULT_COMMIT_MESSAGE,
    DEFAULT_DASHBOARD_URL,
    DEFAULT_GITHUB_OWNER,
    DEFAULT_GITHUB_REPO,
    DEFAULT_HARNESS_BASE_URL,
    DEFAULT_TARGET_FILE,
    DryRunFlowError,
    DryRunSession,
    JsonHttpClient,
    build_codex_cloud_prompt,
    build_operator_summary,
    ensure_directory,
    ensure_expected_file_present,
    ensure_pull_request_matches_session,
    fetch_github_pull_request_bundle,
    fetch_linear_issue,
    fetch_task_inspection,
    post_completion_claim,
    post_github_sync,
    post_linear_ingress,
    read_json_file,
    task_id_for_issue,
    write_json_file,
)


DEFAULT_STATE_DIR = Path(".harness-dryruns")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start", help="Fetch a Linear issue, ingest it into Harness, and render a Codex Cloud prompt.")
    start.add_argument("--linear-issue", required=True, help="Linear issue identifier, for example KNO-185.")
    start.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR), help="Directory for local dry-run session files.")
    start.add_argument("--task-id", help="Optional explicit Harness task id.")
    start.add_argument("--harness-base-url", default=DEFAULT_HARNESS_BASE_URL)
    start.add_argument("--dashboard-url", default=DEFAULT_DASHBOARD_URL)
    start.add_argument("--github-owner", default=DEFAULT_GITHUB_OWNER)
    start.add_argument("--github-repo", default=DEFAULT_GITHUB_REPO)
    start.add_argument("--base-branch", default=DEFAULT_BASE_BRANCH)
    start.add_argument("--target-file", default=DEFAULT_TARGET_FILE)
    start.add_argument("--commit-message", default=DEFAULT_COMMIT_MESSAGE)

    finish = subparsers.add_parser("finish", help="Use a GitHub PR URL to post a completion claim, GitHub sync, and inspection outputs.")
    finish.add_argument("--session", required=True, help="Path to a saved dry-run session JSON file.")
    finish.add_argument("--pr-url", required=True, help="GitHub PR URL returned by Codex Cloud.")
    finish.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR), help="Directory for session output artifacts.")

    status = subparsers.add_parser("status", help="Fetch the current inspection surfaces for a saved session.")
    status.add_argument("--session", required=True, help="Path to a saved dry-run session JSON file.")

    return parser


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise DryRunFlowError(f"{name} is required")
    return value.strip()


def _session_path(state_dir: Path, task_id: str) -> Path:
    return state_dir / f"{task_id}.session.json"


def _write_prompt(path: Path, prompt: str) -> None:
    ensure_directory(path.parent)
    path.write_text(prompt + "\n", encoding="utf-8")


def _cmd_start(args: argparse.Namespace) -> int:
    linear_token = _require_env("LINEAR_AUTH")
    state_dir = Path(args.state_dir)
    client = JsonHttpClient()
    issue = fetch_linear_issue(client, linear_token=linear_token, issue_identifier=args.linear_issue)
    session = DryRunSession(
        task_id=args.task_id or task_id_for_issue(issue.identifier),
        linear_issue_id=issue.issue_id,
        linear_issue_identifier=issue.identifier,
        linear_issue_title=issue.title,
        linear_issue_description=issue.description,
        harness_base_url=args.harness_base_url.rstrip("/"),
        dashboard_url=args.dashboard_url.rstrip("/"),
        github_owner=args.github_owner,
        github_repo=args.github_repo,
        base_branch=args.base_branch,
        target_file=args.target_file,
        commit_message=args.commit_message,
    )
    ingest_result = post_linear_ingress(client, session=session, issue=issue)
    if ingest_result.status != 200:
        raise DryRunFlowError(
            f"Harness linear ingress failed with HTTP {ingest_result.status}: {json.dumps(ingest_result.payload, indent=2)}"
        )

    ensure_directory(state_dir)
    session_path = _session_path(state_dir, session.task_id)
    prompt_path = state_dir / f"{session.task_id}.codex-prompt.txt"
    write_json_file(session_path, session.to_dict())
    _write_prompt(prompt_path, build_codex_cloud_prompt(session))
    write_json_file(state_dir / f"{session.task_id}.ingress-response.json", ingest_result.payload)

    print(f"Session: {session_path}")
    print(f"Prompt: {prompt_path}")
    print(f"Harness task id: {session.task_id}")
    print(f"Dashboard: {session.dashboard_url}")
    print()
    print(build_codex_cloud_prompt(session))
    return 0


def _cmd_finish(args: argparse.Namespace) -> int:
    github_token = _require_env("GH_AUTH")
    state_dir = Path(args.state_dir)
    client = JsonHttpClient()
    session = DryRunSession.from_dict(read_json_file(Path(args.session)))
    pull_request, commit, changed_files = fetch_github_pull_request_bundle(
        client,
        github_token=github_token,
        pr_url=args.pr_url,
    )
    ensure_pull_request_matches_session(session, pull_request)
    ensure_expected_file_present(changed_files, expected_path=session.target_file)

    claim_result = post_completion_claim(client, session=session, pull_request=pull_request, commit=commit)
    if claim_result.status != 200:
        raise DryRunFlowError(
            f"Completion claim failed with HTTP {claim_result.status}: {json.dumps(claim_result.payload, indent=2)}"
        )

    sync_result = post_github_sync(
        client,
        session=session,
        pull_request=pull_request,
        commit=commit,
        changed_files=changed_files,
    )
    if sync_result.status != 200:
        raise DryRunFlowError(
            f"GitHub sync failed with HTTP {sync_result.status}: {json.dumps(sync_result.payload, indent=2)}"
        )

    inspection = fetch_task_inspection(client, session=session)
    for key, result in inspection.items():
        if result.status != 200:
            raise DryRunFlowError(
                f"Inspection fetch for {key} failed with HTTP {result.status}: {json.dumps(result.payload, indent=2)}"
            )

    ensure_directory(state_dir)
    write_json_file(state_dir / f"{session.task_id}.completion-claim-response.json", claim_result.payload)
    write_json_file(state_dir / f"{session.task_id}.github-sync-response.json", sync_result.payload)
    write_json_file(state_dir / f"{session.task_id}.read-model.json", inspection["read_model"].payload)
    write_json_file(state_dir / f"{session.task_id}.timeline.json", inspection["timeline"].payload)
    write_json_file(state_dir / f"{session.task_id}.evaluations.json", inspection["evaluations"].payload)

    summary = build_operator_summary(
        session,
        read_model=inspection["read_model"].payload,
        timeline=inspection["timeline"].payload,
        evaluations=inspection["evaluations"].payload,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    client = JsonHttpClient()
    session = DryRunSession.from_dict(read_json_file(Path(args.session)))
    inspection = fetch_task_inspection(client, session=session)
    for key, result in inspection.items():
        if result.status != 200:
            raise DryRunFlowError(
                f"Inspection fetch for {key} failed with HTTP {result.status}: {json.dumps(result.payload, indent=2)}"
            )
    print(
        json.dumps(
            build_operator_summary(
                session,
                read_model=inspection["read_model"].payload,
                timeline=inspection["timeline"].payload,
                evaluations=inspection["evaluations"].payload,
            ),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "start":
            return _cmd_start(args)
        if args.command == "finish":
            return _cmd_finish(args)
        if args.command == "status":
            return _cmd_status(args)
    except DryRunFlowError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 1
    raise AssertionError(f"Unhandled command {args.command!r}")


if __name__ == "__main__":
    raise SystemExit(main())
