"""Deterministic scenario helpers for the reset verifier redesign."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from .contracts import ResetCompletionClaim, ResetVerificationContract
from .github_verifier import ResetGitHubVerifier
from .prompting import ResetDispatchPromptContext, build_reset_dispatch_prompt
from .proofs import ResetWorkerProofError, parse_worker_proof_output
from .service import ResetVerificationService
from .store import FileBackedResetStore


def _isoformat_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class _MutableClock:
    def __init__(self, current: datetime) -> None:
        self.current = current.astimezone(timezone.utc)

    def now(self) -> datetime:
        return self.current

    def advance(self, *, seconds: int) -> None:
        self.current = self.current + timedelta(seconds=seconds)


class _FakeLinearClient:
    def __init__(self) -> None:
        self.actions: list[tuple[str, str | None, str, str]] = []

    def update_issue(self, issue_id: str, *, state: str | None, harness_status: str, comment: str) -> None:
        self.actions.append((issue_id, state, harness_status, comment))


class _FakeOpenClawClient:
    def __init__(self) -> None:
        self.repairs: list[tuple[str, str, str | None]] = []

    def request_repair(self, issue_id: str, *, reason: str, contract_id: str | None = None) -> None:
        self.repairs.append((issue_id, reason, contract_id))


@dataclass(frozen=True)
class SimulatedGitHubState:
    branch_exists: bool = False
    commit_exists: bool = False
    pull_request_payload: dict[str, Any] | None = None


class _FakeGitHubClient:
    def __init__(self, state: SimulatedGitHubState) -> None:
        self.state = state

    def branch_exists(self, owner: str, repo: str, branch_name: str) -> bool:
        del owner, repo, branch_name
        return self.state.branch_exists

    def commit_exists(self, owner: str, repo: str, commit_sha: str) -> bool:
        del owner, repo, commit_sha
        return self.state.commit_exists

    def get_pull_request(self, owner: str, repo: str, pull_request_number: int) -> dict[str, Any] | None:
        del owner, repo, pull_request_number
        return self.state.pull_request_payload


@dataclass(frozen=True)
class SimulatedResetScenario:
    name: str
    contract_id: str
    linear_issue_id: str
    linear_issue_title: str
    repository_owner: str
    repository_name: str
    branch_name: str
    required_changed_path: str
    worker_output: str
    github_state: SimulatedGitHubState = field(default_factory=SimulatedGitHubState)
    base_branch: str = "main"
    retry_budget: int = 2
    claim_timeout_seconds: int | None = None
    tick_count: int = 0
    tick_advance_seconds: int = 1
    start_at: str = "2026-04-15T12:00:00Z"


@dataclass(frozen=True)
class SimulatedResetScenarioResult:
    prompt: str
    claim_status: int | None
    claim_verdict: str | None
    final_contract: dict[str, Any]
    linear_actions: list[tuple[str, str | None, str, str]]
    repair_requests: list[tuple[str, str, str | None]]
    tick_verdicts: tuple[str, ...]
    proof_error: str | None


def build_worker_proof_output(
    *,
    repository: str,
    branch: str,
    commit_sha: str,
    pull_request_url: str,
) -> str:
    return "\n".join(
        [
            f"Repository: {repository}",
            f"Branch: {branch}",
            f"Commit SHA: {commit_sha}",
            f"PR URL: {pull_request_url}",
        ]
    )


def run_simulated_reset_scenario(scenario: SimulatedResetScenario) -> SimulatedResetScenarioResult:
    prompt = build_reset_dispatch_prompt(
        ResetDispatchPromptContext(
            contract_id=scenario.contract_id,
            linear_issue_id=scenario.linear_issue_id,
            linear_issue_title=scenario.linear_issue_title,
            repository_owner=scenario.repository_owner,
            repository_name=scenario.repository_name,
            branch_name=scenario.branch_name,
            base_branch=scenario.base_branch,
            required_changed_path=scenario.required_changed_path,
        )
    )

    start_at = datetime.fromisoformat(scenario.start_at.replace("Z", "+00:00")).astimezone(timezone.utc)
    clock = _MutableClock(start_at)
    linear_client = _FakeLinearClient()
    openclaw_client = _FakeOpenClawClient()

    with tempfile.TemporaryDirectory() as temp_dir:
        service = ResetVerificationService(
            store=FileBackedResetStore(temp_dir),
            linear_client=linear_client,
            verifier=ResetGitHubVerifier(client=_FakeGitHubClient(scenario.github_state)),
            openclaw_client=openclaw_client,
            now_provider=clock.now,
            retry_cooldown_seconds=0,
            claim_timeout_seconds=float(scenario.claim_timeout_seconds or 900),
        )
        contract = ResetVerificationContract(
            contract_id=scenario.contract_id,
            linear_issue_id=scenario.linear_issue_id,
            repository_owner=scenario.repository_owner,
            repository_name=scenario.repository_name,
            branch_ref=scenario.branch_name,
            retry_budget=scenario.retry_budget,
            created_at=scenario.start_at,
            updated_at=scenario.start_at,
            last_activity_at=scenario.start_at,
            claim_timeout_seconds=scenario.claim_timeout_seconds,
        )
        service.register_contract(contract)

        claim_status: int | None = None
        claim_verdict: str | None = None
        proof_error: str | None = None
        try:
            proof = parse_worker_proof_output(scenario.worker_output)
        except ResetWorkerProofError as exc:
            proof_error = str(exc)
        else:
            claim_status = 200
            claim_result = service.submit_claim(
                scenario.contract_id,
                ResetCompletionClaim(
                    repository_owner=proof.repository_owner,
                    repository_name=proof.repository_name,
                    branch_name=proof.branch_name,
                    commit_sha=proof.commit_sha,
                    pull_request_number=proof.pull_request_number,
                    pull_request_url=proof.pull_request_url,
                    claimed_at=_isoformat_utc(clock.now()),
                ),
            )
            claim_verdict = str(claim_result["status"])

        tick_verdicts: list[str] = []
        for tick_index in range(scenario.tick_count):
            advance_seconds = scenario.tick_advance_seconds
            if (
                tick_index == 0
                and claim_status is None
                and scenario.claim_timeout_seconds is not None
            ):
                advance_seconds = max(advance_seconds, scenario.claim_timeout_seconds + 1)
            clock.advance(seconds=advance_seconds)
            tick_verdicts.extend(result.status for result in service.tick())

        final_contract = service.get_contract(scenario.contract_id).asdict()
        return SimulatedResetScenarioResult(
            prompt=prompt,
            claim_status=claim_status,
            claim_verdict=claim_verdict,
            final_contract=final_contract,
            linear_actions=list(linear_client.actions),
            repair_requests=list(openclaw_client.repairs),
            tick_verdicts=tuple(tick_verdicts),
            proof_error=proof_error,
        )


__all__ = [
    "SimulatedGitHubState",
    "SimulatedResetScenario",
    "SimulatedResetScenarioResult",
    "build_worker_proof_output",
    "run_simulated_reset_scenario",
]
