from __future__ import annotations

import unittest

from modules.contracts.task_envelope_review import (
    ReviewFollowUpAction,
    ReviewOutcome,
    ReviewRequest,
    ReviewTrigger,
    ReviewValidationError,
    ReviewerIdentity,
    append_review_record,
    resolve_review_request,
    validate_review_request,
)


def _base_review_request() -> ReviewRequest:
    return ReviewRequest(
        review_request_id="review-request-1",
        task_id="task-1",
        requested_at="2026-03-24T16:00:00Z",
        requested_by="verification",
        trigger=ReviewTrigger.VERIFICATION,
        summary="Automatic verification could not safely resolve the completion claim.",
        presented_sections=("task_state", "evidence", "reconciliation", "runtime_facts"),
        allowed_outcomes=(
            ReviewOutcome.ACCEPT_COMPLETION,
            ReviewOutcome.KEEP_BLOCKED,
            ReviewOutcome.REJECT_COMPLETION,
            ReviewOutcome.MARK_FAILED,
        ),
        prior_review_ids=(),
        metadata={"source": "verification-run-1"},
    )


def _base_reviewer() -> ReviewerIdentity:
    return ReviewerIdentity(
        reviewer_id="operator-1",
        reviewer_name="Casey Reviewer",
        authority_role="operator",
    )


class ManualReviewPrimitiveTests(unittest.TestCase):
    def test_validates_and_resolves_accept_completion_review(self) -> None:
        review_request = validate_review_request(_base_review_request())

        result = resolve_review_request(
            review_request,
            review_id="review-1",
            reviewer=_base_reviewer(),
            outcome=ReviewOutcome.ACCEPT_COMPLETION,
            reasoning="Evidence and reconciliation are sufficient after manual inspection.",
            reviewed_at="2026-03-24T16:10:00Z",
            basis_refs=("verification-run-1", "artifact-pr-1"),
        )

        self.assertEqual(result.recommended_target_status, "completed")
        self.assertEqual(result.follow_up_action, ReviewFollowUpAction.NONE)
        self.assertEqual(result.record.outcome, ReviewOutcome.ACCEPT_COMPLETION)
        self.assertTrue(result.record.preserves_history)

    def test_rejects_review_request_missing_presented_sections(self) -> None:
        review_request = ReviewRequest(
            review_request_id="review-request-2",
            task_id="task-1",
            requested_at="2026-03-24T16:00:00Z",
            requested_by="verification",
            trigger=ReviewTrigger.VERIFICATION,
            summary="Missing reviewed information bundle.",
            presented_sections=(),
            allowed_outcomes=(ReviewOutcome.KEEP_BLOCKED,),
        )

        with self.assertRaisesRegex(ReviewValidationError, "presented_sections"):
            validate_review_request(review_request)

    def test_rejects_outcome_not_explicitly_allowed_by_policy(self) -> None:
        review_request = _base_review_request()

        with self.assertRaisesRegex(ReviewValidationError, "not allowed"):
            resolve_review_request(
                review_request,
                review_id="review-2",
                reviewer=_base_reviewer(),
                outcome=ReviewOutcome.AUTHORIZE_REDISPATCH,
                reasoning="Need a different executor.",
            )

    def test_allows_redispatch_only_when_explicitly_permitted(self) -> None:
        review_request = ReviewRequest(
            review_request_id="review-request-3",
            task_id="task-1",
            requested_at="2026-03-24T16:00:00Z",
            requested_by="operator",
            trigger=ReviewTrigger.RUNTIME_ANOMALY,
            summary="Current assignment is no longer trustworthy.",
            presented_sections=("task_state", "runtime_facts"),
            allowed_outcomes=(ReviewOutcome.KEEP_BLOCKED, ReviewOutcome.AUTHORIZE_REDISPATCH),
        )

        result = resolve_review_request(
            review_request,
            review_id="review-3",
            reviewer=_base_reviewer(),
            outcome=ReviewOutcome.AUTHORIZE_REDISPATCH,
            reasoning="Redispatch is safer than preserving the current assignment.",
        )

        self.assertEqual(result.recommended_target_status, "dispatch_ready")
        self.assertEqual(result.follow_up_action, ReviewFollowUpAction.REDISPATCH)

    def test_rejects_missing_reviewer_metadata(self) -> None:
        reviewer = ReviewerIdentity(reviewer_id="", reviewer_name="Casey Reviewer", authority_role="operator")

        with self.assertRaisesRegex(ReviewValidationError, "reviewer.reviewer_id"):
            resolve_review_request(
                _base_review_request(),
                review_id="review-4",
                reviewer=reviewer,
                outcome=ReviewOutcome.KEEP_BLOCKED,
                reasoning="Still waiting on external confirmation.",
            )

    def test_append_review_record_preserves_prior_history(self) -> None:
        initial = resolve_review_request(
            _base_review_request(),
            review_id="review-5",
            reviewer=_base_reviewer(),
            outcome=ReviewOutcome.KEEP_BLOCKED,
            reasoning="More evidence is still required.",
        ).record

        follow_up = resolve_review_request(
            _base_review_request(),
            review_id="review-6",
            reviewer=_base_reviewer(),
            outcome=ReviewOutcome.ACCEPT_COMPLETION,
            reasoning="Additional evidence resolves the earlier blocker.",
            supersedes_review_id="review-5",
        ).record

        history = append_review_record((), initial)
        updated_history = append_review_record(history, follow_up)

        self.assertEqual(len(updated_history), 2)
        self.assertEqual(updated_history[0].review_id, "review-5")
        self.assertEqual(updated_history[1].supersedes_review_id, "review-5")

    def test_rejects_superseding_unknown_review_record(self) -> None:
        record = resolve_review_request(
            _base_review_request(),
            review_id="review-7",
            reviewer=_base_reviewer(),
            outcome=ReviewOutcome.KEEP_BLOCKED,
            reasoning="Still blocked pending evidence.",
            supersedes_review_id="review-missing",
        ).record

        with self.assertRaisesRegex(ReviewValidationError, "does not exist"):
            append_review_record((), record)

    def test_require_clarification_records_follow_up_action(self) -> None:
        review_request = ReviewRequest(
            review_request_id="review-request-4",
            task_id="task-clarify-1",
            requested_at="2026-03-24T16:00:00Z",
            requested_by="clarification",
            trigger=ReviewTrigger.CLARIFICATION,
            summary="Clarification is deadlocked.",
            presented_sections=("task_state", "clarification"),
            allowed_outcomes=(ReviewOutcome.REQUIRE_CLARIFICATION, ReviewOutcome.CANCEL_TASK),
        )

        result = resolve_review_request(
            review_request,
            review_id="review-8",
            reviewer=_base_reviewer(),
            outcome=ReviewOutcome.REQUIRE_CLARIFICATION,
            reasoning="The task needs explicit human clarification before continuing.",
        )

        self.assertEqual(result.recommended_target_status, "blocked")
        self.assertEqual(result.follow_up_action, ReviewFollowUpAction.CLARIFICATION)


if __name__ == "__main__":
    unittest.main()
