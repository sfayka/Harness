from __future__ import annotations

import unittest

from modules.reset.prompting import ResetDispatchPromptContext, build_reset_dispatch_prompt


class ResetPromptingTests(unittest.TestCase):
    def test_happy_path_prompt_demands_real_github_proof(self) -> None:
        prompt = build_reset_dispatch_prompt(
            ResetDispatchPromptContext(
                contract_id="contract-1",
                linear_issue_id="KNO-999",
                linear_issue_title="Dryrun happy path",
                repository_owner="sfayka",
                repository_name="HARNESS-DRYRUN",
                branch_name="codex/kno-999-happy-path",
                base_branch="main",
                required_changed_path="proofs/kno-999.md",
            )
        )

        self.assertIn("KNO-999", prompt)
        self.assertIn("sfayka/HARNESS-DRYRUN", prompt)
        self.assertIn("codex/kno-999-happy-path", prompt)
        self.assertIn("proofs/kno-999.md", prompt)
        self.assertIn("PR URL:", prompt)
        self.assertIn("real repository, branch, commit SHA, and PR URL", prompt)
