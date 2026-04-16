from __future__ import annotations

import os
import unittest

from modules.reset_live_smoke import run_live_reset_smoke_suite


@unittest.skipUnless(
    os.getenv("HARNESS_RUN_LIVE_RESET_TESTS") == "1",
    "set HARNESS_RUN_LIVE_RESET_TESTS=1 to run live Linear/GitHub smoke tests",
)
class LiveResetSmokeTests(unittest.TestCase):
    def test_live_linear_and_github_smoke_suite(self) -> None:
        result = run_live_reset_smoke_suite()

        self.assertEqual(result.happy_path.claim_verdict, "verified_done")
        self.assertEqual(result.happy_path.final_harness_status, "verified")
        self.assertEqual(result.happy_path.final_linear_state, "Done")
        self.assertEqual(result.happy_path.repair_request_count, 0)

        self.assertEqual(result.missing_pull_request.claim_verdict, "retryable_invalid_proof")
        self.assertEqual(result.missing_pull_request.final_harness_status, "retrying")
        self.assertEqual(result.missing_pull_request.final_linear_state, "In Progress")
        self.assertGreaterEqual(result.missing_pull_request.repair_request_count, 1)

        self.assertEqual(result.wrong_sha_review.claim_verdict, "retryable_invalid_proof")
        self.assertEqual(result.wrong_sha_review.tick_verdicts, ("needs_review",))
        self.assertEqual(result.wrong_sha_review.final_harness_status, "needs_review")
        self.assertEqual(result.wrong_sha_review.final_linear_state, "In Review")
        self.assertGreaterEqual(result.wrong_sha_review.repair_request_count, 1)


if __name__ == "__main__":
    unittest.main()
