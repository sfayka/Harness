from __future__ import annotations

import unittest

from modules.reset_dryrun import run_reset_review_dry_run, run_reset_success_dry_run


class ResetDryRunTests(unittest.TestCase):
    def test_success_dry_run_recovers_to_verified_done(self) -> None:
        result = run_reset_success_dry_run(contract_id="reset-dryrun-success-test")

        self.assertEqual(result.register_status, 201)
        self.assertEqual(result.initial_claim_status, 200)
        self.assertEqual(result.initial_claim_verdict, "retryable_invalid_proof")
        self.assertEqual(result.repair_request_count, 1)
        self.assertEqual(result.final_claim_status, 200)
        self.assertEqual(result.final_claim_verdict, "verified_done")
        self.assertEqual(result.final_issue_state, "Done")
        self.assertEqual(result.final_harness_status, "verified")

    def test_review_dry_run_escalates_after_retry_budget(self) -> None:
        result = run_reset_review_dry_run(contract_id="reset-dryrun-review-test")

        self.assertEqual(result.register_status, 201)
        self.assertEqual(result.initial_claim_status, 200)
        self.assertEqual(result.initial_claim_verdict, "retryable_invalid_proof")
        self.assertEqual(result.repair_request_count, 2)
        self.assertEqual(result.tick_statuses, (200, 200))
        self.assertEqual(result.tick_verdicts, ("retryable_invalid_proof", "needs_review"))
        self.assertEqual(result.final_issue_state, "In Review")
        self.assertEqual(result.final_harness_status, "needs_review")


if __name__ == "__main__":
    unittest.main()
