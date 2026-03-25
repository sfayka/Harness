from __future__ import annotations

import tempfile
import unittest

from modules.api import HarnessApiService
from modules.prd_breakdown import build_example_prd, generate_linear_work_breakdown
from modules.prd_ingestion import (
    WorkItemReviewDecision,
    approve_all_items,
    ingest_reviewed_work_items,
    prepare_reviewable_work_items,
)
from modules.store import FileBackedHarnessStore


class PRDBulkIngestionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.service = HarnessApiService(store=FileBackedHarnessStore(self.temp_dir.name))
        self.proposal = generate_linear_work_breakdown(build_example_prd("feature_platform"))
        self.reviewable_set = prepare_reviewable_work_items(self.proposal)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_prepare_reviewable_work_items_includes_initiative_and_children(self) -> None:
        self.assertEqual(self.reviewable_set.proposal_id, self.proposal.proposal_id)
        self.assertEqual(len(self.reviewable_set.items), 4)
        self.assertEqual(self.reviewable_set.items[0].item_type, "initiative")
        self.assertEqual(self.reviewable_set.items[1].item_type, "work_item")

    def test_fully_approved_set_ingests_all_items(self) -> None:
        result = ingest_reviewed_work_items(
            self.reviewable_set,
            approve_all_items(self.reviewable_set, review_notes="Approved for ingestion."),
            service=self.service,
        )

        self.assertEqual(result.total_items, 4)
        self.assertEqual(result.approved_items, 4)
        self.assertEqual(result.ingested_items, 4)
        for item_result in result.item_results:
            self.assertTrue(item_result.ingested)
            self.assertFalse(item_result.invalid_input)
            self.assertFalse(item_result.duplicate_task_id)
            status, _ = self.service.get_task(item_result.task_id)
            self.assertEqual(status, 200)

    def test_partially_approved_set_only_ingests_approved_items(self) -> None:
        decisions = (
            WorkItemReviewDecision(self.reviewable_set.items[0].item_id, True, review_notes="Keep initiative."),
            WorkItemReviewDecision(self.reviewable_set.items[1].item_id, True, review_notes="Ship first slice."),
            WorkItemReviewDecision(self.reviewable_set.items[2].item_id, False, review_notes="Out of scope for now."),
            WorkItemReviewDecision(self.reviewable_set.items[3].item_id, False, review_notes="Defer demo work."),
        )

        result = ingest_reviewed_work_items(self.reviewable_set, decisions, service=self.service)

        self.assertEqual(result.approved_items, 2)
        self.assertEqual(result.ingested_items, 2)
        skipped = [item for item in result.item_results if item.skipped]
        self.assertEqual(len(skipped), 2)
        self.assertTrue(all(not item.approved for item in skipped))

    def test_invalid_adjusted_item_is_rejected_without_corrupting_other_items(self) -> None:
        decisions = list(approve_all_items(self.reviewable_set))
        decisions[1] = WorkItemReviewDecision(
            item_id=self.reviewable_set.items[1].item_id,
            approved=True,
            review_notes="Broken on purpose for validation coverage.",
            adjusted_item={"issue": {"title": ""}},
        )

        result = ingest_reviewed_work_items(self.reviewable_set, tuple(decisions), service=self.service)

        self.assertEqual(result.approved_items, 4)
        self.assertEqual(result.ingested_items, 3)

        invalid_items = [item for item in result.item_results if item.invalid_input]
        ingested_items = [item for item in result.item_results if item.ingested]

        self.assertEqual(len(invalid_items), 1)
        self.assertIn("required", invalid_items[0].error.lower())
        self.assertEqual(len(ingested_items), 3)

    def test_duplicate_id_behavior_matches_canonical_submission_policy(self) -> None:
        first_result = ingest_reviewed_work_items(
            self.reviewable_set,
            approve_all_items(self.reviewable_set),
            service=self.service,
        )
        second_result = ingest_reviewed_work_items(
            self.reviewable_set,
            approve_all_items(self.reviewable_set),
            service=self.service,
        )

        self.assertEqual(first_result.ingested_items, 4)
        self.assertEqual(second_result.ingested_items, 0)
        self.assertTrue(all(item.duplicate_task_id for item in second_result.item_results if item.approved))


if __name__ == "__main__":
    unittest.main()
