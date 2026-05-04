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

    def test_synthetic_validation_runner_is_documented(self) -> None:
        validation = Path("docs/howto/test-and-validate.md").read_text(encoding="utf-8")

        self.assertTrue(Path("scripts/proofline_validate.py").exists())
        self.assertIn("python3 scripts/proofline_validate.py", validation)
        self.assertIn("python3 scripts/proofline_validate.py --list", validation)
        self.assertIn("python3 scripts/proofline_validate.py --coverage", validation)
        self.assertIn("does not run live Linear/GitHub mutation smoke", validation)

    def test_repair_dispatch_docs_match_symphony_setup_boundary(self) -> None:
        readme = Path("README.md").read_text(encoding="utf-8")
        runtime_contract = Path("docs/architecture/local-runtime-contract.md").read_text(
            encoding="utf-8"
        )
        guided_setup = Path("docs/architecture/guided-integration-setup.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("repair-dispatch`: requires a Symphony-compatible execution substrate", runtime_contract)
        self.assertIn("Symphony-compatible execution substrate", readme)
        self.assertIn("legacy ingress/executor bridge is compatibility wiring", readme)
        self.assertIn("repair-dispatch` requires the execution substrate", guided_setup)
        self.assertNotIn(
            "repair-dispatch`: requires a desktop-agent ingress/executor bridge",
            runtime_contract,
        )

    def test_github_cli_credential_fallback_is_documented(self) -> None:
        runtime_contract = Path("docs/architecture/local-runtime-contract.md").read_text(
            encoding="utf-8"
        )
        local_development = Path("docs/setup/local-development.md").read_text(encoding="utf-8")
        secrets = Path("docs/architecture/app-managed-secrets.md").read_text(encoding="utf-8")

        self.assertIn("authenticated `gh` CLI session", runtime_contract)
        self.assertIn("`GH_TOKEN` also satisfies setup status", runtime_contract)
        self.assertIn("gh auth token", local_development)
        self.assertIn("GH_TOKEN", local_development)
        self.assertIn("gh auth token", secrets)
        self.assertIn("GH_TOKEN", secrets)
        self.assertIn("only a local credential source", secrets)
