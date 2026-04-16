from __future__ import annotations

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


class _FakeVerifier:
    def verify(self, **_: object):
        return type(
            "Verdict",
            (),
            {"status": "verified_done", "reason": "github proof verified", "details": None},
        )()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class OpenClawResetSpikeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.linear = _FakeLinearClient()
        self.openclaw = _FakeOpenClawClient()
        self.app = create_app(
            store=FileBackedHarnessStore(self.temp_dir.name),
            reset_service=ResetVerificationService(
                store=FileBackedResetStore(self.temp_dir.name),
                linear_client=self.linear,
                verifier=_FakeVerifier(),
                openclaw_client=self.openclaw,
            ),
        )
        self.port = _free_port()
        self.server = uvicorn.Server(
            uvicorn.Config(self.app, host="127.0.0.1", port=self.port, log_level="error")
        )
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        for _ in range(50):
            if getattr(self.server, "started", False):
                break
            time.sleep(0.05)
        self.client = OpenClawHarnessSpikeClient(f"http://127.0.0.1:{self.port}")

    def tearDown(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def test_reset_routes_work_through_openclaw_spike_client(self) -> None:
        status, payload = self.client.register_reset_contract(
            {
                "contract_id": "contract-1",
                "linear_issue_id": "KNO-999",
                "repository_owner": "sfayka",
                "repository_name": "Harness",
                "branch_ref": "codex/reset-verifier-v1",
            }
        )
        self.assertEqual(status, 201)
        self.assertEqual(payload["contract"]["contract_id"], "contract-1")

        claim_status, claim_payload = self.client.submit_reset_claim(
            "contract-1",
            {
                "repository_owner": "sfayka",
                "repository_name": "Harness",
                "branch_name": "codex/reset-verifier-v1",
                "commit_sha": "abc123",
                "pull_request_number": 42,
                "pull_request_url": "https://github.com/sfayka/Harness/pull/42",
            },
        )
        self.assertEqual(claim_status, 200)
        self.assertEqual(claim_payload["status"], "verified_done")

        listed_status, listed_payload = self.client.list_reset_contracts()
        self.assertEqual(listed_status, 200)
        self.assertEqual(len(listed_payload["contracts"]), 1)

        tick_status, tick_payload = self.client.tick_reset()
        self.assertEqual(tick_status, 200)
        self.assertEqual(tick_payload["results"], [])


if __name__ == "__main__":
    unittest.main()
