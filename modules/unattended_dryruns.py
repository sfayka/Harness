"""Unattended dry-run loop for the deployed Harness backend."""

from __future__ import annotations

import json
import random
import string
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from modules.runtime_scenario_builders import (
    CANONICAL_UNATTENDED_SCENARIOS,
    RuntimeScenarioDefinition,
    build_create_task_payload,
)


DEFAULT_BASE_URL = "https://harness-qeav.onrender.com"
E2E_SUITE_COMMAND = [
    sys.executable,
    "-m",
    "unittest",
    "discover",
    "-s",
    "tests/e2e",
    "-p",
    "test_*.py",
]


@dataclass(frozen=True)
class RequestResult:
    status: int | None
    payload: dict[str, Any]
    error: str | None = None


@dataclass(frozen=True)
class FailureClassification:
    category: str
    retryable: bool
    suggested_action: str
    confidence: float | None = None


@dataclass
class RunnerSessionState:
    e2e_suite_runs: int = 0


@dataclass(frozen=True)
class E2ESuiteResult:
    ran: bool
    passed: bool | None
    exit_code: int | None
    output_path: str | None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat_utc(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def compact_utc(dt: datetime) -> str:
    return dt.replace(microsecond=0).strftime("%Y%m%dT%H%M%SZ")


def build_task_id(scenario: str, *, at: datetime | None = None, suffix: str | None = None) -> str:
    timestamp = compact_utc(at or utc_now())
    token = suffix or "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    normalized = scenario.replace("_", "-")
    return f"dryrun-{normalized}-{timestamp}-{token}"


class HarnessRemoteClient:
    """Tiny JSON client for the deployed Harness API."""

    def __init__(self, base_url: str, *, timeout_seconds: float = 45.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> RequestResult:
        body = None
        headers: dict[str, str] = {}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(self.base_url + path, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return RequestResult(
                    status=response.status,
                    payload=json.loads(response.read().decode("utf-8")),
                )
        except HTTPError as error:
            try:
                payload = json.loads(error.read().decode("utf-8"))
            except Exception:
                payload = {"error": f"HTTP {error.code}"}
            finally:
                error.close()
            return RequestResult(status=error.code, payload=payload, error=payload.get("error"))
        except URLError as error:
            return RequestResult(status=None, payload={"error": str(error.reason)}, error=str(error.reason))
        except TimeoutError as error:
            return RequestResult(status=None, payload={"error": str(error)}, error=str(error))

    def get_json(self, path: str) -> RequestResult:
        return self.request("GET", path)

    def post_json(self, path: str, payload: dict[str, Any]) -> RequestResult:
        return self.request("POST", path, payload)


def _write_json(path: Path, payload: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return str(path)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def warm_backend(
    client: HarnessRemoteClient,
    *,
    raw_dir: Path,
    retries: int,
    backoff_seconds: float,
) -> tuple[bool, list[str]]:
    raw_files: list[str] = []
    for attempt in range(1, retries + 1):
        started = time.monotonic()
        result = client.get_json("/health")
        elapsed_ms = round((time.monotonic() - started) * 1000)
        raw_files.append(
            _write_json(
                raw_dir / f"health-attempt-{attempt:02d}.json",
                {
                    "status": result.status,
                    "payload": result.payload,
                    "error": result.error,
                    "duration_ms": elapsed_ms,
                },
            )
        )
        if result.status == 200:
            return True, raw_files
        if attempt < retries:
            time.sleep(backoff_seconds * attempt)
    return False, raw_files


def actual_outcome_from_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "accepted_completion": entry.get("accepted_completion"),
        "final_status": entry.get("final_status"),
        "requires_review": entry.get("requires_review"),
    }


def classify_outcome(
    expected_outcome: dict[str, Any],
    actual_outcome: dict[str, Any],
) -> tuple[bool, str]:
    matched = all(actual_outcome.get(key) == value for key, value in expected_outcome.items())
    if not matched:
        return False, "unexpected_failure"
    if expected_outcome.get("accepted_completion") is True:
        return True, "expected_success"
    return True, "expected_semantic_failure"


def _contains_any(text: str, fragments: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(fragment in lowered for fragment in fragments)


def classify_unexpected_failure(entry: dict[str, Any]) -> FailureClassification:
    stage = entry.get("attempt_error_stage")
    error_text = str(entry.get("error") or "")
    statuses = [
        entry.get("create_http_status"),
        entry.get("evaluate_http_status"),
        entry.get("fetch_http_status"),
    ]

    if stage == "payload_build":
        return FailureClassification(
            category="payload_build_failure",
            retryable=False,
            suggested_action="Inspect the scenario builder or payload overlay assembly for this scenario.",
            confidence=0.98,
        )

    if _contains_any(error_text, ("timed out", "timeout")):
        return FailureClassification(
            category="render_cold_start_timeout",
            retryable=True,
            suggested_action="Warm /health and retry within the capped retry budget.",
            confidence=0.9,
        )

    if any(status in {502, 503, 504} for status in statuses if status is not None):
        return FailureClassification(
            category="backend_unavailable",
            retryable=True,
            suggested_action="Warm /health and retry; the hosted backend appears unavailable.",
            confidence=0.9,
        )

    if any(status is None for status in statuses):
        if _contains_any(
            error_text,
            (
                "connection refused",
                "connection reset",
                "temporarily unavailable",
                "temporary failure",
                "remote end closed",
                "name or service not known",
                "nodename nor servname",
            ),
        ):
            return FailureClassification(
                category="transient_transport",
                retryable=True,
                suggested_action="Retry this scenario within bounds; transport failed before a stable API response arrived.",
                confidence=0.85,
            )
        return FailureClassification(
            category="backend_unavailable",
            retryable=True,
            suggested_action="Warm /health and retry; the backend did not return a usable response.",
            confidence=0.75,
        )

    if any(status is not None and 400 <= status < 500 for status in statuses):
        return FailureClassification(
            category="unexpected_runtime_regression",
            retryable=False,
            suggested_action="Inspect the raw API artifacts and compare them to the canonical runtime E2E suite.",
            confidence=0.8,
        )

    if entry.get("evaluate_http_status") == 200 and not entry.get("expected_outcome_matched", False):
        return FailureClassification(
            category="unexpected_runtime_regression",
            retryable=False,
            suggested_action="Inspect the raw API artifacts and run the runtime E2E suite locally.",
            confidence=0.9,
        )

    return FailureClassification(
        category="unknown",
        retryable=False,
        suggested_action="Inspect the raw artifacts and run the runtime E2E suite once for comparison.",
        confidence=0.4,
    )


def should_run_e2e_suite(classification: FailureClassification) -> bool:
    return classification.category in {"unexpected_runtime_regression", "unknown"}


def run_e2e_suite(*, output_dir: Path, session_state: RunnerSessionState, max_runs: int) -> E2ESuiteResult:
    if max_runs <= 0 or session_state.e2e_suite_runs >= max_runs:
        return E2ESuiteResult(ran=False, passed=None, exit_code=None, output_path=None)

    session_state.e2e_suite_runs += 1
    timestamp = compact_utc(utc_now())
    report_path = output_dir / "reports" / f"e2e-suite-{timestamp}.txt"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        E2E_SUITE_COMMAND,
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
    )
    report_path.write_text(
        f"$ {' '.join(E2E_SUITE_COMMAND)}\n\n{completed.stdout}\n{completed.stderr}",
        encoding="utf-8",
    )
    return E2ESuiteResult(
        ran=True,
        passed=completed.returncode == 0,
        exit_code=completed.returncode,
        output_path=str(report_path),
    )


def write_diagnostic_report(
    *,
    output_dir: Path,
    scenario: str,
    task_id: str | None,
    payload: dict[str, Any],
) -> str:
    timestamp = compact_utc(utc_now())
    normalized_task_id = task_id or "no-task-id"
    report_path = output_dir / "reports" / f"{timestamp}-{scenario}-{normalized_task_id}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return str(report_path)


def summarize_run(
    *,
    timestamp: str,
    scenario: str,
    task_id: str,
    create_result: RequestResult,
    evaluate_result: RequestResult,
    fetch_result: RequestResult,
    duration_ms: int,
    raw_files: dict[str, Any],
    attempt_error_stage: str | None = None,
) -> dict[str, Any]:
    verification = ((evaluate_result.payload.get("enforcement_result") or {}).get("verification_result") or {})
    reconciliation = ((evaluate_result.payload.get("enforcement_result") or {}).get("reconciliation_result") or {})
    fetched_task = fetch_result.payload.get("task") if isinstance(fetch_result.payload.get("task"), dict) else {}

    error = evaluate_result.error or fetch_result.error or create_result.error
    if error is None and evaluate_result.status not in {None, 200}:
        error = evaluate_result.payload.get("error")
    if error is None and create_result.status not in {None, 200}:
        error = create_result.payload.get("error")

    return {
        "timestamp": timestamp,
        "scenario": scenario,
        "task_id": task_id,
        "create_http_status": create_result.status,
        "evaluate_http_status": evaluate_result.status,
        "fetch_http_status": fetch_result.status,
        "accepted_completion": evaluate_result.payload.get("accepted_completion"),
        "verification_passed": verification.get("verification_passed"),
        "reconciliation_status": verification.get("reconciliation_status") or reconciliation.get("status"),
        "requires_review": evaluate_result.payload.get("requires_review"),
        "final_status": fetched_task.get("status"),
        "action": evaluate_result.payload.get("action"),
        "error": error,
        "mismatch_categories": reconciliation.get("mismatch_categories", []),
        "duration_ms": duration_ms,
        "raw_files": raw_files,
        "attempt_error_stage": attempt_error_stage,
    }


def run_scenario_once(
    client: HarnessRemoteClient,
    *,
    scenario: RuntimeScenarioDefinition,
    output_dir: Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    scenario_started = time.monotonic()
    started_at = now or utc_now()
    timestamp = isoformat_utc(started_at)
    task_id = build_task_id(scenario.name, at=started_at)
    scenario_dir = output_dir / "raw" / compact_utc(started_at) / scenario.name / task_id
    raw_files: dict[str, Any] = {}

    create_payload = build_create_task_payload(
        task_id,
        title=f"Unattended dry-run {scenario.name}",
        now=timestamp,
    )
    raw_files["create_request"] = _write_json(scenario_dir / "create-request.json", create_payload)
    create_result = client.post_json("/tasks", create_payload)
    raw_files["create_response"] = _write_json(
        scenario_dir / "create-response.json",
        {"status": create_result.status, "payload": create_result.payload, "error": create_result.error},
    )

    effective_task_id = (
        ((create_result.payload.get("task_envelope") or {}).get("id"))
        if isinstance(create_result.payload.get("task_envelope"), dict)
        else task_id
    ) or task_id

    initial_fetch_result = RequestResult(status=None, payload={}, error="create_failed")
    if create_result.status == 200:
        initial_fetch_result = client.get_json(f"/tasks/{effective_task_id}")
        raw_files["initial_fetch_response"] = _write_json(
            scenario_dir / "initial-fetch-response.json",
            {"status": initial_fetch_result.status, "payload": initial_fetch_result.payload, "error": initial_fetch_result.error},
        )
    else:
        raw_files["initial_fetch_response"] = _write_json(
            scenario_dir / "initial-fetch-response.json",
            {"status": None, "payload": {}, "error": "skipped because create failed"},
        )

    evaluate_result = RequestResult(status=None, payload={}, error="evaluate_skipped")
    attempt_error_stage: str | None = None
    if initial_fetch_result.status == 200 and isinstance(initial_fetch_result.payload.get("task"), dict):
        try:
            evaluate_payload = scenario.build_evaluate_payload(initial_fetch_result.payload["task"])
        except Exception as error:
            attempt_error_stage = "payload_build"
            evaluate_payload = {"error": str(error)}
            evaluate_result = RequestResult(status=None, payload={}, error=str(error))
        raw_files["evaluate_request"] = _write_json(scenario_dir / "evaluate-request.json", evaluate_payload)
        if attempt_error_stage is None:
            evaluate_result = client.post_json("/evaluate", evaluate_payload)
        raw_files["evaluate_response"] = _write_json(
            scenario_dir / "evaluate-response.json",
            {"status": evaluate_result.status, "payload": evaluate_result.payload, "error": evaluate_result.error},
        )
    else:
        raw_files["evaluate_request"] = _write_json(
            scenario_dir / "evaluate-request.json",
            {"error": "skipped because initial fetch failed"},
        )
        raw_files["evaluate_response"] = _write_json(
            scenario_dir / "evaluate-response.json",
            {"status": None, "payload": {}, "error": "skipped because initial fetch failed"},
        )

    final_fetch_result = RequestResult(status=None, payload={}, error="final_fetch_skipped")
    if create_result.status == 200:
        final_fetch_result = client.get_json(f"/tasks/{effective_task_id}")
        raw_files["final_fetch_response"] = _write_json(
            scenario_dir / "final-fetch-response.json",
            {"status": final_fetch_result.status, "payload": final_fetch_result.payload, "error": final_fetch_result.error},
        )
    else:
        raw_files["final_fetch_response"] = _write_json(
            scenario_dir / "final-fetch-response.json",
            {"status": None, "payload": {}, "error": "skipped because create failed"},
        )

    return summarize_run(
        timestamp=timestamp,
        scenario=scenario.name,
        task_id=effective_task_id,
        create_result=create_result,
        evaluate_result=evaluate_result,
        fetch_result=final_fetch_result,
        duration_ms=round((time.monotonic() - scenario_started) * 1000),
        raw_files=raw_files,
        attempt_error_stage=attempt_error_stage,
    )


def enrich_entry_with_expectations(entry: dict[str, Any], scenario: RuntimeScenarioDefinition) -> dict[str, Any]:
    expected_outcome = dict(scenario.expected_outcome)
    actual_outcome = actual_outcome_from_entry(entry)
    matched, outcome_class = classify_outcome(expected_outcome, actual_outcome)
    enriched = dict(entry)
    enriched.update(
        {
            "expected_outcome": expected_outcome,
            "actual_outcome": actual_outcome,
            "outcome_class": outcome_class,
            "expected_outcome_matched": matched,
        }
    )
    return enriched


def _scenario_line(entry: dict[str, Any]) -> str:
    return (
        f"[{entry['timestamp']}] scenario={entry['scenario']} task_id={entry['task_id']} "
        f"outcome={entry.get('outcome_class')} classification={entry.get('classification')} "
        f"create={entry['create_http_status']} evaluate={entry['evaluate_http_status']} "
        f"fetch={entry['fetch_http_status']} final_status={entry['final_status']} "
        f"accepted={entry['accepted_completion']} requires_review={entry['requires_review']} "
        f"retry_count={entry.get('retry_count')} retry_result={entry.get('retry_result')}"
    )


def execute_scenario_with_policy(
    client: HarnessRemoteClient,
    *,
    scenario: RuntimeScenarioDefinition,
    output_dir: Path,
    session_state: RunnerSessionState,
    health_retries: int,
    health_backoff_seconds: float,
    max_retries: int,
    diagnostics_enabled: bool,
    max_e2e_suite_runs: int,
) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    warmup_files: list[str] = []

    for retry_index in range(max_retries + 1):
        if retry_index > 0 and warmup_files:
            warm_key = f"retry_health_attempt_{retry_index}"
        else:
            warm_key = None

        entry = enrich_entry_with_expectations(
            run_scenario_once(
                client,
                scenario=scenario,
                output_dir=output_dir,
                now=utc_now(),
            ),
            scenario,
        )
        attempts.append(entry)

        if entry["expected_outcome_matched"]:
            entry["classification"] = "none"
            entry["retryable"] = False
            entry["suggested_action"] = "No action required."
            entry["confidence"] = None
            entry["retry_count"] = retry_index
            entry["retry_result"] = "not_needed" if retry_index == 0 else "succeeded_after_retry"
            entry["e2e_suite_run"] = False
            entry["e2e_suite_passed"] = None
            entry["e2e_suite_exit_code"] = None
            entry["e2e_suite_output_path"] = None
            entry["report_path"] = None
            if warm_key:
                entry["raw_files"][warm_key] = warmup_files
            return entry

        classification = classify_unexpected_failure(entry)
        should_retry = classification.retryable and retry_index < max_retries
        if should_retry:
            warmed, health_files = warm_backend(
                client,
                raw_dir=output_dir / "raw" / compact_utc(utc_now()) / "_retry_health" / scenario.name,
                retries=health_retries,
                backoff_seconds=health_backoff_seconds,
            )
            warmup_files = health_files
            if not warmed:
                classification = FailureClassification(
                    category="backend_unavailable",
                    retryable=False,
                    suggested_action="Hosted backend stayed unavailable after warmup retries.",
                    confidence=0.9,
                )
                should_retry = False

        if should_retry:
            continue

        e2e_result = E2ESuiteResult(ran=False, passed=None, exit_code=None, output_path=None)
        if diagnostics_enabled and should_run_e2e_suite(classification):
            e2e_result = run_e2e_suite(
                output_dir=output_dir,
                session_state=session_state,
                max_runs=max_e2e_suite_runs,
            )

        retry_result = "retry_exhausted" if classification.retryable and retry_index >= max_retries else "not_retryable"
        final_entry = dict(entry)
        final_entry.update(
            {
                "classification": classification.category,
                "retryable": classification.retryable,
                "suggested_action": classification.suggested_action,
                "confidence": classification.confidence,
                "retry_count": retry_index,
                "retry_result": retry_result,
                "e2e_suite_run": e2e_result.ran,
                "e2e_suite_passed": e2e_result.passed,
                "e2e_suite_exit_code": e2e_result.exit_code,
                "e2e_suite_output_path": e2e_result.output_path,
            }
        )
        if warmup_files:
            final_entry["raw_files"][f"retry_health_attempt_{retry_index}"] = warmup_files

        if diagnostics_enabled:
            final_entry["report_path"] = write_diagnostic_report(
                output_dir=output_dir,
                scenario=scenario.name,
                task_id=final_entry.get("task_id"),
                payload={
                    "scenario": scenario.name,
                    "expected_outcome": final_entry["expected_outcome"],
                    "actual_outcome": final_entry["actual_outcome"],
                    "classification": classification.category,
                    "retry_attempts": retry_index,
                    "retryable": classification.retryable,
                    "retry_result": retry_result,
                    "suggested_action": classification.suggested_action,
                    "confidence": classification.confidence,
                    "e2e_suite": {
                        "ran": e2e_result.ran,
                        "passed": e2e_result.passed,
                        "exit_code": e2e_result.exit_code,
                        "output_path": e2e_result.output_path,
                    },
                    "attempts": attempts,
                    "raw_files": final_entry["raw_files"],
                },
            )
        else:
            final_entry["report_path"] = None
        return final_entry

    # Defensive fallback: the loop above should always return.
    fallback = enrich_entry_with_expectations(
        run_scenario_once(client, scenario=scenario, output_dir=output_dir, now=utc_now()),
        scenario,
    )
    fallback.update(
        {
            "classification": "unknown",
            "retryable": False,
            "suggested_action": "Inspect the raw artifacts for this scenario.",
            "confidence": 0.1,
            "retry_count": max_retries,
            "retry_result": "retry_exhausted",
            "e2e_suite_run": False,
            "e2e_suite_passed": None,
            "e2e_suite_exit_code": None,
            "e2e_suite_output_path": None,
            "report_path": None,
        }
    )
    return fallback


def run_unattended_loop(
    *,
    base_url: str = DEFAULT_BASE_URL,
    output_dir: str = "runs",
    interval_seconds: float = 300.0,
    iterations: int = 0,
    timeout_seconds: float = 45.0,
    health_retries: int = 6,
    health_backoff_seconds: float = 5.0,
    max_retries: int = 2,
    diagnostics_enabled: bool = True,
    max_e2e_suite_runs: int = 1,
) -> int:
    client = HarnessRemoteClient(base_url, timeout_seconds=timeout_seconds)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    log_path = output_path / "log.jsonl"
    session_state = RunnerSessionState()

    loop_count = 0
    try:
        while iterations == 0 or loop_count < iterations:
            loop_count += 1
            loop_started_at = utc_now()
            loop_dir = output_path / "raw" / compact_utc(loop_started_at) / "_health"
            warmed, health_files = warm_backend(
                client,
                raw_dir=loop_dir,
                retries=health_retries,
                backoff_seconds=health_backoff_seconds,
            )
            if not warmed:
                health_entry = {
                    "timestamp": isoformat_utc(loop_started_at),
                    "scenario": "_health",
                    "task_id": None,
                    "create_http_status": None,
                    "evaluate_http_status": None,
                    "fetch_http_status": None,
                    "accepted_completion": None,
                    "verification_passed": None,
                    "reconciliation_status": None,
                    "requires_review": None,
                    "final_status": None,
                    "action": None,
                    "error": "Backend health check did not return HTTP 200 before retries were exhausted",
                    "mismatch_categories": [],
                    "duration_ms": None,
                    "raw_files": {"health": health_files},
                    "attempt_error_stage": "health",
                    "expected_outcome": None,
                    "actual_outcome": None,
                    "outcome_class": "unexpected_failure",
                    "expected_outcome_matched": False,
                    "classification": "backend_unavailable",
                    "retryable": False,
                    "suggested_action": "Inspect Render availability or rerun once the backend becomes healthy.",
                    "confidence": 0.95,
                    "retry_count": 0,
                    "retry_result": "not_retryable",
                    "e2e_suite_run": False,
                    "e2e_suite_passed": None,
                    "e2e_suite_exit_code": None,
                    "e2e_suite_output_path": None,
                    "report_path": None,
                }
                if diagnostics_enabled:
                    health_entry["report_path"] = write_diagnostic_report(
                        output_dir=output_path,
                        scenario="_health",
                        task_id=None,
                        payload={
                            "scenario": "_health",
                            "classification": health_entry["classification"],
                            "retry_attempts": 0,
                            "e2e_suite": {
                                "ran": False,
                                "passed": None,
                                "exit_code": None,
                                "output_path": None,
                            },
                            "raw_files": health_entry["raw_files"],
                            "suggested_action": health_entry["suggested_action"],
                        },
                    )
                append_jsonl(log_path, health_entry)
                print(_scenario_line(health_entry))
            else:
                for scenario in CANONICAL_UNATTENDED_SCENARIOS:
                    entry = execute_scenario_with_policy(
                        client,
                        scenario=scenario,
                        output_dir=output_path,
                        session_state=session_state,
                        health_retries=health_retries,
                        health_backoff_seconds=health_backoff_seconds,
                        max_retries=max_retries,
                        diagnostics_enabled=diagnostics_enabled,
                        max_e2e_suite_runs=max_e2e_suite_runs,
                    )
                    append_jsonl(log_path, entry)
                    print(_scenario_line(entry))

            if iterations != 0 and loop_count >= iterations:
                break
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        print("Unattended dry-run loop interrupted.")
        return 130
    return 0


def default_config_from_env() -> dict[str, Any]:
    import os

    def _float(name: str, default: float) -> float:
        value = os.environ.get(name)
        return float(value) if value else default

    def _int(name: str, default: int) -> int:
        value = os.environ.get(name)
        return int(value) if value else default

    def _bool(name: str, default: bool) -> bool:
        value = os.environ.get(name)
        if value is None:
            return default
        return value.lower() not in {"0", "false", "no", "off"}

    return {
        "base_url": os.environ.get("HARNESS_DRYRUN_BASE_URL", DEFAULT_BASE_URL),
        "output_dir": os.environ.get("HARNESS_DRYRUN_OUTPUT_DIR", "runs"),
        "interval_seconds": _float("HARNESS_DRYRUN_INTERVAL_SECONDS", 300.0),
        "iterations": _int("HARNESS_DRYRUN_ITERATIONS", 0),
        "timeout_seconds": _float("HARNESS_DRYRUN_TIMEOUT_SECONDS", 45.0),
        "health_retries": _int("HARNESS_DRYRUN_HEALTH_RETRIES", 6),
        "health_backoff_seconds": _float("HARNESS_DRYRUN_HEALTH_BACKOFF_SECONDS", 5.0),
        "max_retries": _int("HARNESS_DRYRUN_MAX_RETRIES", 2),
        "diagnostics_enabled": _bool("HARNESS_DRYRUN_DIAGNOSTICS_ENABLED", True),
        "max_e2e_suite_runs": _int("HARNESS_DRYRUN_MAX_E2E_SUITE_RUNS", 1),
    }


__all__ = [
    "CANONICAL_UNATTENDED_SCENARIOS",
    "DEFAULT_BASE_URL",
    "E2ESuiteResult",
    "FailureClassification",
    "HarnessRemoteClient",
    "RequestResult",
    "RunnerSessionState",
    "actual_outcome_from_entry",
    "append_jsonl",
    "build_task_id",
    "classify_outcome",
    "classify_unexpected_failure",
    "default_config_from_env",
    "execute_scenario_with_policy",
    "run_e2e_suite",
    "run_scenario_once",
    "run_unattended_loop",
    "should_run_e2e_suite",
    "summarize_run",
    "write_diagnostic_report",
]
