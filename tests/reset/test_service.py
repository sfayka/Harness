from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from modules.reset.contracts import ResetCompletionClaim, ResetVerificationContract
from modules.reset.service import ResetVerificationService
from modules.reset.store import PostgresResetStore
from modules.reset.store import FileBackedResetStore


class FakeLinearClient:
    def __init__(self) -> None:
        self.actions = []

    def update_issue(self, issue_id: str, *, state: str | None, harness_status: str, comment: str) -> None:
        self.actions.append((issue_id, state, harness_status, comment))


class FakeOpenClawClient:
    def __init__(self) -> None:
        self.repairs = []

    def request_repair(self, issue_id: str, *, reason: str, contract_id: str | None = None) -> None:
        self.repairs.append((issue_id, reason, contract_id))


class FakeVerifier:
    def __init__(self, *statuses: tuple[str, str]) -> None:
        self.statuses = list(statuses)

    def verify(self, **_: object):
        status, reason = self.statuses.pop(0)
        return type("Verdict", (), {"status": status, "reason": reason, "details": None})()


class ResetVerificationServiceTests(unittest.TestCase):
    def test_from_env_uses_postgres_reset_store_in_vercel_runtime_when_database_url_is_available(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "VERCEL_URL": "harness-preview.vercel.app",
                "POSTGRES_URL": "postgresql://env-vercel",
            },
            clear=True,
        ):
            service = ResetVerificationService.from_env()

        self.assertIsInstance(service.store, PostgresResetStore)
        self.assertEqual(service.store.database_url, "postgresql://env-vercel")

    def test_from_env_prefers_explicit_reset_store_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(
                "os.environ",
                {
                    "HARNESS_RESET_STORE_ROOT": temp_dir,
                    "HARNESS_STORE_ROOT": "ignored-shared-root",
                },
                clear=False,
            ):
                service = ResetVerificationService.from_env()

            self.assertEqual(service.store.root_dir, Path(temp_dir))

    def test_from_env_uses_tmp_root_in_vercel_runtime_without_explicit_override(self) -> None:
        with patch.dict("os.environ", {"VERCEL_URL": "harness-umber.vercel.app"}, clear=True):
            service = ResetVerificationService.from_env()

        self.assertEqual(service.store.root_dir, Path("/tmp/harness-reset"))

    def test_invalid_proof_requests_repair_and_keeps_issue_in_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileBackedResetStore(temp_dir)
            linear = FakeLinearClient()
            openclaw = FakeOpenClawClient()
            service = ResetVerificationService(
                store=store,
                linear_client=linear,
                verifier=FakeVerifier(("retryable_invalid_proof", "wrong sha")),
                openclaw_client=openclaw,
            )

            contract = ResetVerificationContract(
                contract_id="contract-1",
                linear_issue_id="KNO-999",
                repository_owner="sfayka",
                repository_name="Harness",
                branch_ref="codex/reset-verifier-v1",
            )
            service.register_contract(contract)

            result = service.submit_claim(
                "contract-1",
                ResetCompletionClaim(
                    repository_owner="sfayka",
                    repository_name="Harness",
                    branch_name="codex/reset-verifier-v1",
                    commit_sha="bad",
                    pull_request_number=42,
                    pull_request_url="https://github.com/sfayka/Harness/pull/42",
                ),
            )

            self.assertEqual(result["status"], "retryable_invalid_proof")
            self.assertEqual(openclaw.repairs[0][0], "KNO-999")
            self.assertEqual(linear.actions[-1][1], "In Progress")
            self.assertEqual(linear.actions[-1][2], "retrying")

    def test_verified_claim_moves_issue_to_done(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileBackedResetStore(temp_dir)
            linear = FakeLinearClient()
            service = ResetVerificationService(
                store=store,
                linear_client=linear,
                verifier=FakeVerifier(("verified_done", "github proof verified")),
                openclaw_client=FakeOpenClawClient(),
            )
            contract = ResetVerificationContract(
                contract_id="contract-1",
                linear_issue_id="KNO-999",
                repository_owner="sfayka",
                repository_name="Harness",
                branch_ref="codex/reset-verifier-v1",
            )
            service.register_contract(contract)

            result = service.submit_claim(
                "contract-1",
                ResetCompletionClaim(
                    repository_owner="sfayka",
                    repository_name="Harness",
                    branch_name="codex/reset-verifier-v1",
                    commit_sha="abc123",
                    pull_request_number=42,
                    pull_request_url="https://github.com/sfayka/Harness/pull/42",
                ),
            )

            self.assertEqual(result["status"], "verified_done")
            self.assertEqual(linear.actions[-1][1], "Done")
            self.assertEqual(linear.actions[-1][2], "verified")

    def test_tick_escalates_to_review_after_retry_budget_is_spent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileBackedResetStore(temp_dir)
            linear = FakeLinearClient()
            openclaw = FakeOpenClawClient()
            service = ResetVerificationService(
                store=store,
                linear_client=linear,
                verifier=FakeVerifier(
                    ("retryable_invalid_proof", "wrong sha"),
                    ("retryable_invalid_proof", "still wrong"),
                    ("retryable_invalid_proof", "still wrong"),
                ),
                openclaw_client=openclaw,
                retry_cooldown_seconds=0,
            )
            contract = ResetVerificationContract(
                contract_id="contract-1",
                linear_issue_id="KNO-999",
                repository_owner="sfayka",
                repository_name="Harness",
                branch_ref="codex/reset-verifier-v1",
            )
            service.register_contract(contract)
            service.submit_claim(
                "contract-1",
                ResetCompletionClaim(
                    repository_owner="sfayka",
                    repository_name="Harness",
                    branch_name="codex/reset-verifier-v1",
                    commit_sha="bad",
                    pull_request_number=42,
                    pull_request_url="https://github.com/sfayka/Harness/pull/42",
                ),
            )

            first_tick = service.tick()
            second_tick = service.tick()

            self.assertEqual(first_tick[0].status, "retryable_invalid_proof")
            self.assertEqual(second_tick[0].status, "needs_review")
            self.assertEqual(linear.actions[-1][1], "In Review")
            self.assertEqual(linear.actions[-1][2], "needs_review")

    def test_tick_waits_for_retry_cooldown_before_dispatching_again(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileBackedResetStore(temp_dir)
            linear = FakeLinearClient()
            openclaw = FakeOpenClawClient()
            requested_at = datetime(2026, 4, 15, 12, 0, tzinfo=timezone.utc)
            service = ResetVerificationService(
                store=store,
                linear_client=linear,
                verifier=FakeVerifier(("retryable_invalid_proof", "still wrong")),
                openclaw_client=openclaw,
                now_provider=lambda: requested_at + timedelta(seconds=60),
                retry_cooldown_seconds=300,
            )
            contract = ResetVerificationContract(
                contract_id="contract-1",
                linear_issue_id="KNO-999",
                repository_owner="sfayka",
                repository_name="Harness",
                branch_ref="codex/reset-verifier-v1",
                harness_status="retrying",
                latest_claim=ResetCompletionClaim(
                    repository_owner="sfayka",
                    repository_name="Harness",
                    branch_name="codex/reset-verifier-v1",
                    commit_sha="bad",
                    pull_request_number=42,
                    pull_request_url="https://github.com/sfayka/Harness/pull/42",
                ),
                retry_count=1,
                last_repair_requested_at=requested_at.isoformat().replace("+00:00", "Z"),
            )
            store.create_contract(contract)

            tick_results = service.tick()

            self.assertEqual(len(tick_results), 1)
            self.assertEqual(tick_results[0].status, "cooldown_wait")
            self.assertEqual(openclaw.repairs, [])
            self.assertEqual(linear.actions, [])

    def test_tick_requests_repair_when_no_claim_arrives_before_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileBackedResetStore(temp_dir)
            linear = FakeLinearClient()
            openclaw = FakeOpenClawClient()
            service = ResetVerificationService(
                store=store,
                linear_client=linear,
                verifier=FakeVerifier(("retryable_invalid_proof", "unused")),
                openclaw_client=openclaw,
                now_provider=lambda: datetime(2026, 4, 15, 12, 5, tzinfo=timezone.utc),
                retry_cooldown_seconds=0,
                claim_timeout_seconds=60,
            )
            contract = ResetVerificationContract(
                contract_id="contract-1",
                linear_issue_id="KNO-999",
                repository_owner="sfayka",
                repository_name="Harness",
                branch_ref="codex/reset-verifier-v1",
                created_at="2026-04-15T12:00:00Z",
                updated_at="2026-04-15T12:00:00Z",
                last_activity_at="2026-04-15T12:00:00Z",
            )
            service.register_contract(contract)

            tick_results = service.tick()
            updated = service.get_contract("contract-1")

            self.assertEqual(len(tick_results), 1)
            self.assertEqual(tick_results[0].status, "retryable_invalid_proof")
            self.assertEqual(updated.harness_status, "retrying")
            self.assertEqual(updated.retry_count, 1)
            self.assertEqual(
                [event.kind for event in updated.event_log][-1],
                "repair_requested",
            )
            self.assertEqual(openclaw.repairs[0][0], "KNO-999")
            self.assertIn("no completion claim", openclaw.repairs[0][1])
            self.assertEqual(linear.actions[-1][1], "In Progress")
            self.assertEqual(linear.actions[-1][2], "retrying")

    def test_tick_escalates_to_review_when_claim_timeout_retries_are_spent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = FileBackedResetStore(temp_dir)
            linear = FakeLinearClient()
            openclaw = FakeOpenClawClient()
            service = ResetVerificationService(
                store=store,
                linear_client=linear,
                verifier=FakeVerifier(("retryable_invalid_proof", "unused")),
                openclaw_client=openclaw,
                now_provider=lambda: datetime(2026, 4, 15, 12, 5, tzinfo=timezone.utc),
                retry_cooldown_seconds=0,
                claim_timeout_seconds=60,
            )
            contract = ResetVerificationContract(
                contract_id="contract-1",
                linear_issue_id="KNO-999",
                repository_owner="sfayka",
                repository_name="Harness",
                branch_ref="codex/reset-verifier-v1",
                retry_count=2,
                retry_budget=2,
                harness_status="retrying",
                created_at="2026-04-15T12:00:00Z",
                updated_at="2026-04-15T12:00:00Z",
                last_activity_at="2026-04-15T12:00:00Z",
                last_repair_requested_at="2026-04-15T12:01:00Z",
            )
            store.create_contract(contract)

            tick_results = service.tick()
            updated = service.get_contract("contract-1")

            self.assertEqual(len(tick_results), 1)
            self.assertEqual(tick_results[0].status, "needs_review")
            self.assertEqual(updated.harness_status, "needs_review")
            self.assertEqual(updated.latest_verdict, "needs_review")
            self.assertEqual(openclaw.repairs, [])
            self.assertEqual(linear.actions[-1][1], "In Review")
            self.assertEqual(linear.actions[-1][2], "needs_review")
