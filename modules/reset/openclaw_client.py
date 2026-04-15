"""Thin OpenClaw callback client for repair requests."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib import error, request


class OpenClawRepairClientError(ValueError):
    """Raised when the repair callback cannot be delivered."""


class OpenClawRepairClient:
    """Minimal HTTP client that asks OpenClaw to repair an issue."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        repair_endpoint: str | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.base_url = (base_url or os.getenv("OPENCLAW_BASE_URL") or "").rstrip("/")
        self.repair_endpoint = repair_endpoint or os.getenv("OPENCLAW_REPAIR_ENDPOINT") or "/repair"
        self.timeout_seconds = timeout_seconds

    def request_repair(self, issue_id: str, *, reason: str, contract_id: str | None = None) -> dict[str, Any]:
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


__all__ = ["OpenClawRepairClient", "OpenClawRepairClientError"]
