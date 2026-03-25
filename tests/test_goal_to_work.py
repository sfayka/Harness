from __future__ import annotations

import tempfile
import unittest

from modules.api import HarnessApiService
from modules.goal_to_work import GoalToWorkInputError, GoalToWorkRequest, build_prd_artifact, run_goal_to_work_flow
from modules.prd_ingestion import WorkItemReviewDecision
from modules.store import FileBackedHarnessStore


def _goal_request() -> GoalToWorkRequest:
    return GoalToWorkRequest(
        goal_id="goal-harness-launch",
        title="Harness verification launch",
        product_goal="Ship a verifiable AI-work control plane that proves task outcomes with evidence.",
        target_user="Engineering teams coordinating AI-assisted delivery through Linear and GitHub.",
        problem_statement="Teams cannot trust task completion claims without artifact-backed verification and reconciliation.",
        scope=(
            {
                "id": "linear-ingress",
                "title": "Linear ingress alignment",
                "description": "Map Linear work into canonical Harness task contracts and retain upstream traceability.",
                "category": "integration",
            },
            {
                "id": "verification",
                "title": "Verification and evidence policy",
                "description": "Enforce completion based on evidence validation and reconciled external facts.",
                "category": "verification",
                "depends_on": ["linear-ingress"],
            },
        ),
        constraints=(
            "Use only canonical Harness contracts and public API surfaces.",
            "Keep external integrations connector-neutral and testable without live services.",
        ),
        success_criteria=(
            "Generated work can be reviewed before issue creation.",
            "Each proposed item is compatible with the Linear-shaped ingress adapter.",
        ),
        priority="high",
    )


class GoalToWorkFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.service = HarnessApiService(store=FileBackedHarnessStore(self.temp_dir.name))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_builds_prd_artifact_from_high_level_goal_request(self) -> None:
        prd_artifact = build_prd_artifact(_goal_request())

        self.assertEqual(prd_artifact["id"], "goal-harness-launch")
        self.assertEqual(prd_artifact["title"], "Harness verification launch")
        self.assertEqual(len(prd_artifact["scope"]), 2)

    def test_runs_accepted_end_to_end_flow(self) -> None:
        result = run_goal_to_work_flow(
            _goal_request(),
            auto_approve=True,
            service=self.service,
        )

        self.assertEqual(result.prd_artifact["id"], "goal-harness-launch")
        self.assertEqual(result.proposal.proposal_id, "proposal-goal-harness-launch")
        self.assertEqual(len(result.reviewable_set.items), 3)
        self.assertEqual(len(result.review_decisions), 3)
        self.assertIsNotNone(result.ingestion_result)
        self.assertEqual(result.ingestion_result.approved_items, 3)
        self.assertEqual(result.ingestion_result.ingested_items, 3)

    def test_runs_partially_approved_flow(self) -> None:
        preview = run_goal_to_work_flow(_goal_request(), service=self.service)
        decisions = (
            WorkItemReviewDecision(preview.reviewable_set.items[0].item_id, True, review_notes="Keep umbrella item."),
            WorkItemReviewDecision(preview.reviewable_set.items[1].item_id, True, review_notes="Start with ingress."),
            WorkItemReviewDecision(preview.reviewable_set.items[2].item_id, False, review_notes="Defer verification slice."),
        )

        result = run_goal_to_work_flow(
            _goal_request(),
            review_decisions=decisions,
            service=self.service,
        )

        self.assertIsNotNone(result.ingestion_result)
        self.assertEqual(result.ingestion_result.approved_items, 2)
        self.assertEqual(result.ingestion_result.ingested_items, 2)
        skipped = [item for item in result.ingestion_result.item_results if item.skipped]
        self.assertEqual(len(skipped), 1)

    def test_rejects_invalid_goal_input_cleanly(self) -> None:
        with self.assertRaises(GoalToWorkInputError):
            run_goal_to_work_flow(
                {
                    "title": "Incomplete goal",
                    "product_goal": "Ship something",
                    "target_user": "",
                    "problem_statement": "Missing required data",
                    "scope": [],
                    "constraints": [],
                    "success_criteria": [],
                },
                service=self.service,
            )

    def test_duplicate_id_behavior_is_preserved_during_ingestion(self) -> None:
        first = run_goal_to_work_flow(_goal_request(), auto_approve=True, service=self.service)
        second = run_goal_to_work_flow(_goal_request(), auto_approve=True, service=self.service)

        self.assertEqual(first.ingestion_result.ingested_items, 3)
        self.assertEqual(second.ingestion_result.ingested_items, 0)
        self.assertTrue(
            all(item.duplicate_task_id for item in second.ingestion_result.item_results if item.approved)
        )


if __name__ == "__main__":
    unittest.main()
