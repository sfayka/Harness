"""Reset-slice verification service orchestration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contracts import ResetCompletionClaim, ResetVerificationContract
from .github_verifier import ResetGitHubVerdict, ResetGitHubVerifier
from .linear_client import LinearClientError, LinearResetClient
from .openclaw_client import OpenClawRepairClient, OpenClawRepairClientError
from .store import (
    ResetContractAlreadyExistsError,
    ResetContractNotFoundError,
    ResetStore,
    build_reset_store,
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


def _isoformat_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


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
        store: ResetStore,
        linear_client: Any,
        verifier: ResetGitHubVerifier,
        openclaw_client: Any,
        now_provider: Any | None = None,
        retry_cooldown_seconds: float = 900.0,
        claim_timeout_seconds: float = 900.0,
    ) -> None:
        self.store = store
        self.linear_client = linear_client
        self.verifier = verifier
        self.openclaw_client = openclaw_client
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self.retry_cooldown_seconds = retry_cooldown_seconds
        self.claim_timeout_seconds = claim_timeout_seconds

    @classmethod
    def from_env(cls, *, root_dir: str | Path | None = None) -> "ResetVerificationService":
        cooldown = _coerce_float(os.environ.get("HARNESS_RESET_POLL_SECONDS"), default=900.0)
        claim_timeout = _coerce_float(os.environ.get("HARNESS_RESET_CLAIM_TIMEOUT_SECONDS"), default=900.0)
        return cls(
            store=build_reset_store(store_root=root_dir),
            linear_client=LinearResetClient(),
            verifier=ResetGitHubVerifier(),
            openclaw_client=OpenClawRepairClient(),
            now_provider=None,
            retry_cooldown_seconds=cooldown,
            claim_timeout_seconds=claim_timeout,
        )

    def register_contract(self, contract: ResetVerificationContract) -> ResetVerificationContract:
        activity_timestamp = contract.last_activity_at or contract.created_at
        created = self.store.create_contract(
            contract.updated(last_activity_at=activity_timestamp).append_event(
                kind="contract_registered",
                message="Harness verification contract registered.",
            )
        )
        return self._sync_linear_writeback(
            created,
            state="In Progress",
            harness_status="running",
            comment="Harness verification contract registered.",
        )

    def list_contracts(self) -> tuple[ResetVerificationContract, ...]:
        return self.store.list_contracts()

    def get_contract(self, contract_id: str) -> ResetVerificationContract:
        return self.store.get_contract(contract_id)

    def submit_claim(self, contract_id: str, claim: ResetCompletionClaim) -> dict[str, Any]:
        contract = self.store.get_contract(contract_id).updated(
            latest_claim=claim,
            harness_status="verifying",
            last_activity_at=claim.claimed_at,
        ).append_event(
            kind="completion_claim_received",
            message=f"Completion claim received for {claim.repository_owner}/{claim.repository_name}@{claim.branch_name}.",
            timestamp=claim.claimed_at,
        )
        return self._evaluate_and_persist(contract, claim=claim, allow_repair_dispatch=True)

    def tick(self) -> tuple[ResetTickResult, ...]:
        outcomes: list[ResetTickResult] = []
        for contract in self.store.list_contracts():
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
            if contract.latest_claim is None:
                timeout_reason = self._claim_timeout_reason(contract)
                if timeout_reason is None:
                    continue
                if contract.retry_count >= contract.retry_budget:
                    updated = self._mark_in_review(contract, timeout_reason)
                    outcomes.append(
                        ResetTickResult(
                            contract_id=updated.contract_id,
                            action="escalated",
                            status="needs_review",
                            reason=timeout_reason,
                        )
                    )
                    continue

                try:
                    updated = self._dispatch_repair(contract, timeout_reason)
                    outcome_status = "retryable_invalid_proof"
                    outcome_action = "repair_requested"
                    outcome_reason = timeout_reason
                except (OpenClawRepairClientError, ValueError) as error:
                    outcome_reason = self._repair_dispatch_failure_reason(timeout_reason, error)
                    updated = self._mark_in_review(contract, outcome_reason)
                    outcome_status = "needs_review"
                    outcome_action = "escalated"
                outcomes.append(
                    ResetTickResult(
                        contract_id=updated.contract_id,
                        action=outcome_action,
                        status=outcome_status,
                        reason=outcome_reason,
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

            try:
                updated = self._dispatch_repair(contract, verdict.reason)
                outcome_status = "retryable_invalid_proof"
                outcome_action = "repair_requested"
                outcome_reason = verdict.reason
            except (OpenClawRepairClientError, ValueError) as error:
                outcome_reason = self._repair_dispatch_failure_reason(verdict.reason, error)
                updated = self._mark_in_review(contract, outcome_reason)
                outcome_status = "needs_review"
                outcome_action = "escalated"
            outcomes.append(
                ResetTickResult(
                    contract_id=updated.contract_id,
                    action=outcome_action,
                    status=outcome_status,
                    reason=outcome_reason,
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

    def _now_iso(self) -> str:
        return _isoformat_utc(self.now_provider())

    def _claim_timeout_reason(self, contract: ResetVerificationContract) -> str | None:
        timeout_seconds = (
            float(contract.claim_timeout_seconds)
            if contract.claim_timeout_seconds is not None
            else self.claim_timeout_seconds
        )
        if timeout_seconds <= 0:
            return None
        last_activity = _parse_iso_timestamp(contract.last_activity_at or contract.created_at)
        if last_activity is None:
            return None
        elapsed = (self.now_provider() - last_activity).total_seconds()
        if elapsed < timeout_seconds:
            return None
        return "no completion claim arrived before the supervision timeout"

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
            try:
                updated = self._dispatch_repair(contract, verdict.reason)
            except (OpenClawRepairClientError, ValueError) as error:
                effective_reason = self._repair_dispatch_failure_reason(verdict.reason, error)
                updated = self._mark_in_review(contract, effective_reason)
                return {
                    "status": "needs_review",
                    "reason": effective_reason,
                    "contract": updated.asdict(),
                }
        else:
            timestamp = self._now_iso()
            updated = self.store.update_contract(
                contract.updated(
                    latest_verdict="retryable_invalid_proof",
                    latest_reason=verdict.reason,
                    harness_status="proof_invalid",
                    last_activity_at=timestamp,
                    updated_at=timestamp,
                ).append_event(kind="verification_failed", message=verdict.reason, timestamp=timestamp)
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
            last_activity_at=claim.claimed_at,
        ).append_event(kind="verified", message=verdict.reason, timestamp=claim.claimed_at)
        self.store.update_contract(updated)
        return self._sync_linear_writeback(
            contract=updated,
            state="Done",
            harness_status="verified",
            comment=verdict.reason,
        )

    def _dispatch_repair(self, contract: ResetVerificationContract, reason: str) -> ResetVerificationContract:
        next_retry_count = contract.retry_count + 1
        timestamp = self._now_iso()
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
            last_activity_at=timestamp,
            updated_at=timestamp,
        )
        updated = updated.updated(
            last_repair_requested_at=updated.updated_at,
            last_activity_at=updated.updated_at,
        ).append_event(
            kind="repair_requested",
            message=reason,
            timestamp=timestamp,
        )
        self.store.update_contract(updated)
        return self._sync_linear_writeback(
            state="In Progress",
            contract=updated,
            harness_status="retrying",
            comment=reason,
        )

    def _repair_dispatch_failure_reason(self, reason: str, error: ValueError) -> str:
        detail = str(error).strip() or "unknown repair dispatch failure"
        return f"{reason}; repair dispatch failed: {detail}"

    def _mark_in_review(self, contract: ResetVerificationContract, reason: str) -> ResetVerificationContract:
        timestamp = self._now_iso()
        updated = contract.updated(
            latest_verdict="needs_review",
            latest_reason=reason,
            harness_status="needs_review",
            last_activity_at=timestamp,
            updated_at=timestamp,
        ).append_event(kind="review_required", message=reason, timestamp=timestamp)
        self.store.update_contract(updated)
        return self._sync_linear_writeback(
            contract=updated,
            state="In Review",
            harness_status="needs_review",
            comment=reason,
        )

    def _sync_linear_writeback(
        self,
        contract: ResetVerificationContract,
        *,
        state: str | None,
        harness_status: str,
        comment: str,
    ) -> ResetVerificationContract:
        try:
            self.linear_client.update_issue(
                contract.linear_issue_id,
                state=state,
                harness_status=harness_status,
                comment=comment,
            )
        except LinearClientError as error:
            timestamp = self._now_iso()
            updated = contract.updated(
                last_activity_at=timestamp,
                updated_at=timestamp,
            ).append_event(
                kind="linear_writeback_failed",
                message=str(error),
                timestamp=timestamp,
            )
            return self.store.update_contract(updated)
        return contract

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
