from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from modules.api import HarnessApiService
from modules.intake import create_task_envelope
from modules.store import FileBackedHarnessStore
from tests.test_api import (
    _completion_claim_payload,
    _execution_attempt_payload,
    _registry_with_no_create_pull_request_gateway,
)

BUNDLE_DIR = Path("docs/demo/kno-181-invalid-execution-attempt-gate")
TASK_CREATED_AT = "2026-03-31T14:30:00Z"


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _base_task(*, task_id: str, description: str, executor_id: str) -> dict:
    task = create_task_envelope(
        {
            "id": task_id,
            "title": f"KNO-181 {task_id}",
            "description": description,
            "origin": {
                "source_system": "openclaw",
                "source_type": "ingress_request",
                "source_id": "req-happy-overlay-1",
            },
            "acceptance_criteria": [
                {
                    "id": "ac-1",
                    "description": "Harness accepts a fully reconciled, evidence-backed completion claim.",
                    "required": True,
                }
            ],
        },
        now=TASK_CREATED_AT,
    )
    task["status"] = "assigned"
    task["assigned_executor"] = {
        "executor_type": "codex",
        "executor_id": executor_id,
        "assignment_reason": description,
    }
    return task


def _seed_artifacts(task: dict) -> tuple[dict, dict]:
    seeded_task = deepcopy(task)
    seed_request = {
        "request": {
            "task_envelope": {
                **deepcopy(task),
                "status": "intake_ready",
                "assigned_executor": None,
            },
            "assigned_executor": deepcopy(task["assigned_executor"]),
        }
    }
    seed_response = {
        "status": 200,
        "response": {
            "action": "seeded_controlled_task",
            "target_status": "assigned",
            "task_envelope": seeded_task,
        },
    }
    return seed_request, seed_response


def _scenario_a() -> dict:
    task = _base_task(
        task_id="task-kno-181-scenario-a",
        description="Scenario A: invalid execution attempt without current-run code identity proof.",
        executor_id="executor-kno-181-a",
    )
    seed_request, seed_response = _seed_artifacts(task)

    invalid_attempt_payload = _execution_attempt_payload(attempt_id="attempt-kno-181-a-1")
    invalid_attempt_payload["execution_attempt"]["recorded_at"] = "2026-04-01T08:00:05Z"
    invalid_attempt_payload["execution_attempt"]["reported_by"] = "stub-executor"
    invalid_attempt_payload["execution_attempt"]["metadata"] = {"executor_run_id": "stub-run-attempt-kno-181-a-1"}
    invalid_attempt_payload["execution_attempt"]["artifact_references"] = [
        {
            "reference_id": "attempt-kno-181-a-1:commit",
            "artifact_type": "commit",
            "location": "stub://attempts/attempt-kno-181-a-1/commit",
            "metadata": {
                "branch_name": "codex/e2e-test",
            },
        }
    ]
    request_payload = {
        "request": {
            **_completion_claim_payload(claim_id="claim-kno-181-a-1"),
            **invalid_attempt_payload,
            "runtime_facts": {"executor_reported_success": True, "attempt_count": 1},
        }
    }
    request_payload["request"]["completion_claim"]["reported_at"] = "2026-04-01T08:00:00Z"
    request_payload["request"]["completion_claim"]["reported_by"] = "stub-executor"

    with TemporaryDirectory(prefix="kno181-scenario-a-") as temp_dir:
        service = HarnessApiService(store=FileBackedHarnessStore(temp_dir))
        service.store.create_task(task)

        read_initial_status, read_initial = service.get_task_read_model(task["id"])
        timeline_initial_status, timeline_initial = service.get_task_timeline(task["id"])

        with patch.dict("os.environ", {"HARNESS_INVALID_EXECUTION_RETRY_BUDGET": "1"}):
            claim_status, claim_response = service.submit_completion_claim(task["id"], request_payload)

        read_final_status, read_final = service.get_task_read_model(task["id"])
        timeline_final_status, timeline_final = service.get_task_timeline(task["id"])
        history_status, history = service.get_evaluation_history(task["id"])

    prefix = BUNDLE_DIR / "scenario-a"
    _write_json(prefix.with_name("scenario-a-submit-request.json"), seed_request)
    _write_json(prefix.with_name("scenario-a-submit-response.json"), seed_response)
    _write_json(prefix.with_name("scenario-a-completion-claim-request.json"), request_payload)
    _write_json(prefix.with_name("scenario-a-completion-claim-response.json"), {"status": claim_status, "response": claim_response})
    _write_json(prefix.with_name("scenario-a-read-model-initial.json"), read_initial)
    _write_json(prefix.with_name("scenario-a-read-model-final.json"), read_final)
    _write_json(prefix.with_name("scenario-a-timeline-initial.json"), timeline_initial)
    _write_json(prefix.with_name("scenario-a-timeline-final.json"), timeline_final)
    _write_json(prefix.with_name("scenario-a-evaluation-history-final.json"), history)

    checks = {
        "claim_http_200": claim_status == 200,
        "read_model_http_200": read_initial_status == 200 and read_final_status == 200,
        "timeline_http_200": timeline_initial_status == 200 and timeline_final_status == 200,
        "history_http_200": history_status == 200,
        "action_contract_violation_failed": claim_response.get("action") == "contract_violation_failed",
        "task_failed": claim_response.get("task_envelope", {}).get("status") == "failed",
        "invalid_execution_attempt_present": bool(claim_response.get("invalid_execution_attempt")),
    }
    return {
        "scenario": "a",
        "checks": checks,
        "all_checks_passed": all(checks.values()),
    }


def _scenario_b() -> dict:
    task = _base_task(
        task_id="task-kno-181-scenario-b",
        description="Scenario B: valid attributable execution attempt with missing PR proof.",
        executor_id="executor-kno-181-b",
    )
    seed_request, seed_response = _seed_artifacts(task)

    valid_attempt_payload = _execution_attempt_payload(attempt_id="attempt-kno-181-b-1")
    valid_attempt_payload["execution_attempt"]["recorded_at"] = "2026-04-01T08:00:05Z"
    valid_attempt_payload["execution_attempt"]["reported_by"] = "stub-executor"
    valid_attempt_payload["execution_attempt"]["metadata"] = {"executor_run_id": "stub-run-attempt-kno-181-b-1"}
    valid_attempt_payload["execution_attempt"]["artifact_references"] = [
        {
            "reference_id": "attempt-kno-181-b-1:commit",
            "artifact_type": "commit",
            "location": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/commit/8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
            "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
            "metadata": {
                "repository_host": "github.com",
                "repository_owner": "KnoxAnalytics",
                "repository_name": "HARNESS-DRYRUN",
                "branch_name": "codex/e2e-test",
                "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
            },
        }
    ]
    request_payload = {
        "request": {
            **_completion_claim_payload(claim_id="claim-kno-181-b-1"),
            **valid_attempt_payload,
            "runtime_facts": {"executor_reported_success": True, "attempt_count": 1},
        }
    }
    request_payload["request"]["completion_claim"]["reported_at"] = "2026-04-01T08:00:00Z"
    request_payload["request"]["completion_claim"]["reported_by"] = "stub-executor"

    with TemporaryDirectory(prefix="kno181-scenario-b-") as temp_dir:
        service = HarnessApiService(
            store=FileBackedHarnessStore(temp_dir),
            reconciliation_registry=_registry_with_no_create_pull_request_gateway(),
        )
        service.store.create_task(task)

        read_initial_status, read_initial = service.get_task_read_model(task["id"])
        timeline_initial_status, timeline_initial = service.get_task_timeline(task["id"])
        claim_status, claim_response = service.submit_completion_claim(task["id"], request_payload)
        read_final_status, read_final = service.get_task_read_model(task["id"])
        timeline_final_status, timeline_final = service.get_task_timeline(task["id"])
        history_status, history = service.get_evaluation_history(task["id"])

    prefix = BUNDLE_DIR / "scenario-b"
    _write_json(prefix.with_name("scenario-b-submit-request.json"), seed_request)
    _write_json(prefix.with_name("scenario-b-submit-response.json"), seed_response)
    _write_json(prefix.with_name("scenario-b-completion-claim-request.json"), request_payload)
    _write_json(prefix.with_name("scenario-b-completion-claim-response.json"), {"status": claim_status, "response": claim_response})
    _write_json(prefix.with_name("scenario-b-read-model-initial.json"), read_initial)
    _write_json(prefix.with_name("scenario-b-read-model-final.json"), read_final)
    _write_json(prefix.with_name("scenario-b-timeline-initial.json"), timeline_initial)
    _write_json(prefix.with_name("scenario-b-timeline-final.json"), timeline_final)
    _write_json(prefix.with_name("scenario-b-evaluation-history-final.json"), history)

    checks = {
        "claim_http_200": claim_status == 200,
        "read_model_http_200": read_initial_status == 200 and read_final_status == 200,
        "timeline_http_200": timeline_initial_status == 200 and timeline_final_status == 200,
        "history_http_200": history_status == 200,
        "action_reconciliation_failed": claim_response.get("action") == "reconciliation_failed",
        "task_in_review": claim_response.get("task_envelope", {}).get("status") == "in_review",
        "review_request_present": bool(claim_response.get("review_request")),
        "read_model_review_requested": ((read_final.get("task", {}).get("review_summary") or {}).get("status")) == "requested",
        "read_model_assignment_hidden": read_final.get("task", {}).get("assigned_executor") is None,
    }
    return {
        "scenario": "b",
        "checks": checks,
        "all_checks_passed": all(checks.values()),
    }


def main() -> None:
    BUNDLE_DIR.mkdir(parents=True, exist_ok=True)
    scenarios = [_scenario_a(), _scenario_b()]
    summary = {
        "proof_name": "kno-181-invalid-execution-attempt-gate",
        "execution_mode": "local-controlled",
        "hosted_validation": "not_performed",
        "scenarios": scenarios,
        "overall": {
            "all_scenarios_passed": all(item["all_checks_passed"] for item in scenarios),
            "conclusion": "validated" if all(item["all_checks_passed"] for item in scenarios) else "partially validated",
        },
    }
    _write_json(BUNDLE_DIR / "summary.json", summary)


if __name__ == "__main__":
    main()
