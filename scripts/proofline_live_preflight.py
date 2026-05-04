#!/usr/bin/env python3
"""Preflight Proofline's gated live Linear/GitHub smoke.

This command is read-only. It does not create Linear issues, GitHub branches,
commits, or pull requests. It exists so operators can see whether the live smoke
is ready before setting HARNESS_RUN_LIVE_RESET_TESTS=1.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from modules.local_secrets import SecretStatus, collect_secret_statuses


DEFAULT_LINEAR_PROJECT_NAME = "HARNESS-DRYRUN"
DEFAULT_GITHUB_OWNER = "sfayka"
DEFAULT_GITHUB_REPO = "HARNESS-DRYRUN"
DEFAULT_BASE_BRANCH = "main"

CommandRunner = Callable[[tuple[str, ...]], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class PreflightCheck:
    code: str
    status: str
    message: str
    next_action: str
    details: dict[str, object] | None = None


def _run(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True)


def _has_env(name: str, env: dict[str, str]) -> bool:
    return bool((env.get(name) or "").strip())


def _configured_secret_source(name: str, statuses: tuple[SecretStatus, ...]) -> str | None:
    for status in statuses:
        if status.name == name and status.status == "configured":
            return status.source or "runtime-managed-secret-store"
    return None


def build_live_preflight_checks(
    *,
    env: dict[str, str],
    runner: CommandRunner = _run,
    github_owner: str = DEFAULT_GITHUB_OWNER,
    github_repo: str = DEFAULT_GITHUB_REPO,
    linear_project: str = DEFAULT_LINEAR_PROJECT_NAME,
    base_branch: str = DEFAULT_BASE_BRANCH,
    secret_statuses: tuple[SecretStatus, ...] | None = None,
) -> tuple[PreflightCheck, ...]:
    checks: list[PreflightCheck] = []
    runtime_statuses = secret_statuses if secret_statuses is not None else tuple(
        collect_secret_statuses(required_names=("github_token", "linear_api_key"))
    )

    live_flag = env.get("HARNESS_RUN_LIVE_RESET_TESTS") == "1"
    checks.append(
        PreflightCheck(
            code="live_mutation_flag",
            status="pass" if live_flag else "warn",
            message=(
                "HARNESS_RUN_LIVE_RESET_TESTS=1 is set."
                if live_flag
                else "HARNESS_RUN_LIVE_RESET_TESTS=1 is not set."
            ),
            next_action=(
                "No action needed."
                if live_flag
                else "Set HARNESS_RUN_LIVE_RESET_TESTS=1 only when you are ready to create throwaway live artifacts."
            ),
        )
    )

    github_env_ready = _has_env("GITHUB_TOKEN", env) or _has_env("GH_TOKEN", env)
    github_runtime_source = _configured_secret_source("github_token", runtime_statuses)
    github_ready = github_env_ready or github_runtime_source is not None
    checks.append(
        PreflightCheck(
            code="github_credential",
            status="pass" if github_ready else "warn",
            message=(
                "GitHub token env is configured."
                if github_env_ready
                else (
                    f"GitHub token is configured through {github_runtime_source}."
                    if github_runtime_source
                    else "No GitHub credential is configured."
                )
            ),
            next_action=(
                "No action needed."
                if github_ready
                else "Export GITHUB_TOKEN or GH_TOKEN, or configure Proofline's runtime-managed github_token secret."
            ),
            details={"accepted_env": ["GITHUB_TOKEN", "GH_TOKEN"], "runtime_secret": "github_token"},
        )
    )

    linear_env_ready = _has_env("LINEAR_API_KEY", env)
    linear_runtime_source = _configured_secret_source("linear_api_key", runtime_statuses)
    linear_ready = linear_env_ready or linear_runtime_source is not None
    checks.append(
        PreflightCheck(
            code="linear_credential",
            status="pass" if linear_ready else "fail",
            message=(
                "LINEAR_API_KEY is configured."
                if linear_env_ready
                else (
                    f"Linear API key is configured through {linear_runtime_source}."
                    if linear_runtime_source
                    else "No Linear credential is configured."
                )
            ),
            next_action=(
                "No action needed."
                if linear_ready
                else "Export LINEAR_API_KEY or configure Proofline's runtime-managed linear_api_key secret."
            ),
            details={"accepted_env": ["LINEAR_API_KEY"], "runtime_secret": "linear_api_key"},
        )
    )

    checks.append(
        PreflightCheck(
            code="target_guard",
            status="pass"
            if (github_owner, github_repo, linear_project, base_branch)
            == (DEFAULT_GITHUB_OWNER, DEFAULT_GITHUB_REPO, DEFAULT_LINEAR_PROJECT_NAME, DEFAULT_BASE_BRANCH)
            else "fail",
            message=(
                "Live smoke targets match the approved dry-run targets."
                if (github_owner, github_repo, linear_project, base_branch)
                == (DEFAULT_GITHUB_OWNER, DEFAULT_GITHUB_REPO, DEFAULT_LINEAR_PROJECT_NAME, DEFAULT_BASE_BRANCH)
                else "Live smoke targets do not match the approved dry-run targets."
            ),
            next_action="Use HARNESS-DRYRUN, sfayka/HARNESS-DRYRUN, and base branch main unless Sean approves a different target.",
            details={
                "linear_project": linear_project,
                "github_owner": github_owner,
                "github_repo": github_repo,
                "base_branch": base_branch,
            },
        )
    )

    gh_bin = shutil.which("gh")
    if not gh_bin:
        checks.append(
            PreflightCheck(
                code="github_cli",
                status="warn",
                message="GitHub CLI was not found on PATH.",
                next_action="Install gh or rely on explicit GITHUB_TOKEN/GH_TOKEN for live smoke.",
            )
        )
    else:
        auth = runner((gh_bin, "auth", "status"))
        checks.append(
            PreflightCheck(
                code="github_cli_auth",
                status="pass" if auth.returncode == 0 else "warn",
                message="GitHub CLI auth status is available." if auth.returncode == 0 else "GitHub CLI auth status failed.",
                next_action="No action needed." if auth.returncode == 0 else "Run gh auth status locally and fix authentication if needed.",
            )
        )
        token = runner((gh_bin, "auth", "token"))
        checks.append(
            PreflightCheck(
                code="github_cli_token",
                status="pass" if token.returncode == 0 and bool(token.stdout.strip()) else "warn",
                message="gh auth token returned a token." if token.returncode == 0 and bool(token.stdout.strip()) else "gh auth token did not return a usable token.",
                next_action="No action needed." if token.returncode == 0 and bool(token.stdout.strip()) else "Use GITHUB_TOKEN/GH_TOKEN or repair gh auth token access before relying on the CLI fallback.",
            )
        )
        repo = runner(
            (
                gh_bin,
                "repo",
                "view",
                f"{github_owner}/{github_repo}",
                "--json",
                "nameWithOwner,defaultBranchRef,url,isPrivate",
            )
        )
        repo_status = "warn"
        repo_details: dict[str, object] = {}
        if repo.returncode == 0:
            try:
                payload = json.loads(repo.stdout)
            except json.JSONDecodeError:
                repo_status = "warn"
            else:
                default_branch = ((payload.get("defaultBranchRef") or {}).get("name")) or None
                repo_status = "pass" if default_branch == base_branch else "fail"
                repo_details = {
                    "nameWithOwner": payload.get("nameWithOwner"),
                    "url": payload.get("url"),
                    "defaultBranch": default_branch,
                    "isPrivate": payload.get("isPrivate"),
                }
        checks.append(
            PreflightCheck(
                code="github_repo_readonly",
                status=repo_status,
                message=(
                    "GitHub dry-run repository is readable and default branch matches."
                    if repo_status == "pass"
                    else "GitHub dry-run repository read-only check did not pass."
                ),
                next_action="No action needed." if repo_status == "pass" else "Verify GitHub auth and the approved dry-run repository target.",
                details=repo_details or None,
            )
        )

    return tuple(checks)


def _summary(checks: tuple[PreflightCheck, ...]) -> dict[str, object]:
    fail = sum(1 for check in checks if check.status == "fail")
    warn = sum(1 for check in checks if check.status == "warn")
    status = "ready" if fail == 0 and warn == 0 else "not_ready"
    return {
        "status": status,
        "fail": fail,
        "warn": warn,
        "pass": sum(1 for check in checks if check.status == "pass"),
        "creates_live_artifacts": False,
        "live_smoke_command": "HARNESS_RUN_LIVE_RESET_TESTS=1 python3 -m unittest tests.test_reset_live_smoke -v",
        "checks": [asdict(check) for check in checks],
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--project", default=DEFAULT_LINEAR_PROJECT_NAME)
    parser.add_argument("--owner", default=DEFAULT_GITHUB_OWNER)
    parser.add_argument("--repo", default=DEFAULT_GITHUB_REPO)
    parser.add_argument("--base-branch", default=DEFAULT_BASE_BRANCH)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    checks = build_live_preflight_checks(
        env=dict(os.environ),
        github_owner=args.owner,
        github_repo=args.repo,
        linear_project=args.project,
        base_branch=args.base_branch,
    )
    payload = _summary(checks)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"status: {payload['status']}")
        for check in checks:
            print(f"- {check.status.upper()} {check.code}: {check.message}")
            if check.status != "pass":
                print(f"  next: {check.next_action}")
        print("live artifacts created: no")
    return 0 if payload["status"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
