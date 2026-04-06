from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from modules.api import HarnessApiService
from modules.store import FileBackedHarnessStore
from tests.test_completion_claim_reconciliation import (
    _FakeGitHubGateway,
    _completion_claim_payload,
    _pull_request,
    _registry_with_gateway,
    _task_envelope,
)

BUNDLE_DIR = Path("docs/demo/kno-183-pr-create-readback-validation")


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _run_scenario(
    *,
    scenario_id: str,
    task_id: str,
    claim_id: str,
    gateway: _FakeGitHubGateway,
    expected_action: str,
    expected_status: str,
    expected_result: str,
    expected_revalidation: bool,
) -> dict:
    with TemporaryDirectory(prefix=f"{scenario_id}-") as temp_dir:
        service = HarnessApiService(
            store=FileBackedHarnessStore(temp_dir),
            reconciliation_registry=_registry_with_gateway(gateway),
        )
        task = _task_envelope(task_id=task_id)
        service.store.create_task(task)

        request_payload = _completion_claim_payload(claim_id)

        initial_read_model_status, initial_read_model = service.get_task_read_model(task_id)
        initial_timeline_status, initial_timeline = service.get_task_timeline(task_id)

        claim_status, claim_response = service.submit_completion_claim(task_id, request_payload)

        final_read_model_status, final_read_model = service.get_task_read_model(task_id)
        final_timeline_status, final_timeline = service.get_task_timeline(task_id)

    scenario_prefix = BUNDLE_DIR / f"scenario-{scenario_id}"
    _write_json(scenario_prefix.with_name(f"scenario-{scenario_id}-completion-claim-request.json"), request_payload)
    _write_json(scenario_prefix.with_name(f"scenario-{scenario_id}-completion-claim-response.json"), claim_response)
    _write_json(scenario_prefix.with_name(f"scenario-{scenario_id}-read-model-initial.json"), initial_read_model)
    _write_json(scenario_prefix.with_name(f"scenario-{scenario_id}-timeline-initial.json"), initial_timeline)
    _write_json(scenario_prefix.with_name(f"scenario-{scenario_id}-read-model-final.json"), final_read_model)
    _write_json(scenario_prefix.with_name(f"scenario-{scenario_id}-timeline-final.json"), final_timeline)

    attempts = claim_response.get("task_envelope", {}).get("reconciliation", {}).get("attempts", [])
    attempt = attempts[-1] if attempts else {}
    decision = attempt.get("details", {}).get("final_decision", {})

    checks = {
        "claim_status": claim_status == 200,
        "initial_read_model_status": initial_read_model_status == 200,
        "initial_timeline_status": initial_timeline_status == 200,
        "final_read_model_status": final_read_model_status == 200,
        "final_timeline_status": final_timeline_status == 200,
        "expected_action": claim_response.get("action") == expected_action,
        "expected_task_status": claim_response.get("task_envelope", {}).get("status") == expected_status,
        "expected_final_decision": decision.get("result") == expected_result,
        "expected_revalidation": attempt.get("details", {}).get("created_pull_request_revalidated") == expected_revalidation,
    }

    return {
        "scenario": scenario_id,
        "task_id": task_id,
        "claim_id": claim_id,
        "expected": {
            "action": expected_action,
            "task_status": expected_status,
            "final_decision_result": expected_result,
            "created_pull_request_revalidated": expected_revalidation,
        },
        "actual": {
            "http_status": claim_status,
            "action": claim_response.get("action"),
            "task_status": claim_response.get("task_envelope", {}).get("status"),
            "final_decision": decision,
            "created_pull_request": attempt.get("details", {}).get("created_pull_request"),
            "created_pull_request_revalidated": attempt.get("details", {}).get("created_pull_request_revalidated"),
            "get_pull_request_calls": gateway.get_pull_request_calls,
            "create_pull_request_calls": gateway.create_calls,
        },
        "checks": checks,
        "all_checks_passed": all(checks.values()),
    }


def main() -> None:
    scenario_a = _run_scenario(
        scenario_id="a",
        task_id="task-kno-183-scenario-a",
        claim_id="claim-kno-183-a",
        gateway=_FakeGitHubGateway(created_pr=_pull_request(number=631)),
        expected_action="transition_applied",
        expected_status="completed",
        expected_result="created_new",
        expected_revalidation=True,
    )

    scenario_b = _run_scenario(
        scenario_id="b",
        task_id="task-kno-183-scenario-b",
        claim_id="claim-kno-183-b",
        gateway=_FakeGitHubGateway(
            created_pr=_pull_request(number=632),
            persisted_created_pr=None,
        ),
        expected_action="reconciliation_failed",
        expected_status="in_review",
        expected_result="created_pull_request_revalidation_failed",
        expected_revalidation=False,
    )

    scenario_c = _run_scenario(
        scenario_id="c",
        task_id="task-kno-183-scenario-c",
        claim_id="claim-kno-183-c",
        gateway=_FakeGitHubGateway(
            created_pr=_pull_request(number=633),
            persisted_created_pr=_pull_request(
                number=633,
                head_sha="1111111111111111111111111111111111111111",
            ),
        ),
        expected_action="reconciliation_failed",
        expected_status="in_review",
        expected_result="created_pull_request_revalidation_failed",
        expected_revalidation=False,
    )

    summary = {
        "proof_name": "kno-183-pr-create-readback-validation",
        "execution_mode": "local-controlled",
        "hosted_validation": "not_performed",
        "scenarios": [scenario_a, scenario_b, scenario_c],
    }
    summary["overall"] = {
        "all_scenarios_passed": all(item["all_checks_passed"] for item in summary["scenarios"]),
        "conclusion": "validated" if all(item["all_checks_passed"] for item in summary["scenarios"]) else "partially validated",
    }
    _write_json(BUNDLE_DIR / "summary.json", summary)


if __name__ == "__main__":
    main()
