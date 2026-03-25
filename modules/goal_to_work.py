"""Canonical goal-to-work orchestration flow for Harness."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from modules.api import HarnessApiService
from modules.prd_breakdown import (
    PRDBreakdownInputError,
    WorkBreakdownProposal,
    generate_linear_work_breakdown,
)
from modules.prd_ingestion import (
    BulkIngestionResult,
    ReviewableWorkItemSet,
    WorkItemReviewDecision,
    approve_all_items,
    ingest_reviewed_work_items,
    prepare_reviewable_work_items,
)


class GoalToWorkInputError(ValueError):
    """Raised when a high-level goal request cannot be normalized into a PRD-like artifact."""


@dataclass(frozen=True)
class GoalToWorkRequest:
    """Structured high-level goal input for the canonical upstream flow."""

    title: str
    product_goal: str
    target_user: str
    problem_statement: str
    scope: tuple[dict[str, Any] | str, ...]
    constraints: tuple[str, ...]
    success_criteria: tuple[str, ...]
    goal_id: str | None = None
    priority: str | int | None = None


@dataclass(frozen=True)
class GoalToWorkFlowResult:
    """Auditable output of the canonical goal-to-work flow."""

    prd_artifact: dict[str, Any]
    proposal: WorkBreakdownProposal
    reviewable_set: ReviewableWorkItemSet
    review_decisions: tuple[WorkItemReviewDecision, ...]
    ingestion_result: BulkIngestionResult | None


def _require_string(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GoalToWorkInputError(f"{field_name} is required")
    return value.strip()


def _require_string_list(value: Any, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise GoalToWorkInputError(f"{field_name} must be a list of strings")
    normalized: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise GoalToWorkInputError(f"{field_name}[{index}] must be a non-empty string")
        normalized.append(item.strip())
    if not normalized:
        raise GoalToWorkInputError(f"{field_name} must contain at least one item")
    return tuple(normalized)


def _normalize_scope(value: Any) -> tuple[dict[str, Any] | str, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise GoalToWorkInputError("scope must contain at least one proposed workstream")
    normalized: list[dict[str, Any] | str] = []
    for index, item in enumerate(value):
        if isinstance(item, str):
            if not item.strip():
                raise GoalToWorkInputError(f"scope[{index}] must be a non-empty string")
            normalized.append(item.strip())
            continue
        if not isinstance(item, dict):
            raise GoalToWorkInputError(f"scope[{index}] must be either a string or an object")
        normalized.append(dict(item))
    return tuple(normalized)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "goal"


def build_prd_artifact(goal_request: GoalToWorkRequest | dict[str, Any]) -> dict[str, Any]:
    """Build the canonical PRD-like artifact used by the goal-to-work flow."""

    if isinstance(goal_request, GoalToWorkRequest):
        title = _require_string(goal_request.title, field_name="title")
        goal_id = goal_request.goal_id or _slugify(title)
        return {
            "id": goal_id,
            "title": title,
            "product_goal": _require_string(goal_request.product_goal, field_name="product_goal"),
            "target_user": _require_string(goal_request.target_user, field_name="target_user"),
            "problem_statement": _require_string(goal_request.problem_statement, field_name="problem_statement"),
            "scope": [item if isinstance(item, str) else dict(item) for item in goal_request.scope],
            "constraints": list(goal_request.constraints),
            "success_criteria": list(goal_request.success_criteria),
            "priority": goal_request.priority,
        }

    if not isinstance(goal_request, dict):
        raise GoalToWorkInputError("goal_request must be a GoalToWorkRequest or mapping")

    title = _require_string(goal_request.get("title"), field_name="title")
    goal_id = goal_request.get("goal_id") or goal_request.get("id") or _slugify(title)

    return {
        "id": _require_string(goal_id, field_name="goal_id"),
        "title": title,
        "product_goal": _require_string(goal_request.get("product_goal"), field_name="product_goal"),
        "target_user": _require_string(goal_request.get("target_user"), field_name="target_user"),
        "problem_statement": _require_string(goal_request.get("problem_statement"), field_name="problem_statement"),
        "scope": list(_normalize_scope(goal_request.get("scope"))),
        "constraints": list(_require_string_list(goal_request.get("constraints"), field_name="constraints")),
        "success_criteria": list(_require_string_list(goal_request.get("success_criteria"), field_name="success_criteria")),
        "priority": goal_request.get("priority"),
    }


def run_goal_to_work_flow(
    goal_request: GoalToWorkRequest | dict[str, Any],
    *,
    review_decisions: tuple[WorkItemReviewDecision, ...] | list[WorkItemReviewDecision] | None = None,
    auto_approve: bool = False,
    service: HarnessApiService | None = None,
) -> GoalToWorkFlowResult:
    """Run the canonical flow from high-level goal to reviewable and ingestible work."""

    prd_artifact = build_prd_artifact(goal_request)

    try:
        proposal = generate_linear_work_breakdown(prd_artifact)
    except PRDBreakdownInputError as error:
        raise GoalToWorkInputError(str(error)) from error

    reviewable_set = prepare_reviewable_work_items(proposal)

    normalized_decisions: tuple[WorkItemReviewDecision, ...]
    if review_decisions is not None:
        normalized_decisions = tuple(review_decisions)
    elif auto_approve:
        normalized_decisions = approve_all_items(
            reviewable_set,
            review_notes="Auto-approved for the canonical goal-to-work flow.",
        )
    else:
        normalized_decisions = ()

    ingestion_result = None
    if normalized_decisions:
        ingestion_result = ingest_reviewed_work_items(
            reviewable_set,
            normalized_decisions,
            service=service,
        )

    return GoalToWorkFlowResult(
        prd_artifact=prd_artifact,
        proposal=proposal,
        reviewable_set=reviewable_set,
        review_decisions=normalized_decisions,
        ingestion_result=ingestion_result,
    )


__all__ = [
    "GoalToWorkFlowResult",
    "GoalToWorkInputError",
    "GoalToWorkRequest",
    "build_prd_artifact",
    "run_goal_to_work_flow",
]
