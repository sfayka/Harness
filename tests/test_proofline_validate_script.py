from __future__ import annotations

import unittest

from scripts.proofline_validate import build_plan


class ProoflineValidateScriptTests(unittest.TestCase):
    def test_default_plan_covers_backend_synthetic_and_frontend_without_live_mutation(self) -> None:
        steps = build_plan(include_frontend=True, include_coverage=False)
        names = [step.name for step in steps]
        rendered = [" ".join(step.command) for step in steps]

        self.assertIn("backend-unit-suite", names)
        self.assertIn("execution-substrate-event-stream", names)
        self.assertIn("execution-substrate-intent-consumer", names)
        self.assertIn("execution-substrate-handoff", names)
        self.assertIn("reset-success-dryrun", names)
        self.assertIn("reset-review-dryrun", names)
        self.assertIn("frontend-tests", names)
        self.assertIn("frontend-lint", names)
        self.assertIn("frontend-build", names)
        self.assertNotIn("HARNESS_RUN_LIVE_RESET_TESTS=1", "\n".join(rendered))
        self.assertNotIn("tests.test_reset_live_smoke", "\n".join(rendered))

    def test_coverage_plan_is_explicitly_opt_in(self) -> None:
        default_names = [step.name for step in build_plan(include_frontend=False, include_coverage=False)]
        coverage_names = [step.name for step in build_plan(include_frontend=False, include_coverage=True)]

        self.assertNotIn("backend-coverage-run", default_names)
        self.assertIn("backend-coverage-run", coverage_names)
        self.assertIn("backend-coverage-report", coverage_names)


if __name__ == "__main__":
    unittest.main()
