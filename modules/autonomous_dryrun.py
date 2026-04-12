"""Controlled local autonomous dry runs over canonical Harness APIs."""

from __future__ import annotations

import json
import re
import tempfile
import threading
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from modules.adapters.codex_cloud import CodexCloudExecutorAdapter, CodexCloudRuntimeClient
from modules.api import HarnessApiService, run_server
from modules.connectors.openclaw_supervisor import OpenClawHarnessSupervisor
from modules.runtime_scenario_builders import (
    build_create_task_payload,
    build_completion_evidence,
    build_expected_code_context,
    build_github_facts,
    build_linked_artifacts,
    build_linear_facts,
)
from modules.store import FileBackedHarnessStore


@dataclass(frozen=True)
class AutonomousDryRunResult:
    """Structured result from a controlled local autonomous dry run."""

    task_id: str
    create_status: int
    initial_task_status: str | None
    initial_supervision_queue_status: int
    initial_supervision_attention_type: str | None
    supervisor_queue_status: int
    supervisor_decision_count: int
    supervisor_action_statuses: tuple[str, ...]
    final_task_status: str | None
    final_supervision_queue_status: int
    final_supervision_attention_type: str | None
    sample_runtime: bool


class SampleCodexCloudRuntimeClient:
    """Deterministic sample runtime used for local controlled autonomy dry runs."""

    sample_runtime = True

    def execute(self, request_payload: dict[str, Any]) -> dict[str, Any]:
        branch_name = request_payload["task"]["branch_hint"]
        commit_sha = "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705"
        return {
            "run_id": "sample-codex-cloud-run-1",
            "preflight": {
                "pwd": "/workspace/Harness",
                "git_remote_v": (
                    "origin\thttps://github.com/sfayka/Harness.git (fetch)\n"
                    "origin\thttps://github.com/sfayka/Harness.git (push)"
                ),
                "bootstrap_proof": "sample bootstrap ok",
            },
            "events": [
                {"id": "evt-1", "type": "run_started", "timestamp": "2026-04-12T16:00:00Z"},
                {"id": "evt-2", "type": "run_succeeded", "timestamp": "2026-04-12T16:05:00Z"},
            ],
            "artifacts": [
                {
                    "type": "branch",
                    "id": "branch-1",
                    "external_id": branch_name,
                    "head_commit_sha": commit_sha,
                },
                {
                    "type": "commit",
                    "id": "commit-1",
                    "commit_sha": commit_sha,
                    "url": f"https://github.com/KnoxAnalytics/HARNESS-DRYRUN/commit/{commit_sha}",
                },
                {
                    "type": "pull_request",
                    "id": "pr-1",
                    "url": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/pull/2",
                    "number": 2,
                    "state": "open",
                    "merged": False,
                    "branch_name": branch_name,
                    "commit_sha": commit_sha,
                },
                {
                    "type": "changed_file",
                    "id": "changed-file-1",
                    "url": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/blob/main/modules/api.py",
                    "commit_sha": commit_sha,
                },
            ],
            "completion": {
                "reported_complete": True,
                "confidence": "high",
                "reason": "Sample autonomous dry run produced the full artifact set",
            },
        }


def _request_json(base_url: str, method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(base_url + path, data=data, headers=headers, method=method)
    try:
        with urlopen(request) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        try:
            return error.code, json.loads(error.read().decode("utf-8"))
        finally:
            error.close()


def _find_queue_entry(queue_payload: dict[str, Any], *, task_id: str) -> dict[str, Any] | None:
    queue = queue_payload.get("queue")
    if not isinstance(queue, list):
        return None
    return next(
        (
            item
            for item in queue
            if isinstance(item, dict) and str(item.get("task_id") or "") == task_id
        ),
        None,
    )


def _retryable_creation_payload(task_id: str) -> dict[str, Any]:
    branch_name = _task_scoped_branch_name(task_id)
    payload = build_create_task_payload(
        task_id,
        title="Controlled autonomous retryable dry run",
    )
    payload["request"]["linked_artifacts"] = build_linked_artifacts(branch_name=branch_name)
    payload["request"]["completion_evidence"] = build_completion_evidence(
        required_artifact_types=["pull_request", "commit", "changed_file"],
        validated_artifact_ids=["artifact-pr-1", "artifact-commit-1"],
    )
    payload["request"]["external_facts"] = {
        "expected_code_context": build_expected_code_context(branch_name=branch_name),
        "github_facts": build_github_facts(branch_name=branch_name),
        "linear_facts": build_linear_facts(state="completed", workflow_state_type="completed"),
    }
    payload["request"]["claimed_completion"] = True
    payload["request"]["acceptance_criteria_satisfied"] = True
    payload["request"]["runtime_facts"] = {
        "executor_reported_failure": True,
        "attempt_count": 1,
        "latest_attempt_outcome": "failed",
    }
    return payload


def _task_scoped_branch_name(task_id: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", task_id.strip().lower()).strip("-")
    return f"codex/{slug or 'task'}"


def _github_sync_reevaluation_payload(task_id: str) -> dict[str, Any]:
    branch_name = _task_scoped_branch_name(task_id)
    changed_file_artifact_id = f"artifact-changed-file-{task_id}"
    commit_sha = "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705"
    return {
        "request": {
            "new_artifacts": [
                {
                    "id": changed_file_artifact_id,
                    "type": "changed_file",
                    "title": "GitHub changed-file proof",
                    "description": "Post-dispatch GitHub sync captured the changed file for the latest run.",
                    "location": f"https://github.com/KnoxAnalytics/HARNESS-DRYRUN/blob/{branch_name}/modules/api.py",
                    "content_type": None,
                    "external_id": None,
                    "commit_sha": commit_sha,
                    "pull_request_number": None,
                    "review_state": None,
                    "provenance": {
                        "source_system": "github",
                        "source_type": "api",
                        "source_id": f"contents/{branch_name}/modules/api.py",
                        "captured_by": "github-sync",
                    },
                    "verification_status": "verified",
                    "repository": {
                        "host": "github.com",
                        "owner": "KnoxAnalytics",
                        "name": "HARNESS-DRYRUN",
                        "external_id": "repo-dryrun-1",
                    },
                    "branch": {
                        "name": branch_name,
                        "base_branch": "main",
                        "head_commit_sha": commit_sha,
                    },
                    "changed_files": [
                        {
                            "path": "modules/api.py",
                            "change_type": "modified",
                        }
                    ],
                    "external_refs": [],
                    "captured_at": "2026-04-12T16:06:00Z",
                    "metadata": {},
                }
            ],
            "completion_evidence": {
                "validated_artifact_ids": [
                    "artifact-pr-1",
                    "artifact-commit-1",
                    changed_file_artifact_id,
                ],
                "validation_method": "external_reconciliation",
            },
            "external_facts": {
                "expected_code_context": build_expected_code_context(branch_name=branch_name),
                "github_facts": build_github_facts(branch_name=branch_name),
                "linear_facts": build_linear_facts(state="completed", workflow_state_type="completed"),
            },
            "claimed_completion": True,
            "acceptance_criteria_satisfied": True,
        }
    }


def run_retryable_codex_supervision_dry_run(
    *,
    runtime_client: CodexCloudRuntimeClient | None = None,
    task_id: str = "autonomous-dryrun-retryable-1",
) -> AutonomousDryRunResult:
    """Run a controlled local dry run that exercises retryable supervision recovery."""

    resolved_runtime_client = runtime_client or SampleCodexCloudRuntimeClient()
    with tempfile.TemporaryDirectory() as temp_dir:
        service = HarnessApiService(
            store=FileBackedHarnessStore(temp_dir),
            executor_adapters={
                "codex": CodexCloudExecutorAdapter(runtime_client=resolved_runtime_client),
            },
        )
        server = run_server(host="127.0.0.1", port=0, service=service)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base_url = f"http://127.0.0.1:{server.server_port}"
            create_status, create_payload = _request_json(
                base_url,
                "POST",
                "/evaluate",
                _retryable_creation_payload(task_id),
            )
            if create_status >= 400:
                raise RuntimeError(f"Autonomous dry run create failed: {create_payload}")

            initial_queue_status, initial_queue_payload = _request_json(base_url, "GET", "/supervision/queue")
            if initial_queue_status >= 400:
                raise RuntimeError(f"Autonomous dry run queue fetch failed: {initial_queue_payload}")
            initial_queue_entry = _find_queue_entry(initial_queue_payload, task_id=task_id)

            supervisor = OpenClawHarnessSupervisor(base_url)
            cycle = supervisor.run_cycle(allow_redispatch=True, executor="codex")

            post_dispatch_task_status, post_dispatch_task_payload = _request_json(base_url, "GET", f"/tasks/{task_id}")
            if post_dispatch_task_status >= 400:
                raise RuntimeError("Autonomous dry run final inspection failed")

            if (
                isinstance(post_dispatch_task_payload.get("task"), dict)
                and str((post_dispatch_task_payload.get("task") or {}).get("status") or "") == "blocked"
            ):
                reevaluation_status, reevaluation_payload = _request_json(
                    base_url,
                    "POST",
                    f"/tasks/{task_id}/reevaluate",
                    _github_sync_reevaluation_payload(task_id),
                )
                if reevaluation_status >= 400:
                    raise RuntimeError(f"Autonomous dry run GitHub sync failed: {reevaluation_payload}")

            task_status, task_payload = _request_json(base_url, "GET", f"/tasks/{task_id}")
            final_queue_status, final_queue_payload = _request_json(base_url, "GET", "/supervision/queue")
            if task_status >= 400 or final_queue_status >= 400:
                raise RuntimeError("Autonomous dry run final inspection failed")
            final_queue_entry = _find_queue_entry(final_queue_payload, task_id=task_id)

            return AutonomousDryRunResult(
                task_id=task_id,
                create_status=create_status,
                initial_task_status=(
                    str((create_payload.get("task_envelope") or {}).get("status"))
                    if isinstance(create_payload.get("task_envelope"), dict)
                    else None
                ),
                initial_supervision_queue_status=initial_queue_status,
                initial_supervision_attention_type=(
                    str(initial_queue_entry.get("attention_type"))
                    if isinstance(initial_queue_entry, dict) and initial_queue_entry.get("attention_type") is not None
                    else None
                ),
                supervisor_queue_status=cycle.queue_status,
                supervisor_decision_count=cycle.decision_count,
                supervisor_action_statuses=tuple(item.action_status for item in cycle.action_results),
                final_task_status=(
                    str((task_payload.get("task") or {}).get("status"))
                    if isinstance(task_payload.get("task"), dict) and (task_payload.get("task") or {}).get("status") is not None
                    else None
                ),
                final_supervision_queue_status=final_queue_status,
                final_supervision_attention_type=(
                    str(final_queue_entry.get("attention_type"))
                    if isinstance(final_queue_entry, dict) and final_queue_entry.get("attention_type") is not None
                    else None
                ),
                sample_runtime=bool(getattr(resolved_runtime_client, "sample_runtime", False)),
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


__all__ = [
    "AutonomousDryRunResult",
    "SampleCodexCloudRuntimeClient",
    "run_retryable_codex_supervision_dry_run",
]
