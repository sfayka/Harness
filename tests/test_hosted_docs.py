from __future__ import annotations

import unittest
from pathlib import Path


class HostedDocsTests(unittest.TestCase):
    def test_readme_points_to_vercel_and_neon_as_the_default_hosted_story(self) -> None:
        readme = Path("README.md").read_text(encoding="utf-8")

        self.assertIn("Vercel Services", readme)
        self.assertIn("Neon", readme)
        self.assertNotIn("Render + Supabase Deployment", readme)

    def test_vercel_neon_runbook_exists_and_render_supabase_runbook_is_removed(self) -> None:
        self.assertTrue(Path("docs/setup/vercel-neon.md").exists())
        self.assertFalse(Path("docs/setup/render-supabase.md").exists())
