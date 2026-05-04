from __future__ import annotations

import unittest
from pathlib import Path


class HostedDocsTests(unittest.TestCase):
    def test_readme_points_to_vercel_and_neon_as_the_default_hosted_story(self) -> None:
        readme = Path("README.md").read_text(encoding="utf-8")

        self.assertIn("Vercel Services", readme)
        self.assertIn("Neon", readme)
        self.assertIn("BLOB_READ_WRITE_TOKEN", readme)
        self.assertNotIn("Render + Supabase Deployment", readme)

    def test_vercel_neon_runbook_exists_and_render_supabase_runbook_is_removed(self) -> None:
        self.assertTrue(Path("docs/setup/vercel-neon.md").exists())
        self.assertFalse(Path("docs/setup/render-supabase.md").exists())

    def test_validation_plan_names_synthetic_and_live_linear_github_gates(self) -> None:
        readme = Path("README.md").read_text(encoding="utf-8")
        validation = Path("docs/howto/test-and-validate.md").read_text(encoding="utf-8")

        self.assertIn("docs/howto/test-and-validate.md", readme)
        self.assertIn("Validation Tiers", validation)
        self.assertIn("Real Linear/GitHub Validation Plan", validation)
        self.assertIn("HARNESS-DRYRUN", validation)
        self.assertIn("sfayka/HARNESS-DRYRUN", validation)
        self.assertIn("HARNESS_RUN_LIVE_RESET_TESTS=1", validation)
        self.assertIn("synthetic", validation.lower())

    def test_backend_coverage_command_is_documented(self) -> None:
        validation = Path("docs/howto/test-and-validate.md").read_text(encoding="utf-8")
        local_development = Path("docs/setup/local-development.md").read_text(encoding="utf-8")

        self.assertTrue(Path("requirements-dev.txt").exists())
        self.assertTrue(Path(".coveragerc").exists())
        self.assertIn("python3 -m coverage run -m unittest discover -s tests", validation)
        self.assertIn("python3 -m coverage report -m", validation)
        self.assertIn("requirements-dev.txt", local_development)
