"""Reset-slice verification service orchestration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contracts import ResetCompletionClaim, ResetVerificationContract
from .github_verifier import ResetGitHubVerdict, ResetGitHubVerifier
from .linear_client import LinearResetClient
from .openclaw_client import OpenClawRepairClient
from .store import (
    FileBackedResetStore,
    ResetContractAlreadyExistsError,
    ResetContractNotFoundError,
)


def _coerce_float(value: str | None, *, default: float) -> float:
    try:
        return float(value) if value is not None else default
    except ValueError:
        return default


def _parse_iso_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


@dataclass(frozen=True)
class ResetTickResult:
    contract_id: str
    action: str
    status: str
    reason: str


class ResetVerificationService:
    """Owns reset-slice contract registration, verification, and supervision."""

    def __init__(
        self,
        *,
        store: FileBackedResetStore,
        linear_client: Any,
        verifier: ResetGitHubVerifier,
        openclaw_client: Any,
        now_provider: Any | None = None,
        retry_cooldown_seconds: float = 900.0,
    ) -> None:
        self.store = store
        self.linear_client = linear_client
        self.verifier = verifier
        self.openclaw_client = openclaw_client
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self.retry_cooldown_seconds = retry_cooldown_seconds

    @classmethod
    def from_env(cls, *, root_dir: str | Path | None = None) -> "ResetVerificationService":
        resolved_root = Path(root_dir or os.environ.get("HARNESS_STORE_ROOT") or ".harness-store")
        cooldown = _coerce_float(os.environ.get("HARNESS_RESET_POLL_SECONDS"), default=900.0)
        return cls(
            store=FileBackedResetStore(resolved_root),
            linear_client=LinearResetClient(),
            verifier=ResetGitHubVerifier(),
            openclaw_client=OpenClawRepairClient(),
            now_provider=None,
            retry_cooldown_seconds=cooldown,
        )

    def register_contract(self, contract: ResetVerificationContract) -> ResetVerificationContract:
        created = self.store.create_contract(
            contract.append_event(kind="contract_registered", message="Harness verification contract registered.")
        )
        self.linear_client.update_issue(
            created.linear_issue_id,
            state="In Progress",
            harness_status="running",
            comment="Harness verification contract registered.",
        )
        return created

    def list_contracts(self) -> tuple[ResetVerificationContract, ...]:
        return self.store.list_contracts()

    def get_contract(self, contract_id: str) -> ResetVerificationContract:
        return self.store.get_contract(contract_id)

    def submit_claim(self, contract_id: str, claim: ResetCompletionClaim) -> dict[str, Any]:
        contract = self.store.get_contract(contract_id).updated(
            latest_claim=claim,
            harness_status="verifying",
        ).append_event(
            kind="completion_claim_received",
            message=f"Completion claim received for {claim.repository_owner}/{claim.repository_name}@{claim.branch_name}.",
            timestamp=claim.claimed_at,
        )
        return self._evaluate_and_persist(contract, claim=claim, allow_repair_dispatch=True)

    def tick(self) -> tuple[ResetTickResult, ...]:
        outcomes: list[ResetTickResult] = []
        for contract in self.store.list_contracts():
            if contract.latest_claim is None:
                continue
            if contract.harness_status not in {"verifying", "retrying", "running"}:
                continue
            if self._within_retry_cooldown(contract):
                outcomes.append(
                    ResetTickResult(
                        contract_id=contract.contract_id,
                        action="cooldown_wait",
                        status="cooldown_wait",
                        reason="retry cooldown window is still active",
                    )
                )
                continue

            evaluation = self._evaluate_claim(contract, contract.latest_claim)
            verdict = evaluation["verdict"]
            if verdict.status == "verified_done":
                updated = self._mark_verified(contract, contract.latest_claim, verdict)
                outcomes.append(
                    ResetTickResult(
                        contract_id=updated.contract_id,
                        action="verified",
                        status="verified_done",
                        reason=verdict.reason,
                    )
                )
                continue

            if contract.retry_count >= contract.retry_budget:
                updated = self._mark_in_review(contract, verdict.reason)
                outcomes.append(
                    ResetTickResult(
                        contract_id=updated.contract_id,
                        action="escalated",
                        status="needs_review",
                        reason=verdict.reason,
                    )
                )
                continue

            updated = self._dispatch_repair(contract, verdict.reason)
            outcomes.append(
                ResetTickResult(
                    contract_id=updated.contract_id,
                    action="repair_requested",
                    status="retryable_invalid_proof",
                    reason=verdict.reason,
                )
            )
        return tuple(outcomes)

    def _within_retry_cooldown(self, contract: ResetVerificationContract) -> bool:
        if contract.harness_status != "retrying" or self.retry_cooldown_seconds <= 0:
            return False
        last_requested = _parse_iso_timestamp(contract.last_repair_requested_at)
        if last_requested is None:
            return False
        elapsed = (self.now_provider() - last_requested).total_seconds()
        return elapsed < self.retry_cooldown_seconds

    def _evaluate_claim(
        self, contract: ResetVerificationContract, claim: ResetCompletionClaim
    ) -> dict[str, Any]:
        verdict = self.verifier.verify(
            expected_owner=contract.repository_owner,
            expected_repo=contract.repository_name,
            expected_branch=contract.branch_ref,
            claimed_owner=claim.repository_owner,
            claimed_repo=claim.repository_name,
            branch_name=claim.branch_name,
            commit_sha=claim.commit_sha,
            pull_request_number=claim.pull_request_number,
            pull_request_url=claim.pull_request_url,
        )
        return {"verdict": verdict}

    def _evaluate_and_persist(
        self,
        contract: ResetVerificationContract,
        *,
        claim: ResetCompletionClaim,
        allow_repair_dispatch: bool,
    ) -> dict[str, Any]:
        evaluation = self._evaluate_claim(contract, claim)
        verdict = evaluation["verdict"]
        if verdict.status == "verified_done":
            updated = self._mark_verified(contract, claim, verdict)
            return {
                "status": "verified_done",
                "reason": verdict.reason,
                "contract": updated.asdict(),
                "details": verdict.details or {},
            }

        if contract.retry_count >= contract.retry_budget:
            updated = self._mark_in_review(contract, verdict.reason)
            return {
                "status": "needs_review",
                "reason": verdict.reason,
                "contract": updated.asdict(),
            }

        if allow_repair_dispatch:
            updated = self._dispatch_repair(contract, verdict.reason)
        else:
            updated = self.store.update_contract(
                contract.updated(
                    latest_verdict="retryable_invalid_proof",
                    latest_reason=verdict.reason,
                    harness_status="proof_invalid",
                ).append_event(kind="verification_failed", message=verdict.reason)
            )
        return {
            "status": "retryable_invalid_proof",
            "reason": verdict.reason,
            "contract": updated.asdict(),
        }

    def _mark_verified(
        self,
        contract: ResetVerificationContract,
        claim: ResetCompletionClaim,
        verdict: ResetGitHubVerdict,
    ) -> ResetVerificationContract:
        updated = contract.updated(
            latest_claim=claim,
            latest_verdict="verified_done",
            latest_reason=verdict.reason,
            harness_status="verified",
            last_verified_at=claim.claimed_at,
        ).append_event(kind="verified", message=verdict.reason, timestamp=claim.claimed_at)
        self.store.update_contract(updated)
        self.linear_client.update_issue(
            updated.linear_issue_id,
            state="Done",
            harness_status="verified",
            comment=verdict.reason,
        )
        return updated

    def _dispatch_repair(self, contract: ResetVerificationContract, reason: str) -> ResetVerificationContract:
        next_retry_count = contract.retry_count + 1
        self.openclaw_client.request_repair(
            contract.linear_issue_id,
            reason=reason,
            contract_id=contract.contract_id,
        )
        updated = contract.updated(
            retry_count=next_retry_count,
            latest_verdict="retryable_invalid_proof",
            latest_reason=reason,
            harness_status="retrying",
        )
        updated = updated.updated(last_repair_requested_at=updated.updated_at).append_event(
            kind="repair_requested",
            message=reason,
        )
        self.store.update_contract(updated)
        self.linear_client.update_issue(
            updated.linear_issue_id,
            state="In Progress",
            harness_status="retrying",
            comment=reason,
        )
        return updated

    def _mark_in_review(self, contract: ResetVerificationContract, reason: str) -> ResetVerificationContract:
        updated = contract.updated(
            latest_verdict="needs_review",
            latest_reason=reason,
            harness_status="needs_review",
        ).append_event(kind="review_required", message=reason)
        self.store.update_contract(updated)
        self.linear_client.update_issue(
            updated.linear_issue_id,
            state="In Review",
            harness_status="needs_review",
            comment=reason,
        )
        return updated

    def register_contract_http(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        try:
            contract = ResetVerificationContract.from_dict(payload)
            created = self.register_contract(contract)
        except (ResetContractAlreadyExistsError, ValueError) as error:
            return 400, {"error": str(error)}
        return 201, {"contract": created.asdict()}

    def list_contracts_http(self) -> tuple[int, dict[str, Any]]:
        return 200, {"contracts": [contract.asdict() for contract in self.list_contracts()]}

    def get_contract_http(self, contract_id: str) -> tuple[int, dict[str, Any]]:
        try:
            contract = self.get_contract(contract_id)
        except ResetContractNotFoundError as error:
            return 404, {"error": str(error)}
        return 200, {"contract": contract.asdict()}

    def submit_claim_http(self, contract_id: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        try:
            claim = ResetCompletionClaim.from_dict(payload)
            result = self.submit_claim(contract_id, claim)
        except ResetContractNotFoundError as error:
            return 404, {"error": str(error)}
        except ValueError as error:
            return 400, {"error": str(error)}
        return 200, result

    def tick_http(self) -> tuple[int, dict[str, Any]]:
        results = self.tick()
        return 200, {
            "results": [
                {
                    "contract_id": result.contract_id,
                    "action": result.action,
                    "status": result.status,
                    "reason": result.reason,
                }
                for result in results
            ]
        }


__all__ = ["ResetTickResult", "ResetVerificationService"]
