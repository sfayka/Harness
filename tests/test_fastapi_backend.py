from __future__ import annotations

import os
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.server import create_app
from modules.local_env import load_local_env_file, load_native_local_env
from modules.reset.linear_client import LinearClientError
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

    def test_native_loader_includes_openclaw_local_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            (repo_root / ".env.local").write_text("FIRST=one\nOPENCLAW_GATEWAY_PORT=1111\n", encoding="utf-8")
            (repo_root / "config" / "openclaw").mkdir(parents=True, exist_ok=True)
            (repo_root / "config" / "openclaw" / ".env.local").write_text(
                "OPENCLAW_CONFIG_PATH=/tmp/openclaw.local.json5\nOPENCLAW_GATEWAY_PORT=2222\n",
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                loaded = load_native_local_env(repo_root=repo_root)
                self.assertEqual(
                    loaded,
                    ("FIRST", "OPENCLAW_GATEWAY_PORT", "OPENCLAW_CONFIG_PATH"),
                )
                self.assertEqual(os.environ["FIRST"], "one")
                self.assertEqual(os.environ["OPENCLAW_GATEWAY_PORT"], "1111")
                self.assertEqual(os.environ["OPENCLAW_CONFIG_PATH"], "/tmp/openclaw.local.json5")


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

    def test_openapi_metadata_uses_proofline_product_name(self) -> None:
        response = self.client.get("/openapi.json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["info"]["title"], "Proofline API")

    def test_runtime_status_route_returns_app_shell_contract(self) -> None:
        with patch.dict(
            os.environ,
            {
                "HARNESS_RUNTIME_MODE": "local-app",
                "HARNESS_RUNTIME_BASE_URL": "http://127.0.0.1:8765",
                "HARNESS_RUNTIME_CONFIG_PATH": "/tmp/harness/config.json",
                "HARNESS_RUNTIME_DATA_DIR": "/tmp/harness",
                "HARNESS_RUNTIME_LOG_PATH": "/tmp/harness.log",
            },
            clear=False,
        ):
            client = TestClient(create_app(store=self.store, reset_service=self.reset_service))
            response = client.get("/runtime/status")

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["mode"], "local-app")
        self.assertEqual(payload["api_base_url"], "http://127.0.0.1:8765")
        self.assertEqual(payload["store_backend"], "file")
        self.assertEqual(payload["paths"]["config_path"], "/tmp/harness/config.json")
        self.assertNotIn("TOKEN", json.dumps(payload))

    def test_mounts_packaged_dashboard_assets_when_configured(self) -> None:
        dashboard_dir = Path(self.temp_dir.name) / "dashboard"
        (dashboard_dir / "tasks").mkdir(parents=True)
        (dashboard_dir / "index.html").write_text("<h1>Dashboard Home</h1>", encoding="utf-8")
        (dashboard_dir / "tasks" / "index.html").write_text("<h1>Tasks</h1>", encoding="utf-8")

        with patch.dict(os.environ, {"PROOFLINE_DASHBOARD_ASSETS_DIR": str(dashboard_dir)}, clear=False):
            client = TestClient(create_app(store=self.store, reset_service=self.reset_service))

        home = client.get("/dashboard/")
        tasks = client.get("/dashboard/tasks/")

        self.assertEqual(home.status_code, 200)
        self.assertIn("Dashboard Home", home.text)
        self.assertEqual(tasks.status_code, 200)
        self.assertIn("Tasks", tasks.text)

    def test_mounts_packaged_dashboard_assets_from_harness_fallback(self) -> None:
        dashboard_dir = Path(self.temp_dir.name) / "dashboard-fallback"
        dashboard_dir.mkdir(parents=True)
        (dashboard_dir / "index.html").write_text("<h1>Fallback Dashboard</h1>", encoding="utf-8")

        with patch.dict(os.environ, {"HARNESS_DASHBOARD_ASSETS_DIR": str(dashboard_dir)}, clear=False):
            client = TestClient(create_app(store=self.store, reset_service=self.reset_service))

        home = client.get("/dashboard/")

        self.assertEqual(home.status_code, 200)
        self.assertIn("Fallback Dashboard", home.text)

    def test_backend_stays_healthy_when_reset_startup_is_unavailable(self) -> None:
        with patch("backend.server.ResetVerificationService.from_env", side_effect=OSError("read-only file system")):
            client = TestClient(create_app(store=self.store))

        health = client.get("/health")
        reset_contracts = client.get("/reset/contracts")

        self.assertEqual(health.status_code, 200)
        self.assertEqual(reset_contracts.status_code, 503)
        self.assertEqual(reset_contracts.json()["status"], "unavailable")
        self.assertEqual(
            reset_contracts.json()["reason"],
            "Reset verifier startup failed. Check server logs and runtime configuration.",
        )
        self.assertNotIn("read-only file system", json.dumps(reset_contracts.json()))

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
                "pull_request_url": "https://github.com/sfayka/Harness/pull/42",
            },
        )
        self.assertEqual(claimed.status_code, 200)
        self.assertEqual(claimed.json()["status"], "verified_done")
        self.assertEqual(self.linear_actions[-1][1], "Done")

        ticked = self.client.post("/reset/tick")
        self.assertEqual(ticked.status_code, 200)
        self.assertEqual(ticked.json()["results"], [])

    def test_reset_claim_invalid_proof_returns_review_instead_of_bad_request_when_repair_dispatch_fails(self) -> None:
        class _FailingVerifier:
            def verify(inner_self, **_: object):
                return type(
                    "Verdict",
                    (),
                    {"status": "retryable_invalid_proof", "reason": "wrong sha", "details": None},
                )()

        class _FailingOpenClawClient:
            def request_repair(
                inner_self,
                issue_id: str,
                *,
                reason: str,
                contract_id: str | None = None,
            ) -> None:
                raise ValueError("OpenClaw repair callback failed: connection refused")

        reset_service = ResetVerificationService(
            store=FileBackedResetStore(self.temp_dir.name),
            linear_client=type(
                "_FakeLinearClient",
                (),
                {
                    "update_issue": lambda inner_self, issue_id, *, state, harness_status, comment: self.linear_actions.append(
                        (issue_id, state, harness_status, comment)
                    )
                },
            )(),
            verifier=_FailingVerifier(),
            openclaw_client=_FailingOpenClawClient(),
        )
        client = TestClient(create_app(store=self.store, reset_service=reset_service))

        created = client.post(
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

        claimed = client.post(
            "/reset/contracts/contract-1/claims",
            json={
                "repository_owner": "sfayka",
                "repository_name": "Harness",
                "branch_name": "codex/reset-verifier-v1",
                "commit_sha": "bad",
                "pull_request_number": 42,
                "pull_request_url": "https://github.com/sfayka/Harness/pull/42",
            },
        )

        self.assertEqual(claimed.status_code, 200)
        self.assertEqual(claimed.json()["status"], "needs_review")
        self.assertEqual(self.linear_actions[-1][1], "In Review")
        self.assertEqual(self.linear_actions[-1][2], "needs_review")

    def test_reset_claim_verified_done_still_returns_success_when_linear_writeback_fails(self) -> None:
        class _VerifiedVerifier:
            def verify(inner_self, **_: object):
                return type(
                    "Verdict",
                    (),
                    {"status": "verified_done", "reason": "github proof verified", "details": None},
                )()

        class _FailingLinearClient:
            def update_issue(
                inner_self,
                issue_id: str,
                *,
                state: str | None,
                harness_status: str,
                comment: str,
            ) -> None:
                raise LinearClientError("Linear issueUpdate did not succeed")

        reset_service = ResetVerificationService(
            store=FileBackedResetStore(self.temp_dir.name),
            linear_client=_FailingLinearClient(),
            verifier=_VerifiedVerifier(),
            openclaw_client=type(
                "_FakeOpenClawClient",
                (),
                {"request_repair": lambda inner_self, issue_id, *, reason, contract_id=None: None},
            )(),
        )
        client = TestClient(create_app(store=self.store, reset_service=reset_service))

        created = client.post(
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

        claimed = client.post(
            "/reset/contracts/contract-1/claims",
            json={
                "repository_owner": "sfayka",
                "repository_name": "Harness",
                "branch_name": "codex/reset-verifier-v1",
                "commit_sha": "abc123",
                "pull_request_number": 42,
                "pull_request_url": "https://github.com/sfayka/Harness/pull/42",
            },
        )

        self.assertEqual(claimed.status_code, 200)
        self.assertEqual(claimed.json()["status"], "verified_done")
        self.assertEqual(
            claimed.json()["contract"]["event_log"][-1]["kind"],
            "linear_writeback_failed",
        )
