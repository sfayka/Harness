from __future__ import annotations

import tempfile
import unittest

from modules.reset.contracts import ResetCompletionClaim, ResetVerificationContract
from modules.reset.service import ResetVerificationService
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
                ),
            )

            first_tick = service.tick()
            second_tick = service.tick()

            self.assertEqual(first_tick[0].status, "retryable_invalid_proof")
            self.assertEqual(second_tick[0].status, "needs_review")
            self.assertEqual(linear.actions[-1][1], "In Review")
            self.assertEqual(linear.actions[-1][2], "needs_review")

