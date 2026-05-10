from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.validate_buildroom import validate_buildroom


REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO_ROOM = REPO_ROOT / "buildroom" / "examples" / "demo-room"


class BuildroomContractTests(unittest.TestCase):
    def test_demo_room_has_complete_ordered_contract_chain(self) -> None:
        result = validate_buildroom(DEMO_ROOM)

        self.assertTrue(result["valid"])
        self.assertEqual(result["job_id"], "demo-client-html-delivery")
        self.assertEqual(
            result["artifact_kinds"],
            [
                "research_packet",
                "idea_contract",
                "intent_review",
                "main_review",
                "product_plan",
                "build_plan",
                "coder_receipt",
                "qa_receipt",
                "verification_delta",
                "trust_report",
                "retention_review",
                "operator_summary",
            ],
        )
        self.assertEqual(result["trust_state"], "clean")
        self.assertEqual(result["retention_recommendation"], "keep")

    def test_demo_room_preserves_autobuild_guardrails(self) -> None:
        result = validate_buildroom(DEMO_ROOM)

        self.assertTrue(result["guardrails"]["dreamer_cannot_approve"])
        self.assertTrue(result["guardrails"]["main_approved_before_build"])
        self.assertTrue(result["guardrails"]["coder_paths_within_product_plan"])
        self.assertTrue(result["guardrails"]["qa_independent_from_coder"])
        self.assertTrue(result["guardrails"]["retention_recommendation_only"])
        self.assertFalse(result["live_mutations_enabled"])

    def test_rejects_coder_receipt_that_expands_outside_allowed_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            room = Path(tmp)
            for source in sorted(DEMO_ROOM.glob("*.json")):
                target = room / source.name
                target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

            coder_path = room / "07-coder-receipt.json"
            coder_receipt = json.loads(coder_path.read_text(encoding="utf-8"))
            coder_receipt["changed_paths"].append("modules/evaluation.py")
            coder_path.write_text(json.dumps(coder_receipt, indent=2) + "\n", encoding="utf-8")

            result = validate_buildroom(room)

        self.assertFalse(result["valid"])
        self.assertIn("coder_changed_path_outside_allowed_paths: modules/evaluation.py", result["errors"])


if __name__ == "__main__":
    unittest.main()
