"""Thin OpenClaw callback client for repair requests."""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any
from urllib import error, request


class OpenClawRepairClientError(ValueError):
    """Raised when the repair callback cannot be delivered."""


def _normalize_timeout(value: float) -> str:
    return format(value, "g")


def _sanitize_session_fragment(value: str) -> str:
    cleaned = "".join(character.lower() if character.isalnum() else "-" for character in value)
    collapsed = "-".join(part for part in cleaned.split("-") if part)
    return collapsed or "repair"


def _extract_json_payload(raw_output: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    for index, character in enumerate(raw_output):
        if character != "{":
            continue
        try:
            payload, end = decoder.raw_decode(raw_output[index:])
        except json.JSONDecodeError:
            continue
        if raw_output[index + end :].strip():
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _repair_message(issue_id: str, *, reason: str, contract_id: str | None) -> str:
    lines = [
        f"Harness rejected completion for Linear issue {issue_id}.",
        f"Harness contract id: {contract_id or 'unknown'}.",
        f"Verification failure: {reason}.",
        "Re-dispatch work in OpenClaw, use the issue's existing repo and branch context, and do not treat the task as complete until there is a real repository, branch, commit SHA, and PR URL.",
    ]
    return "\n".join(lines)


class OpenClawRepairClient:
    """Requests OpenClaw repair over HTTP or through the local CLI."""

    def __init__(
        self,
        *,
        transport: str | None = None,
        base_url: str | None = None,
        repair_endpoint: str | None = None,
        cli_bin: str | None = None,
        config_path: str | None = None,
        state_dir: str | None = None,
        agent_id: str | None = None,
        session_prefix: str | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.base_url = (base_url or os.getenv("OPENCLAW_BASE_URL") or "").rstrip("/")
        self.repair_endpoint = repair_endpoint or os.getenv("OPENCLAW_REPAIR_ENDPOINT") or "/repair"
        self.cli_bin = cli_bin or os.getenv("OPENCLAW_BIN") or "openclaw"
        self.config_path = config_path or os.getenv("OPENCLAW_CONFIG_PATH")
        self.state_dir = state_dir or os.getenv("OPENCLAW_STATE_DIR")
        self.agent_id = agent_id or os.getenv("OPENCLAW_AGENT_ID") or "harness-local"
        self.session_prefix = (session_prefix or os.getenv("OPENCLAW_REPAIR_SESSION_PREFIX") or "harness-repair").strip()
        self.timeout_seconds = timeout_seconds
        self.transport = transport or os.getenv("OPENCLAW_REPAIR_TRANSPORT") or self._default_transport()

    def request_repair(self, issue_id: str, *, reason: str, contract_id: str | None = None) -> dict[str, Any]:
        if self.transport == "cli":
            return self._request_repair_cli(issue_id, reason=reason, contract_id=contract_id)
        if self.transport != "http":
            raise OpenClawRepairClientError(f"Unsupported OpenClaw repair transport: {self.transport}")
        return self._request_repair_http(issue_id, reason=reason, contract_id=contract_id)

    def _default_transport(self) -> str:
        if self.config_path or self.state_dir:
            return "cli"
        return "http"

    def _request_repair_http(self, issue_id: str, *, reason: str, contract_id: str | None = None) -> dict[str, Any]:
        if not self.base_url:
            raise OpenClawRepairClientError("OPENCLAW_BASE_URL is required")
        url = f"{self.base_url}{self.repair_endpoint}"
        payload = {"linear_issue_id": issue_id, "reason": reason, "contract_id": contract_id}
        req = request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                raw_body = response.read().decode("utf-8")
                return json.loads(raw_body) if raw_body else {"status": "ok"}
        except error.HTTPError as http_error:
            raise OpenClawRepairClientError(f"OpenClaw repair callback failed: HTTP {http_error.code}") from http_error
        except error.URLError as url_error:
            raise OpenClawRepairClientError(f"OpenClaw repair callback failed: {url_error.reason}") from url_error

    def _request_repair_cli(self, issue_id: str, *, reason: str, contract_id: str | None = None) -> dict[str, Any]:
        session_id = f"{self.session_prefix}-{_sanitize_session_fragment(issue_id)}"
        command = [
            self.cli_bin,
            "agent",
            "--local",
            "--agent",
            self.agent_id,
            "--session-id",
            session_id,
            "--message",
            _repair_message(issue_id, reason=reason, contract_id=contract_id),
            "--json",
            "--timeout",
            _normalize_timeout(self.timeout_seconds),
        ]
        env = os.environ.copy()
        if self.config_path:
            env["OPENCLAW_CONFIG_PATH"] = self.config_path
        if self.state_dir:
            env["OPENCLAW_STATE_DIR"] = self.state_dir

        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                env=env,
                timeout=max(self.timeout_seconds + 5.0, 15.0),
            )
        except OSError as os_error:
            raise OpenClawRepairClientError(f"OpenClaw CLI repair dispatch failed: {os_error}") from os_error
        except subprocess.TimeoutExpired as timeout_error:
            raise OpenClawRepairClientError("OpenClaw CLI repair dispatch timed out") from timeout_error

        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()
        payload = _extract_json_payload(stdout) if stdout else None

        if completed.returncode != 0:
            detail = stderr or stdout or "unknown error"
            raise OpenClawRepairClientError(f"OpenClaw CLI repair dispatch failed: {detail}")
        if payload is None:
            raise OpenClawRepairClientError("OpenClaw CLI repair dispatch did not return JSON output")
        if payload.get("meta", {}).get("stopReason") == "error":
            payloads = payload.get("payloads") or []
            detail = payloads[0].get("text") if payloads and isinstance(payloads[0], dict) else "agent run failed"
            raise OpenClawRepairClientError(f"OpenClaw CLI repair dispatch failed: {detail}")
        return payload


__all__ = ["OpenClawRepairClient", "OpenClawRepairClientError"]
