from __future__ import annotations

from contextlib import contextmanager
import socket
import tempfile
import threading
import time
import unittest

import uvicorn

from backend.server import create_app
from modules.connectors.openclaw_harness_spike import OpenClawHarnessSpikeClient
from modules.reset.service import ResetVerificationService
from modules.reset.store import FileBackedResetStore
from modules.store import FileBackedHarnessStore


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


class _SequencedVerifier:
    def __init__(self, *statuses: tuple[str, str]) -> None:
        self._statuses = list(statuses)
        self.calls: list[dict[str, object]] = []

    def verify(self, **kwargs: object):
        self.calls.append(kwargs)
        status, reason = self._statuses.pop(0)
        return type("Verdict", (), {"status": status, "reason": reason, "details": None})()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextmanager
def _running_reset_app(
    *,
    verifier: _SequencedVerifier,
    retry_cooldown_seconds: float = 900.0,
):
    with tempfile.TemporaryDirectory() as temp_dir:
        linear = _FakeLinearClient()
        openclaw = _FakeOpenClawClient()
        app = create_app(
            store=FileBackedHarnessStore(temp_dir),
            reset_service=ResetVerificationService(
                store=FileBackedResetStore(temp_dir),
                linear_client=linear,
                verifier=verifier,
                openclaw_client=openclaw,
                retry_cooldown_seconds=retry_cooldown_seconds,
            ),
        )
        port = _free_port()
        server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
        )
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        try:
            for _ in range(50):
                if getattr(server, "started", False):
                    break
                time.sleep(0.05)
            client = OpenClawHarnessSpikeClient(f"http://127.0.0.1:{port}")
            yield client, linear, openclaw, verifier
        finally:
            server.should_exit = True
            thread.join(timeout=5)


class OpenClawResetEndToEndTests(unittest.TestCase):
    def _register_contract(self, client: OpenClawHarnessSpikeClient, *, contract_id: str) -> dict:
        status, payload = client.register_reset_contract(
            {
                "contract_id": contract_id,
                "linear_issue_id": "KNO-999",
                "repository_owner": "sfayka",
                "repository_name": "Harness",
                "branch_ref": "codex/reset-verifier-v1",
                "retry_budget": 2,
            }
        )
        self.assertEqual(status, 201)
        return payload["contract"]

    def test_invalid_claim_stays_visible_until_verified_follow_up_claim(self) -> None:
        verifier = _SequencedVerifier(
            ("retryable_invalid_proof", "commit sha does not exist in the expected repository"),
            ("verified_done", "github proof verified"),
        )

        with _running_reset_app(verifier=verifier) as (client, linear, openclaw, _):
            self._register_contract(client, contract_id="contract-recovery")

            first_claim_status, first_claim_payload = client.submit_reset_claim(
                "contract-recovery",
                {
                    "repository_owner": "sfayka",
                    "repository_name": "Harness",
                    "branch_name": "codex/reset-verifier-v1",
                    "commit_sha": "bad-sha",
                    "pull_request_number": 42,
                    "pull_request_url": "https://github.com/sfayka/Harness/pull/42",
                },
            )
            fetch_after_invalid_status, fetch_after_invalid_payload = client.get_reset_contract("contract-recovery")
            list_after_invalid_status, list_after_invalid_payload = client.list_reset_contracts()

            self.assertEqual(first_claim_status, 200)
            self.assertEqual(first_claim_payload["status"], "retryable_invalid_proof")
            self.assertEqual(fetch_after_invalid_status, 200)
            self.assertEqual(list_after_invalid_status, 200)
            self.assertEqual(len(list_after_invalid_payload["contracts"]), 1)
            invalid_contract = fetch_after_invalid_payload["contract"]
            self.assertEqual(invalid_contract["harness_status"], "retrying")
            self.assertEqual(invalid_contract["retry_count"], 1)
            self.assertEqual(invalid_contract["latest_verdict"], "retryable_invalid_proof")
            self.assertEqual(
                [event["kind"] for event in invalid_contract["event_log"]],
                ["contract_registered", "completion_claim_received", "repair_requested"],
            )
            self.assertEqual(
                openclaw.repairs,
                [("KNO-999", "commit sha does not exist in the expected repository", "contract-recovery")],
            )
            self.assertEqual(linear.actions[-1][:3], ("KNO-999", "In Progress", "retrying"))

            second_claim_status, second_claim_payload = client.submit_reset_claim(
                "contract-recovery",
                {
                    "repository_owner": "sfayka",
                    "repository_name": "Harness",
                    "branch_name": "codex/reset-verifier-v1",
                    "commit_sha": "good-sha",
                    "pull_request_number": 42,
                    "pull_request_url": "https://github.com/sfayka/Harness/pull/42",
                },
            )
            fetch_after_verified_status, fetch_after_verified_payload = client.get_reset_contract("contract-recovery")

            self.assertEqual(second_claim_status, 200)
            self.assertEqual(second_claim_payload["status"], "verified_done")
            self.assertEqual(fetch_after_verified_status, 200)
            verified_contract = fetch_after_verified_payload["contract"]
            self.assertEqual(verified_contract["harness_status"], "verified")
            self.assertEqual(verified_contract["retry_count"], 1)
            self.assertEqual(verified_contract["latest_verdict"], "verified_done")
            self.assertIsNotNone(verified_contract["last_verified_at"])
            self.assertEqual(
                [event["kind"] for event in verified_contract["event_log"]],
                [
                    "contract_registered",
                    "completion_claim_received",
                    "repair_requested",
                    "completion_claim_received",
                    "verified",
                ],
            )
            self.assertEqual(linear.actions[-1][:3], ("KNO-999", "Done", "verified"))
            self.assertEqual(len(openclaw.repairs), 1)
            self.assertEqual(len(verifier.calls), 2)

    def test_retry_budget_exhaustion_moves_contract_to_review_without_dropping_it(self) -> None:
        verifier = _SequencedVerifier(
            ("retryable_invalid_proof", "wrong sha"),
            ("retryable_invalid_proof", "still wrong"),
            ("retryable_invalid_proof", "still wrong"),
        )

        with _running_reset_app(
            verifier=verifier,
            retry_cooldown_seconds=0,
        ) as (client, linear, openclaw, _):
            self._register_contract(client, contract_id="contract-review")

            claim_status, claim_payload = client.submit_reset_claim(
                "contract-review",
                {
                    "repository_owner": "sfayka",
                    "repository_name": "Harness",
                    "branch_name": "codex/reset-verifier-v1",
                    "commit_sha": "bad-sha",
                    "pull_request_number": 42,
                    "pull_request_url": "https://github.com/sfayka/Harness/pull/42",
                },
            )
            first_tick_status, first_tick_payload = client.tick_reset()
            second_tick_status, second_tick_payload = client.tick_reset()
            third_tick_status, third_tick_payload = client.tick_reset()
            fetch_status, fetch_payload = client.get_reset_contract("contract-review")
            list_status, list_payload = client.list_reset_contracts()

            self.assertEqual(claim_status, 200)
            self.assertEqual(claim_payload["status"], "retryable_invalid_proof")
            self.assertEqual(first_tick_status, 200)
            self.assertEqual(second_tick_status, 200)
            self.assertEqual(third_tick_status, 200)
            self.assertEqual(first_tick_payload["results"][0]["status"], "retryable_invalid_proof")
            self.assertEqual(second_tick_payload["results"][0]["status"], "needs_review")
            self.assertEqual(third_tick_payload["results"], [])
            self.assertEqual(fetch_status, 200)
            self.assertEqual(list_status, 200)
            self.assertEqual(len(list_payload["contracts"]), 1)

            review_contract = fetch_payload["contract"]
            self.assertEqual(review_contract["harness_status"], "needs_review")
            self.assertEqual(review_contract["retry_count"], 2)
            self.assertEqual(review_contract["latest_verdict"], "needs_review")
            self.assertEqual(
                [event["kind"] for event in review_contract["event_log"]],
                [
                    "contract_registered",
                    "completion_claim_received",
                    "repair_requested",
                    "repair_requested",
                    "review_required",
                ],
            )
            self.assertEqual(
                openclaw.repairs,
                [
                    ("KNO-999", "wrong sha", "contract-review"),
                    ("KNO-999", "still wrong", "contract-review"),
                ],
            )
            self.assertEqual(linear.actions[-1][:3], ("KNO-999", "In Review", "needs_review"))


if __name__ == "__main__":
    unittest.main()
