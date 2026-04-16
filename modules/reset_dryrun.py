"""Deterministic local dry runs for the reset verifier slice."""

from __future__ import annotations

import argparse
import socket
import tempfile
import threading
import time
from dataclasses import dataclass

import uvicorn

from backend.server import create_app
from modules.connectors.openclaw_harness_spike import OpenClawHarnessSpikeClient
from modules.reset.service import ResetVerificationService
from modules.reset.store import FileBackedResetStore
from modules.store import FileBackedHarnessStore


@dataclass(frozen=True)
class ResetDryRunResult:
    contract_id: str
    register_status: int
    initial_claim_status: int
    initial_claim_verdict: str | None
    repair_request_count: int
    final_claim_status: int | None
    final_claim_verdict: str | None
    tick_statuses: tuple[int, ...]
    tick_verdicts: tuple[str, ...]
    final_issue_state: str | None
    final_harness_status: str | None


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


class _ShaDrivenVerifier:
    def verify(
        self,
        *,
        commit_sha: str,
        pull_request_number: int | None,
        pull_request_url: str | None = None,
        **_: object,
    ):
        if pull_request_number is None and not pull_request_url:
            return type(
                "Verdict",
                (),
                {"status": "retryable_invalid_proof", "reason": "pull request reference missing", "details": None},
            )()
        if commit_sha.startswith("bad"):
            return type(
                "Verdict",
                (),
                {
                    "status": "retryable_invalid_proof",
                    "reason": "commit sha does not exist in the expected repository",
                    "details": None,
                },
            )()
        return type(
            "Verdict",
            (),
            {"status": "verified_done", "reason": "github proof verified", "details": None},
        )()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_reset_server(temp_dir: str, *, retry_cooldown_seconds: float = 900.0):
    linear = _FakeLinearClient()
    openclaw = _FakeOpenClawClient()
    app = create_app(
        store=FileBackedHarnessStore(temp_dir),
        reset_service=ResetVerificationService(
            store=FileBackedResetStore(temp_dir),
            linear_client=linear,
            verifier=_ShaDrivenVerifier(),
            openclaw_client=openclaw,
            retry_cooldown_seconds=retry_cooldown_seconds,
        ),
    )
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(50):
        if getattr(server, "started", False):
            break
        time.sleep(0.05)
    return server, thread, port, linear, openclaw


def run_reset_success_dry_run(*, contract_id: str = "reset-dryrun-success-1") -> ResetDryRunResult:
    with tempfile.TemporaryDirectory() as temp_dir:
        server, thread, port, linear, openclaw = _start_reset_server(temp_dir)
        try:
            client = OpenClawHarnessSpikeClient(f"http://127.0.0.1:{port}")
            register_status, _ = client.register_reset_contract(
                {
                    "contract_id": contract_id,
                    "linear_issue_id": "KNO-RESET-DRYRUN-SUCCESS",
                    "repository_owner": "sfayka",
                    "repository_name": "Harness",
                    "branch_ref": "codex/reset-verifier-v1",
                }
            )
            initial_claim_status, initial_claim_payload = client.submit_reset_claim(
                contract_id,
                {
                    "repository_owner": "sfayka",
                    "repository_name": "Harness",
                    "branch_name": "codex/reset-verifier-v1",
                    "commit_sha": "bad-sha",
                    "pull_request_number": 42,
                },
            )
            final_claim_status, final_claim_payload = client.submit_reset_claim(
                contract_id,
                {
                    "repository_owner": "sfayka",
                    "repository_name": "Harness",
                    "branch_name": "codex/reset-verifier-v1",
                    "commit_sha": "good-sha",
                    "pull_request_number": 42,
                },
            )
            return ResetDryRunResult(
                contract_id=contract_id,
                register_status=register_status,
                initial_claim_status=initial_claim_status,
                initial_claim_verdict=initial_claim_payload.get("status"),
                repair_request_count=len(openclaw.repairs),
                final_claim_status=final_claim_status,
                final_claim_verdict=final_claim_payload.get("status"),
                tick_statuses=(),
                tick_verdicts=(),
                final_issue_state=linear.actions[-1][1] if linear.actions else None,
                final_harness_status=linear.actions[-1][2] if linear.actions else None,
            )
        finally:
            server.should_exit = True
            thread.join(timeout=5)


def run_reset_review_dry_run(*, contract_id: str = "reset-dryrun-review-1") -> ResetDryRunResult:
    with tempfile.TemporaryDirectory() as temp_dir:
        server, thread, port, linear, openclaw = _start_reset_server(
            temp_dir,
            retry_cooldown_seconds=0,
        )
        try:
            client = OpenClawHarnessSpikeClient(f"http://127.0.0.1:{port}")
            register_status, _ = client.register_reset_contract(
                {
                    "contract_id": contract_id,
                    "linear_issue_id": "KNO-RESET-DRYRUN-REVIEW",
                    "repository_owner": "sfayka",
                    "repository_name": "Harness",
                    "branch_ref": "codex/reset-verifier-v1",
                }
            )
            initial_claim_status, initial_claim_payload = client.submit_reset_claim(
                contract_id,
                {
                    "repository_owner": "sfayka",
                    "repository_name": "Harness",
                    "branch_name": "codex/reset-verifier-v1",
                    "commit_sha": "bad-sha",
                    "pull_request_number": 42,
                },
            )
            tick_statuses: list[int] = []
            tick_verdicts: list[str] = []
            for _ in range(2):
                tick_status, tick_payload = client.tick_reset()
                tick_statuses.append(tick_status)
                results = tick_payload.get("results") or []
                tick_verdicts.append(results[0]["status"] if results else "none")

            return ResetDryRunResult(
                contract_id=contract_id,
                register_status=register_status,
                initial_claim_status=initial_claim_status,
                initial_claim_verdict=initial_claim_payload.get("status"),
                repair_request_count=len(openclaw.repairs),
                final_claim_status=None,
                final_claim_verdict=None,
                tick_statuses=tuple(tick_statuses),
                tick_verdicts=tuple(tick_verdicts),
                final_issue_state=linear.actions[-1][1] if linear.actions else None,
                final_harness_status=linear.actions[-1][2] if linear.actions else None,
            )
        finally:
            server.should_exit = True
            thread.join(timeout=5)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run deterministic reset verifier dry runs.")
    parser.add_argument("scenario", choices=("success", "review"))
    args = parser.parse_args()

    if args.scenario == "success":
        print(run_reset_success_dry_run())
        return
    print(run_reset_review_dry_run())


if __name__ == "__main__":
    main()
