"""Contracts for the reset-slice verifier workflow."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from fnmatch import fnmatch
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class ResetVerificationContractError(ValueError):
    """Raised when reset-slice contract input is malformed."""


def _require_text(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ResetVerificationContractError(f"{field_name} is required")
    return normalized


@dataclass(frozen=True)
class ResetEvent:
    timestamp: str
    kind: str
    message: str

    @classmethod
    def create(cls, *, kind: str, message: str, timestamp: str | None = None) -> "ResetEvent":
        return cls(timestamp=timestamp or _utc_now(), kind=kind, message=message)


@dataclass(frozen=True)
class ResetCompletionClaim:
    repository_owner: str
    repository_name: str
    branch_name: str
    commit_sha: str
    pull_request_number: int | None = None
    pull_request_url: str | None = None
    claimed_at: str = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "repository_owner", _require_text(self.repository_owner, field_name="repository_owner"))
        object.__setattr__(self, "repository_name", _require_text(self.repository_name, field_name="repository_name"))
        object.__setattr__(self, "branch_name", _require_text(self.branch_name, field_name="branch_name"))
        object.__setattr__(self, "commit_sha", _require_text(self.commit_sha, field_name="commit_sha"))
        if not (self.pull_request_url or "").strip():
            raise ResetVerificationContractError("pull_request_url is required")

    def asdict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ResetCompletionClaim":
        return cls(**payload)


@dataclass(frozen=True)
class ResetVerificationContract:
    contract_id: str
    linear_issue_id: str
    repository_owner: str
    repository_name: str
    branch_ref: str
    retry_count: int = 0
    retry_budget: int = 2
    harness_status: str = "running"
    latest_claim: ResetCompletionClaim | None = None
    latest_verdict: str | None = None
    latest_reason: str | None = None
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    last_activity_at: str | None = None
    last_repair_requested_at: str | None = None
    last_verified_at: str | None = None
    claim_timeout_seconds: int | None = None
    event_log: tuple[ResetEvent, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "contract_id", _require_text(self.contract_id, field_name="contract_id"))
        object.__setattr__(self, "linear_issue_id", _require_text(self.linear_issue_id, field_name="linear_issue_id"))
        object.__setattr__(self, "repository_owner", _require_text(self.repository_owner, field_name="repository_owner"))
        object.__setattr__(self, "repository_name", _require_text(self.repository_name, field_name="repository_name"))
        object.__setattr__(self, "branch_ref", _require_text(self.branch_ref, field_name="branch_ref"))
        if self.retry_budget < 1:
            raise ResetVerificationContractError("retry_budget must be at least 1")
        if self.retry_count < 0:
            raise ResetVerificationContractError("retry_count must be non-negative")
        if self.claim_timeout_seconds is not None and self.claim_timeout_seconds < 1:
            raise ResetVerificationContractError("claim_timeout_seconds must be at least 1 when provided")

    def branch_matches(self, branch_name: str) -> bool:
        normalized = branch_name.strip()
        if "*" in self.branch_ref or "?" in self.branch_ref:
            return fnmatch(normalized, self.branch_ref)
        return normalized == self.branch_ref

    def append_event(self, *, kind: str, message: str, timestamp: str | None = None) -> "ResetVerificationContract":
        return self.updated(
            event_log=self.event_log + (ResetEvent.create(kind=kind, message=message, timestamp=timestamp),)
        )

    def updated(self, **changes: Any) -> "ResetVerificationContract":
        payload = self.asdict()
        payload.update(changes)
        payload["updated_at"] = changes.get("updated_at", _utc_now())
        return self.from_dict(payload)

    def asdict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "linear_issue_id": self.linear_issue_id,
            "repository_owner": self.repository_owner,
            "repository_name": self.repository_name,
            "branch_ref": self.branch_ref,
            "retry_count": self.retry_count,
            "retry_budget": self.retry_budget,
            "harness_status": self.harness_status,
            "latest_claim": self.latest_claim.asdict() if self.latest_claim is not None else None,
            "latest_verdict": self.latest_verdict,
            "latest_reason": self.latest_reason,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_activity_at": self.last_activity_at,
            "last_repair_requested_at": self.last_repair_requested_at,
            "last_verified_at": self.last_verified_at,
            "claim_timeout_seconds": self.claim_timeout_seconds,
            "event_log": [asdict(event) for event in self.event_log],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ResetVerificationContract":
        latest_claim = payload.get("latest_claim")
        event_log = payload.get("event_log") or ()
        return cls(
            contract_id=str(payload["contract_id"]),
            linear_issue_id=str(payload["linear_issue_id"]),
            repository_owner=str(payload["repository_owner"]),
            repository_name=str(payload["repository_name"]),
            branch_ref=str(payload["branch_ref"]),
            retry_count=int(payload.get("retry_count", 0)),
            retry_budget=int(payload.get("retry_budget", 2)),
            harness_status=str(payload.get("harness_status") or "running"),
            latest_claim=(
                latest_claim
                if isinstance(latest_claim, ResetCompletionClaim)
                else ResetCompletionClaim.from_dict(latest_claim)
                if isinstance(latest_claim, dict)
                else None
            ),
            latest_verdict=str(payload["latest_verdict"]) if payload.get("latest_verdict") is not None else None,
            latest_reason=str(payload["latest_reason"]) if payload.get("latest_reason") is not None else None,
            created_at=str(payload.get("created_at") or _utc_now()),
            updated_at=str(payload.get("updated_at") or _utc_now()),
            last_activity_at=str(payload["last_activity_at"]) if payload.get("last_activity_at") is not None else None,
            last_repair_requested_at=(
                str(payload["last_repair_requested_at"])
                if payload.get("last_repair_requested_at") is not None
                else None
            ),
            last_verified_at=str(payload["last_verified_at"]) if payload.get("last_verified_at") is not None else None,
            claim_timeout_seconds=(
                int(payload["claim_timeout_seconds"])
                if payload.get("claim_timeout_seconds") is not None
                else None
            ),
            event_log=tuple(
                item if isinstance(item, ResetEvent) else ResetEvent(**item)
                for item in event_log
            ),
        )


__all__ = [
    "ResetCompletionClaim",
    "ResetEvent",
    "ResetVerificationContract",
    "ResetVerificationContractError",
]
