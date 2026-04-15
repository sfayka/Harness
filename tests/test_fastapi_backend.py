from __future__ import annotations

import os
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.server import create_app
from modules.local_env import load_local_env_file
from modules.reset.service import ResetVerificationService
from modules.reset.store import FileBackedResetStore
from modules.store import FileBackedHarnessStore
from tests.test_api import _manual_happy_path_overlay_payload


class LocalEnvLoaderTests(unittest.TestCase):
    def test_loads_key_value_pairs_without_overwriting_existing_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env.local"
            env_path.write_text(
                "# local-only config\nFIRST=one\nSECOND='two words'\nTHIRD=three\n",
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"SECOND": "existing"}, clear=False):
                loaded = load_local_env_file(env_path)
                self.assertEqual(loaded, ("FIRST", "THIRD"))
                self.assertEqual(os.environ["FIRST"], "one")
                self.assertEqual(os.environ["SECOND"], "existing")
                self.assertEqual(os.environ["THIRD"], "three")


class FastApiBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = FileBackedHarnessStore(self.temp_dir.name)
        self.linear_actions: list[tuple[str, str | None, str, str]] = []
        self.repair_requests: list[tuple[str, str, str | None]] = []

        class _FakeLinearClient:
            def __init__(inner_self, actions: list[tuple[str, str | None, str, str]]) -> None:
                inner_self.actions = actions

            def update_issue(
                inner_self,
                issue_id: str,
                *,
                state: str | None,
                harness_status: str,
                comment: str,
            ) -> None:
                inner_self.actions.append((issue_id, state, harness_status, comment))

        class _FakeOpenClawClient:
            def __init__(inner_self, repairs: list[tuple[str, str, str | None]]) -> None:
                inner_self.repairs = repairs

            def request_repair(
                inner_self,
                issue_id: str,
                *,
                reason: str,
                contract_id: str | None = None,
            ) -> None:
                inner_self.repairs.append((issue_id, reason, contract_id))

        class _FakeVerifier:
            def verify(inner_self, **_: object):
                return type(
                    "Verdict",
                    (),
                    {"status": "verified_done", "reason": "github proof verified", "details": None},
                )()

        self.reset_service = ResetVerificationService(
            store=FileBackedResetStore(self.temp_dir.name),
            linear_client=_FakeLinearClient(self.linear_actions),
            verifier=_FakeVerifier(),
            openclaw_client=_FakeOpenClawClient(self.repair_requests),
        )
        self.client = TestClient(create_app(store=self.store, reset_service=self.reset_service))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_health_route_returns_canonical_health_payload(self) -> None:
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertIn("store_backend", response.json())

    def test_submit_and_read_model_round_trip_through_fastapi_adapter(self) -> None:
        created = self.client.post(
            "/tasks",
            json={"request": {"task_envelope": deepcopy(_manual_happy_path_overlay_payload()["request"]["task_envelope"])}},
        )
        self.assertEqual(created.status_code, 200)

        task_id = created.json()["task_envelope"]["id"]

        read_model = self.client.get(f"/tasks/{task_id}/read-model")
        self.assertEqual(read_model.status_code, 200)
        self.assertEqual(read_model.json()["task"]["task_id"], task_id)

    def test_reset_contract_registration_and_claim_routes_round_trip(self) -> None:
        created = self.client.post(
            "/reset/contracts",
            json={
                "contract_id": "contract-1",
                "linear_issue_id": "KNO-999",
                "repository_owner": "sfayka",
                "repository_name": "Harness",
                "branch_ref": "codex/reset-verifier-v1",
            },
        )
        self.assertEqual(created.status_code, 201)

        listed = self.client.get("/reset/contracts")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()["contracts"]), 1)

        claimed = self.client.post(
            "/reset/contracts/contract-1/claims",
            json={
                "repository_owner": "sfayka",
                "repository_name": "Harness",
                "branch_name": "codex/reset-verifier-v1",
                "commit_sha": "abc123",
                "pull_request_number": 42,
            },
        )
        self.assertEqual(claimed.status_code, 200)
        self.assertEqual(claimed.json()["status"], "verified_done")
        self.assertEqual(self.linear_actions[-1][1], "Done")

        ticked = self.client.post("/reset/tick")
        self.assertEqual(ticked.status_code, 200)
        self.assertEqual(ticked.json()["results"], [])
