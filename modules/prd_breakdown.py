"""PRD-to-Linear work breakdown generator."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


class PRDBreakdownInputError(ValueError):
    """Raised when a PRD-like input artifact is missing required structure."""


@dataclass(frozen=True)
class WorkBreakdownProposal:
    """Structured, reviewable PRD work breakdown proposal."""

    proposal_id: str
    prd_summary: dict[str, Any]
    initiative: dict[str, Any]
    work_items: tuple[dict[str, Any], ...]


def _require_mapping(value: Any, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PRDBreakdownInputError(f"{field_name} must be a mapping")
    return value


def _require_string(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PRDBreakdownInputError(f"{field_name} is required")
    return value.strip()


def _require_string_list(value: Any, *, field_name: str, min_items: int = 1) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise PRDBreakdownInputError(f"{field_name} must be a list of strings")
    normalized: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise PRDBreakdownInputError(f"{field_name}[{index}] must be a non-empty string")
        normalized.append(item.strip())
    if len(normalized) < min_items:
        raise PRDBreakdownInputError(f"{field_name} must contain at least {min_items} item(s)")
    return tuple(normalized)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "work-item"


def _state_payload() -> dict[str, str]:
    return {
        "id": "workflow_planned",
        "name": "planned",
        "type": "unstarted",
    }


def _normalize_priority(value: Any | None) -> str:
    if value is None:
        return "normal"
    if isinstance(value, int):
        mapping = {
            0: "backlog",
            1: "critical",
            2: "high",
            3: "normal",
            4: "low",
        }
        if value not in mapping:
            raise PRDBreakdownInputError("priority integer must be one of 0, 1, 2, 3, or 4")
        return mapping[value]
    if isinstance(value, str):
        normalized = value.strip().lower()
        aliases = {
            "critical": "critical",
            "urgent": "critical",
            "high": "high",
            "normal": "normal",
            "medium": "normal",
            "low": "low",
            "backlog": "backlog",
        }
        if normalized not in aliases:
            raise PRDBreakdownInputError("priority string must map to a canonical Harness priority")
        return aliases[normalized]
    raise PRDBreakdownInputError("priority must be a string, integer, or null")


def _normalize_scope_item(item: Any, *, index: int) -> dict[str, Any]:
    if isinstance(item, str):
        title = item.strip()
        if not title:
            raise PRDBreakdownInputError(f"scope[{index}] must be a non-empty string")
        return {
            "id": f"scope-{index + 1}",
            "title": title,
            "description": title,
            "category": "feature",
            "priority": None,
            "depends_on": (),
        }

    item = _require_mapping(item, field_name=f"scope[{index}]")
    depends_on = item.get("depends_on", [])
    if depends_on is None:
        depends_on = []
    if not isinstance(depends_on, list):
        raise PRDBreakdownInputError(f"scope[{index}].depends_on must be a list of scope ids")
    normalized_depends_on = []
    for dep_index, dependency in enumerate(depends_on):
        normalized_depends_on.append(_require_string(dependency, field_name=f"scope[{index}].depends_on[{dep_index}]"))

    return {
        "id": _require_string(item.get("id", f"scope-{index + 1}"), field_name=f"scope[{index}].id"),
        "title": _require_string(item.get("title"), field_name=f"scope[{index}].title"),
        "description": _require_string(
            item.get("description") or item.get("title"),
            field_name=f"scope[{index}].description",
        ),
        "category": _require_string(item.get("category", "feature"), field_name=f"scope[{index}].category"),
        "priority": item.get("priority"),
        "depends_on": tuple(normalized_depends_on),
    }


def _normalize_prd_input(prd_input: Mapping[str, Any]) -> dict[str, Any]:
    prd_input = _require_mapping(prd_input, field_name="prd_input")
    prd_id = _require_string(prd_input.get("id") or _slugify(_require_string(prd_input.get("title"), field_name="title")), field_name="id")
    title = _require_string(prd_input.get("title"), field_name="title")

    scope = prd_input.get("scope")
    if not isinstance(scope, list):
        raise PRDBreakdownInputError("scope must be a list")
    normalized_scope = tuple(_normalize_scope_item(item, index=index) for index, item in enumerate(scope))
    if not normalized_scope:
        raise PRDBreakdownInputError("scope must contain at least one work item")

    return {
        "id": prd_id,
        "title": title,
        "product_goal": _require_string(prd_input.get("product_goal"), field_name="product_goal"),
        "target_user": _require_string(prd_input.get("target_user"), field_name="target_user"),
        "problem_statement": _require_string(prd_input.get("problem_statement"), field_name="problem_statement"),
        "constraints": _require_string_list(prd_input.get("constraints"), field_name="constraints"),
        "success_criteria": _require_string_list(prd_input.get("success_criteria"), field_name="success_criteria"),
        "scope": normalized_scope,
        "priority": _normalize_priority(prd_input.get("priority")),
    }


def _project_payload(prd: dict[str, Any]) -> dict[str, str]:
    return {
        "id": prd["id"],
        "name": prd["title"],
    }


def _initiative_description(prd: dict[str, Any]) -> str:
    lines = [
        f"Product goal: {prd['product_goal']}",
        f"Target user/customer: {prd['target_user']}",
        f"Problem statement: {prd['problem_statement']}",
        "",
        "Scope items:",
    ]
    lines.extend(f"- {item['title']}: {item['description']}" for item in prd["scope"])
    lines.append("")
    lines.append("Success criteria:")
    lines.extend(f"- {criterion}" for criterion in prd["success_criteria"])
    lines.append("")
    lines.append("Constraints:")
    lines.extend(f"- {constraint}" for constraint in prd["constraints"])
    lines.append("")
    lines.append("Generated by Harness as a proposed, reviewable work breakdown.")
    return "\n".join(lines)


def _child_description(prd: dict[str, Any], scope_item: dict[str, Any]) -> str:
    lines = [
        f"PRD goal: {prd['product_goal']}",
        f"Target user/customer: {prd['target_user']}",
        f"Problem statement: {prd['problem_statement']}",
        "",
        f"Workstream focus: {scope_item['description']}",
        "",
        "Relevant constraints:",
    ]
    lines.extend(f"- {constraint}" for constraint in prd["constraints"])
    lines.append("")
    lines.append("Relevant success criteria:")
    lines.extend(f"- {criterion}" for criterion in prd["success_criteria"])
    lines.append("")
    lines.append("Generated by Harness as a proposed work item for review.")
    return "\n".join(lines)


def _acceptance_criteria(scope_item: dict[str, Any], *, prd_identifier: str) -> list[dict[str, Any]]:
    return [
        {
            "id": f"{scope_item['id']}-implemented",
            "description": f"{scope_item['title']} is delivered in a way that supports {prd_identifier}.",
            "required": True,
        },
        {
            "id": f"{scope_item['id']}-verifiable",
            "description": "Resulting work can be verified by Harness using artifacts and reconciled external facts.",
            "required": True,
        },
    ]


def _initiative_acceptance_criteria(prd_identifier: str) -> list[dict[str, Any]]:
    return [
        {
            "id": "initiative-reviewable-breakdown",
            "description": f"The proposed work breakdown for {prd_identifier} is reviewable and complete enough for issue creation.",
            "required": True,
        }
    ]


def _initiative_item(prd: dict[str, Any]) -> dict[str, Any]:
    issue_identifier = f"PRD-{prd['id'].upper()}-INIT"
    return {
        "issue": {
            "id": f"{prd['id']}-initiative",
            "identifier": issue_identifier,
            "title": f"{prd['title']} work breakdown",
            "description": _initiative_description(prd),
        },
        "state": _state_payload(),
        "project": _project_payload(prd),
        "task_reference": {
            "external_ref": issue_identifier,
        },
        "labels": ["prd-generated", "initiative", "reviewable"],
        "priority": prd["priority"],
        "acceptance_criteria": _initiative_acceptance_criteria(issue_identifier),
        "metadata": {
            "generated_from_prd_id": prd["id"],
            "proposal_kind": "initiative",
            "review_status": "proposed",
        },
        "dependency_hints": [],
        "sequence": 0,
    }


def _child_item(prd: dict[str, Any], scope_item: dict[str, Any], *, sequence: int) -> dict[str, Any]:
    slug = _slugify(scope_item["title"])
    issue_identifier = f"PRD-{prd['id'].upper()}-{sequence:02d}"
    dependency_hints = [dependency for dependency in scope_item["depends_on"]]
    return {
        "issue": {
            "id": f"{prd['id']}-{scope_item['id']}-{slug}",
            "identifier": issue_identifier,
            "title": scope_item["title"],
            "description": _child_description(prd, scope_item),
        },
        "state": _state_payload(),
        "project": _project_payload(prd),
        "task_reference": {
            "external_ref": issue_identifier,
        },
        "labels": ["prd-generated", "reviewable", scope_item["category"]],
        "priority": _normalize_priority(scope_item["priority"] or prd["priority"]),
        "acceptance_criteria": _acceptance_criteria(scope_item, prd_identifier=prd["id"]),
        "metadata": {
            "generated_from_prd_id": prd["id"],
            "proposal_kind": "work_item",
            "scope_id": scope_item["id"],
            "review_status": "proposed",
            "category": scope_item["category"],
        },
        "dependency_hints": dependency_hints,
        "sequence": sequence,
    }


def generate_linear_work_breakdown(prd_input: Mapping[str, Any]) -> WorkBreakdownProposal:
    """Generate a reviewable Linear-shaped work breakdown from a PRD-like input."""

    prd = _normalize_prd_input(prd_input)
    initiative = _initiative_item(prd)
    work_items = tuple(
        _child_item(prd, scope_item, sequence=index + 1)
        for index, scope_item in enumerate(prd["scope"])
    )

    return WorkBreakdownProposal(
        proposal_id=f"proposal-{prd['id']}",
        prd_summary={
            "id": prd["id"],
            "title": prd["title"],
            "product_goal": prd["product_goal"],
            "target_user": prd["target_user"],
            "problem_statement": prd["problem_statement"],
            "constraints": list(prd["constraints"]),
            "success_criteria": list(prd["success_criteria"]),
            "scope_count": len(prd["scope"]),
        },
        initiative=initiative,
        work_items=work_items,
    )


def list_example_prds() -> tuple[str, ...]:
    """Return supported example PRD fixture names."""

    return ("feature_platform", "narrow_improvement")


def build_example_prd(example_name: str) -> dict[str, Any]:
    """Build one canonical PRD-like fixture for tests and local exploration."""

    if example_name == "feature_platform":
        return {
            "id": "harness-prd",
            "title": "Harness verification launch",
            "product_goal": "Ship a verifiable AI-work control plane that proves task outcomes with evidence.",
            "target_user": "Engineering teams coordinating AI-assisted delivery through Linear and GitHub.",
            "problem_statement": "Teams cannot trust task completion claims without artifact-backed verification and reconciliation.",
            "scope": [
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
                {
                    "id": "demo-flow",
                    "title": "Demo and audit trace flow",
                    "description": "Provide a visible end-to-end demo showing lifecycle transitions and audit traces.",
                    "category": "demo",
                    "depends_on": ["verification"],
                },
            ],
            "constraints": [
                "Use only canonical Harness contracts and public API surfaces.",
                "Keep external integrations connector-neutral and testable without live services.",
            ],
            "success_criteria": [
                "Generated work can be reviewed before issue creation.",
                "Each proposed item is compatible with the Linear-shaped ingress adapter.",
                "The resulting work set is small enough to sequence explicitly.",
            ],
            "priority": "high",
        }

    if example_name == "narrow_improvement":
        return {
            "id": "clarification-loop",
            "title": "Clarification loop improvement",
            "product_goal": "Reduce friction when Harness blocks on missing information.",
            "target_user": "Operators reviewing blocked AI-assisted tasks.",
            "problem_statement": "Blocked tasks lack a consistent reviewable handoff into clarification-oriented follow-up work.",
            "scope": [
                {
                    "id": "clarification-surface",
                    "title": "Clarification request visibility",
                    "description": "Expose missing-information requests as a clear reviewable work item.",
                    "category": "workflow",
                }
            ],
            "constraints": [
                "Keep the change small and reviewable.",
                "Avoid changing core lifecycle policy in this pass.",
            ],
            "success_criteria": [
                "The generated work set contains only the minimum required work item.",
                "The output remains compatible with existing Linear-shaped ingress.",
            ],
            "priority": "normal",
        }

    raise ValueError(f"Unknown example PRD {example_name!r}")


__all__ = [
    "PRDBreakdownInputError",
    "WorkBreakdownProposal",
    "build_example_prd",
    "generate_linear_work_breakdown",
    "list_example_prds",
]
