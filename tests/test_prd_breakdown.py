from __future__ import annotations

import unittest

from modules.connectors import translate_linear_submission_payload
from modules.prd_breakdown import (
    PRDBreakdownInputError,
    build_example_prd,
    generate_linear_work_breakdown,
    list_example_prds,
)


class PRDWorkBreakdownTests(unittest.TestCase):
    def test_lists_example_prds(self) -> None:
        self.assertIn("feature_platform", list_example_prds())
        self.assertIn("narrow_improvement", list_example_prds())

    def test_generates_coherent_breakdown_for_valid_prd(self) -> None:
        proposal = generate_linear_work_breakdown(build_example_prd("feature_platform"))

        self.assertEqual(proposal.proposal_id, "proposal-harness-prd")
        self.assertEqual(proposal.prd_summary["scope_count"], 3)
        self.assertEqual(proposal.initiative["issue"]["title"], "Harness verification launch work breakdown")
        self.assertEqual(len(proposal.work_items), 3)
        self.assertEqual(proposal.work_items[0]["title"] if "title" in proposal.work_items[0] else proposal.work_items[0]["issue"]["title"], "Linear ingress alignment")
        self.assertEqual(proposal.work_items[1]["dependency_hints"], ["linear-ingress"])
        self.assertEqual(proposal.work_items[2]["dependency_hints"], ["verification"])
        self.assertIn("prd-generated", proposal.work_items[0]["labels"])

    def test_narrower_prd_generates_smaller_work_set(self) -> None:
        proposal = generate_linear_work_breakdown(build_example_prd("narrow_improvement"))

        self.assertEqual(proposal.prd_summary["scope_count"], 1)
        self.assertEqual(len(proposal.work_items), 1)
        self.assertEqual(proposal.work_items[0]["issue"]["title"], "Clarification request visibility")
        self.assertEqual(proposal.work_items[0]["sequence"], 1)

    def test_rejects_underspecified_prd_input(self) -> None:
        invalid_prd = {
            "id": "bad-prd",
            "title": "Bad PRD",
            "product_goal": "Ship something",
            "target_user": "Engineers",
            "problem_statement": "",
            "scope": [],
            "constraints": [],
            "success_criteria": [],
        }

        with self.assertRaises(PRDBreakdownInputError):
            generate_linear_work_breakdown(invalid_prd)

    def test_generated_items_are_compatible_with_linear_ingress_adapter(self) -> None:
        proposal = generate_linear_work_breakdown(build_example_prd("feature_platform"))

        initiative_payload = translate_linear_submission_payload(proposal.initiative)
        child_payloads = [translate_linear_submission_payload(item) for item in proposal.work_items]

        self.assertEqual(initiative_payload["request"]["task_envelope"]["origin"]["source_system"], "linear")
        self.assertEqual(len(child_payloads), 3)
        self.assertEqual(child_payloads[0]["request"]["task_envelope"]["title"], "Linear ingress alignment")
        self.assertEqual(
            child_payloads[1]["request"]["external_facts"]["linear_facts"]["issue_id"],
            proposal.work_items[1]["issue"]["id"],
        )


if __name__ == "__main__":
    unittest.main()
