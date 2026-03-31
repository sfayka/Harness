"""Unattended dry-run loop for the deployed Harness backend."""

from __future__ import annotations

import json
import random
import string
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


@dataclass(frozen=True)
class RequestResult:
    status: int | None
    payload: dict[str, Any]
    error: str | None = None


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


def summarize_run(
    *,
    timestamp: str,
    scenario: str,
    task_id: str,
    create_result: RequestResult,
    evaluate_result: RequestResult,
    fetch_result: RequestResult,
    duration_ms: int,
    raw_files: dict[str, str],
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
    raw_files: dict[str, str] = {}

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
    if initial_fetch_result.status == 200 and isinstance(initial_fetch_result.payload.get("task"), dict):
        evaluate_payload = scenario.build_evaluate_payload(initial_fetch_result.payload["task"])
        raw_files["evaluate_request"] = _write_json(scenario_dir / "evaluate-request.json", evaluate_payload)
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
    )


def _scenario_line(entry: dict[str, Any]) -> str:
    return (
        f"[{entry['timestamp']}] scenario={entry['scenario']} task_id={entry['task_id']} "
        f"create={entry['create_http_status']} evaluate={entry['evaluate_http_status']} "
        f"fetch={entry['fetch_http_status']} final_status={entry['final_status']} "
        f"accepted={entry['accepted_completion']} requires_review={entry['requires_review']} "
        f"action={entry['action']} duration_ms={entry['duration_ms']}"
    )


def run_unattended_loop(
    *,
    base_url: str = DEFAULT_BASE_URL,
    output_dir: str = "runs",
    interval_seconds: float = 300.0,
    iterations: int = 0,
    timeout_seconds: float = 45.0,
    health_retries: int = 6,
    health_backoff_seconds: float = 5.0,
) -> int:
    client = HarnessRemoteClient(base_url, timeout_seconds=timeout_seconds)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    log_path = output_path / "log.jsonl"

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
                failure_entry = {
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
                }
                append_jsonl(log_path, failure_entry)
                print(_scenario_line(failure_entry))
            else:
                for scenario in CANONICAL_UNATTENDED_SCENARIOS:
                    scenario_started = time.monotonic()
                    try:
                        entry = run_scenario_once(
                            client,
                            scenario=scenario,
                            output_dir=output_path,
                            now=utc_now(),
                        )
                    except Exception as error:
                        failure_time = utc_now()
                        entry = {
                            "timestamp": isoformat_utc(failure_time),
                            "scenario": scenario.name,
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
                            "error": str(error),
                            "mismatch_categories": [],
                            "duration_ms": round((time.monotonic() - scenario_started) * 1000),
                            "raw_files": {},
                        }
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

    return {
        "base_url": os.environ.get("HARNESS_DRYRUN_BASE_URL", DEFAULT_BASE_URL),
        "output_dir": os.environ.get("HARNESS_DRYRUN_OUTPUT_DIR", "runs"),
        "interval_seconds": _float("HARNESS_DRYRUN_INTERVAL_SECONDS", 300.0),
        "iterations": _int("HARNESS_DRYRUN_ITERATIONS", 0),
        "timeout_seconds": _float("HARNESS_DRYRUN_TIMEOUT_SECONDS", 45.0),
        "health_retries": _int("HARNESS_DRYRUN_HEALTH_RETRIES", 6),
        "health_backoff_seconds": _float("HARNESS_DRYRUN_HEALTH_BACKOFF_SECONDS", 5.0),
    }


__all__ = [
    "CANONICAL_UNATTENDED_SCENARIOS",
    "DEFAULT_BASE_URL",
    "HarnessRemoteClient",
    "RequestResult",
    "append_jsonl",
    "build_task_id",
    "default_config_from_env",
    "run_scenario_once",
    "run_unattended_loop",
    "summarize_run",
]
