from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from modules.api import HarnessApiService
from modules.intake import create_task_envelope
from modules.store import FileBackedHarnessStore
from tests.test_completion_claim_reconciliation import (
    _FakeGitHubGateway,
    _completion_claim_payload,
    _prepare_branch_only_reconciliation_task,
    _pull_request,
    _registry_with_gateway,
    _remove_commit_context,
    _task_envelope,
)

BUNDLE_DIR = Path("docs/demo/kno-184-missing-commit-recovery-validation")


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _scenario_a() -> dict:
    resolved_sha = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    gateway = _FakeGitHubGateway(
        branch_head_commit_sha=resolved_sha,
        created_pr=_pull_request(number=409, head_sha=resolved_sha),
    )

    with TemporaryDirectory(prefix="kno184-scenario-a-") as temp_dir:
        service = HarnessApiService(
            store=FileBackedHarnessStore(temp_dir),
            reconciliation_registry=_registry_with_gateway(gateway),
        )
        task_id = "task-kno-184-scenario-a"
        claim_id = "claim-kno-184-scenario-a"
        task = _prepare_branch_only_reconciliation_task(_task_envelope(task_id=task_id))
        service.store.create_task(task)

        request_payload = _remove_commit_context(_completion_claim_payload(claim_id))
        read_initial_status, read_initial = service.get_task_read_model(task_id)
        timeline_initial_status, timeline_initial = service.get_task_timeline(task_id)
        claim_status, claim_response = service.submit_completion_claim(task_id, request_payload)
        read_final_status, read_final = service.get_task_read_model(task_id)
        timeline_final_status, timeline_final = service.get_task_timeline(task_id)

    prefix = BUNDLE_DIR / "scenario-a"
    _write_json(prefix.with_name("scenario-a-completion-claim-request.json"), request_payload)
    _write_json(prefix.with_name("scenario-a-completion-claim-response.json"), claim_response)
    _write_json(prefix.with_name("scenario-a-read-model-initial.json"), read_initial)
    _write_json(prefix.with_name("scenario-a-read-model-final.json"), read_final)
    _write_json(prefix.with_name("scenario-a-timeline-initial.json"), timeline_initial)
    _write_json(prefix.with_name("scenario-a-timeline-final.json"), timeline_final)

    attempt = claim_response["task_envelope"]["reconciliation"]["attempts"][-1]
    checks = {
        "claim_http_200": claim_status == 200,
        "not_invalid_execution_attempt": "invalid_execution_attempt" not in claim_response,
        "action_transition_applied": claim_response.get("action") == "transition_applied",
        "attempt_resolved": attempt.get("status") == "resolved",
        "task_blocked_pending_pr_recovery": claim_response.get("task_envelope", {}).get("status") == "blocked",
        "commit_sha_recovered": attempt.get("details", {}).get("commit_sha") == resolved_sha,
        "read_model_http_200": read_initial_status == 200 and read_final_status == 200,
        "timeline_http_200": timeline_initial_status == 200 and timeline_final_status == 200,
    }

    return {
        "scenario": "A",
        "description": "Missing commit SHA with trustworthy repository+branch, branch head resolvable",
        "construction": "Branch-only reconciliation task with commit context removed from completion claim; fake GitHub gateway returns branch head SHA.",
        "expected": {
            "invalid_execution_attempt": False,
            "recovery_attempted": True,
            "recovery_succeeds": True,
            "result": "transition_applied",
            "task_status": "blocked",
        },
        "actual": {
            "claim_status": claim_status,
            "action": claim_response.get("action"),
            "task_status": claim_response.get("task_envelope", {}).get("status"),
            "branch_head_commit_sha": attempt.get("details", {}).get("branch_head_commit_sha"),
            "resolved_commit_sha": attempt.get("details", {}).get("commit_sha"),
            "final_decision": attempt.get("details", {}).get("final_decision"),
            "invalid_execution_attempt_present": "invalid_execution_attempt" in claim_response,
        },
        "checks": checks,
        "matched_expectation": all(checks.values()),
    }


def _scenario_b() -> dict:
    gateway = _FakeGitHubGateway(branch_head_commit_sha=None)

    with TemporaryDirectory(prefix="kno184-scenario-b-") as temp_dir:
        service = HarnessApiService(
            store=FileBackedHarnessStore(temp_dir),
            reconciliation_registry=_registry_with_gateway(gateway),
        )
        task_id = "task-kno-184-scenario-b"
        claim_id = "claim-kno-184-scenario-b"
        task = _prepare_branch_only_reconciliation_task(_task_envelope(task_id=task_id))
        service.store.create_task(task)

        request_payload = _remove_commit_context(_completion_claim_payload(claim_id))
        read_initial_status, read_initial = service.get_task_read_model(task_id)
        timeline_initial_status, timeline_initial = service.get_task_timeline(task_id)
        claim_status, claim_response = service.submit_completion_claim(task_id, request_payload)
        read_final_status, read_final = service.get_task_read_model(task_id)
        timeline_final_status, timeline_final = service.get_task_timeline(task_id)

    prefix = BUNDLE_DIR / "scenario-b"
    _write_json(prefix.with_name("scenario-b-completion-claim-request.json"), request_payload)
    _write_json(prefix.with_name("scenario-b-completion-claim-response.json"), claim_response)
    _write_json(prefix.with_name("scenario-b-read-model-initial.json"), read_initial)
    _write_json(prefix.with_name("scenario-b-read-model-final.json"), read_final)
    _write_json(prefix.with_name("scenario-b-timeline-initial.json"), timeline_initial)
    _write_json(prefix.with_name("scenario-b-timeline-final.json"), timeline_final)

    attempt = claim_response.get("reconciliation_attempt", {})
    checks = {
        "claim_http_200": claim_status == 200,
        "not_invalid_execution_attempt": "invalid_execution_attempt" not in claim_response,
        "action_reconciliation_terminal_failed": claim_response.get("action") == "reconciliation_terminal_failed",
        "task_failed": claim_response.get("task_envelope", {}).get("status") == "failed",
        "recovery_attempted": "branch head" in str(attempt.get("details", {}).get("error", "")).lower(),
        "branch_head_unresolved": attempt.get("details", {}).get("branch_head_commit_sha") is None,
        "read_model_http_200": read_initial_status == 200 and read_final_status == 200,
        "timeline_http_200": timeline_initial_status == 200 and timeline_final_status == 200,
    }

    return {
        "scenario": "B",
        "description": "Missing commit SHA with trustworthy repository+branch, branch head not resolvable",
        "construction": "Branch-only reconciliation task with commit context removed from completion claim; fake GitHub gateway returns no branch head SHA.",
        "expected": {
            "invalid_execution_attempt": False,
            "recovery_attempted": True,
            "recovery_succeeds": False,
            "result": "reconciliation_terminal_failed",
            "task_status": "failed",
        },
        "actual": {
            "claim_status": claim_status,
            "action": claim_response.get("action"),
            "task_status": claim_response.get("task_envelope", {}).get("status"),
            "branch_head_commit_sha": attempt.get("details", {}).get("branch_head_commit_sha"),
            "error": attempt.get("details", {}).get("error"),
            "invalid_execution_attempt_present": "invalid_execution_attempt" in claim_response,
        },
        "checks": checks,
        "matched_expectation": all(checks.values()),
    }


def _scenario_c() -> dict:
    with TemporaryDirectory(prefix="kno184-scenario-c-") as temp_dir:
        service = HarnessApiService(store=FileBackedHarnessStore(temp_dir))
        task_id = "task-kno-184-scenario-c"
        task = create_task_envelope(
            {
                "id": task_id,
                "title": "KNO-184 scenario C validation",
                "description": "Validate invalid execution attempt boundary remains enforced.",
                "origin": {
                    "source_system": "linear",
                    "source_type": "ingress_request",
                    "source_id": "KNO-184",
                },
                "acceptance_criteria": [
                    {
                        "id": "ac-1",
                        "description": "invalid_execution_attempt remains enforced when execution identity is weak.",
                        "required": True,
                    }
                ],
            },
            now="2026-04-06T00:00:00Z",
        )
        task["status"] = "executing"
        task["assigned_executor"] = {
            "executor_type": "codex",
            "executor_id": "executor-kno-184-scenario-c",
            "assignment_reason": "Validate invalid execution attempt boundary.",
        }
        service.store.create_task(task)

        request_payload = {
            "request": {
                "completion_claim": {
                    "claim_id": "claim-kno-184-scenario-c",
                    "reported_at": "2026-04-06T00:01:00Z",
                    "reported_by": "codex",
                    "reason": "executor reported completion",
                },
                "execution_attempt": {
                    "attempt_id": "attempt-kno-184-scenario-c",
                    "recorded_at": "2026-04-06T00:01:01Z",
                    "status": "succeeded",
                    "reported_by": "codex",
                    "artifact_references": [],
                    "metadata": {"executor_run_id": "run-kno-184-scenario-c"},
                },
                "runtime_facts": {
                    "executor_reported_success": True,
                    "attempt_count": 1,
                },
            }
        }

        read_initial_status, read_initial = service.get_task_read_model(task_id)
        timeline_initial_status, timeline_initial = service.get_task_timeline(task_id)
        claim_status, claim_response = service.submit_completion_claim(task_id, request_payload)
        read_final_status, read_final = service.get_task_read_model(task_id)
        timeline_final_status, timeline_final = service.get_task_timeline(task_id)

    prefix = BUNDLE_DIR / "scenario-c"
    _write_json(prefix.with_name("scenario-c-completion-claim-request.json"), request_payload)
    _write_json(prefix.with_name("scenario-c-completion-claim-response.json"), claim_response)
    _write_json(prefix.with_name("scenario-c-read-model-initial.json"), read_initial)
    _write_json(prefix.with_name("scenario-c-read-model-final.json"), read_final)
    _write_json(prefix.with_name("scenario-c-timeline-initial.json"), timeline_initial)
    _write_json(prefix.with_name("scenario-c-timeline-final.json"), timeline_final)

    validation = claim_response.get("invalid_execution_attempt", {}).get("validation", {})
    checks = {
        "claim_http_200": claim_status == 200,
        "action_contract_violation_failed": claim_response.get("action") == "contract_violation_failed",
        "task_failed": claim_response.get("task_envelope", {}).get("status") == "failed",
        "failure_type_contract_violation": claim_response.get("evaluation_record", {})
        .get("result", {})
        .get("failure_classification", {})
        .get("failure_type")
        == "contract_violation",
        "missing_branch_reason_present": "missing branch identity"
        in str(
            claim_response.get("evaluation_record", {})
            .get("result", {})
            .get("failure_classification", {})
            .get("reason", "")
        ).lower(),
        "read_model_http_200": read_initial_status == 200 and read_final_status == 200,
        "timeline_http_200": timeline_initial_status == 200 and timeline_final_status == 200,
    }

    return {
        "scenario": "C",
        "description": "Missing commit SHA with untrustworthy repository/branch identity",
        "construction": "Created an executing task with no trusted repo/branch artifacts; submitted a successful execution attempt without repository, branch, or commit identity.",
        "expected": {
            "invalid_execution_attempt": False,
            "recovery_attempted": False,
            "result": "contract_violation_failed",
            "task_status": "failed",
        },
        "actual": {
            "claim_status": claim_status,
            "action": claim_response.get("action"),
            "task_status": claim_response.get("task_envelope", {}).get("status"),
            "invalid_execution_attempt": claim_response.get("invalid_execution_attempt"),
            "failure_classification": claim_response.get("evaluation_record", {})
            .get("result", {})
            .get("failure_classification"),
        },
        "checks": checks,
        "matched_expectation": all(checks.values()),
    }


def main() -> None:
    BUNDLE_DIR.mkdir(parents=True, exist_ok=True)

    scenarios = [_scenario_a(), _scenario_b(), _scenario_c()]
    summary = {
        "proof_name": "kno-184-missing-commit-recovery-validation",
        "validation_target": {
            "merged_pr": 166,
            "branch": "main",
            "boundary": "missing commit SHA recovery via trusted branch head without weakening invalid_execution_attempt",
        },
        "execution_mode": "local-controlled",
        "hosted_validation": "not_performed",
        "scenarios": scenarios,
    }
    all_passed = all(item["matched_expectation"] for item in scenarios)
    summary["overall"] = {
        "all_scenarios_passed": all_passed,
        "conclusion": "validated" if all_passed else "partially validated",
    }

    _write_json(BUNDLE_DIR / "summary.json", summary)


if __name__ == "__main__":
    main()
