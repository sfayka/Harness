"""Review-and-approve bulk ingestion flow for PRD-generated work items."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from modules.api import HarnessApiService
from modules.prd_breakdown import WorkBreakdownProposal


@dataclass(frozen=True)
class ReviewableWorkItem:
    """One proposed Linear-shaped work item awaiting explicit review."""

    item_id: str
    item_type: str
    title: str
    proposed_item: dict[str, Any]


@dataclass(frozen=True)
class ReviewableWorkItemSet:
    """A reviewable set of proposed work items before ingestion."""

    proposal_id: str
    prd_summary: dict[str, Any]
    items: tuple[ReviewableWorkItem, ...]


@dataclass(frozen=True)
class WorkItemReviewDecision:
    """Explicit review decision for one proposed work item."""

    item_id: str
    approved: bool
    review_notes: str | None = None
    adjusted_item: dict[str, Any] | None = None


@dataclass(frozen=True)
class BulkIngestionItemResult:
    """Per-item bulk-ingestion outcome."""

    item_id: str
    item_type: str
    title: str
    approved: bool
    submitted_item: dict[str, Any] | None
    http_status: int | None
    ingested: bool
    skipped: bool
    duplicate_task_id: bool
    invalid_input: bool
    task_id: str | None
    task_status: str | None
    action: str | None
    error: str | None
    review_notes: str | None


@dataclass(frozen=True)
class BulkIngestionResult:
    """Structured result for reviewed bulk ingestion of generated work items."""

    proposal_id: str
    total_items: int
    approved_items: int
    ingested_items: int
    item_results: tuple[BulkIngestionItemResult, ...]


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _proposal_items(proposal: WorkBreakdownProposal) -> tuple[ReviewableWorkItem, ...]:
    items: list[ReviewableWorkItem] = [
        ReviewableWorkItem(
            item_id=str(proposal.initiative["issue"]["id"]),
            item_type="initiative",
            title=str(proposal.initiative["issue"]["title"]),
            proposed_item=dict(proposal.initiative),
        )
    ]
    for work_item in proposal.work_items:
        items.append(
            ReviewableWorkItem(
                item_id=str(work_item["issue"]["id"]),
                item_type="work_item",
                title=str(work_item["issue"]["title"]),
                proposed_item=dict(work_item),
            )
        )
    return tuple(items)


def prepare_reviewable_work_items(proposal: WorkBreakdownProposal) -> ReviewableWorkItemSet:
    """Convert a generated proposal into an explicit reviewable item set."""

    return ReviewableWorkItemSet(
        proposal_id=proposal.proposal_id,
        prd_summary=dict(proposal.prd_summary),
        items=_proposal_items(proposal),
    )


def approve_all_items(reviewable_set: ReviewableWorkItemSet, *, review_notes: str | None = None) -> tuple[WorkItemReviewDecision, ...]:
    """Build an approval decision set that accepts every proposed item."""

    return tuple(
        WorkItemReviewDecision(item_id=item.item_id, approved=True, review_notes=review_notes)
        for item in reviewable_set.items
    )


def ingest_reviewed_work_items(
    reviewable_set: ReviewableWorkItemSet,
    decisions: tuple[WorkItemReviewDecision, ...] | list[WorkItemReviewDecision],
    *,
    service: HarnessApiService | None = None,
) -> BulkIngestionResult:
    """Ingest approved generated work items through the canonical Linear ingress path."""

    api_service = service or HarnessApiService()
    decision_map = {decision.item_id: decision for decision in decisions}

    item_results: list[BulkIngestionItemResult] = []
    ingested_items = 0
    approved_items = 0

    for item in reviewable_set.items:
        decision = decision_map.get(item.item_id)
        if decision is None or not decision.approved:
            item_results.append(
                BulkIngestionItemResult(
                    item_id=item.item_id,
                    item_type=item.item_type,
                    title=item.title,
                    approved=False,
                    submitted_item=None,
                    http_status=None,
                    ingested=False,
                    skipped=True,
                    duplicate_task_id=False,
                    invalid_input=False,
                    task_id=None,
                    task_status=None,
                    action=None,
                    error=None,
                    review_notes=decision.review_notes if decision is not None else None,
                )
            )
            continue

        approved_items += 1
        submitted_item = dict(item.proposed_item)
        if decision.adjusted_item is not None:
            submitted_item = _deep_merge(submitted_item, decision.adjusted_item)

        http_status, payload = api_service.submit_linear_ingress(submitted_item)
        ingested = 200 <= http_status < 300 and not payload.get("invalid_input", False)
        if ingested:
            ingested_items += 1

        task_envelope = payload.get("task_envelope") if isinstance(payload, dict) else None
        item_results.append(
            BulkIngestionItemResult(
                item_id=item.item_id,
                item_type=item.item_type,
                title=item.title,
                approved=True,
                submitted_item=submitted_item,
                http_status=http_status,
                ingested=ingested,
                skipped=False,
                duplicate_task_id=bool(payload.get("duplicate_task_id", False)) if isinstance(payload, dict) else False,
                invalid_input=bool(payload.get("invalid_input", False)) if isinstance(payload, dict) else False,
                task_id=(task_envelope or {}).get("id") if isinstance(task_envelope, dict) else None,
                task_status=(task_envelope or {}).get("status") if isinstance(task_envelope, dict) else None,
                action=payload.get("action") if isinstance(payload, dict) else None,
                error=payload.get("error") if isinstance(payload, dict) else None,
                review_notes=decision.review_notes,
            )
        )

    return BulkIngestionResult(
        proposal_id=reviewable_set.proposal_id,
        total_items=len(reviewable_set.items),
        approved_items=approved_items,
        ingested_items=ingested_items,
        item_results=tuple(item_results),
    )


__all__ = [
    "BulkIngestionItemResult",
    "BulkIngestionResult",
    "ReviewableWorkItem",
    "ReviewableWorkItemSet",
    "WorkItemReviewDecision",
    "approve_all_items",
    "ingest_reviewed_work_items",
    "prepare_reviewable_work_items",
]
