from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

EXPECTED_CHAIN = [
    ("01-research-packet.json", "research_packet"),
    ("02-idea-contract.json", "idea_contract"),
    ("03-intent-review.json", "intent_review"),
    ("04-main-review.json", "main_review"),
    ("05-product-plan.json", "product_plan"),
    ("06-build-plan.json", "build_plan"),
    ("07-coder-receipt.json", "coder_receipt"),
    ("08-qa-receipt.json", "qa_receipt"),
    ("09-verification-delta.json", "verification_delta"),
    ("10-trust-report.json", "trust_report"),
    ("11-retention-review.json", "retention_review"),
    ("12-operator-summary.json", "operator_summary"),
]


def _read_json(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append(f"missing_required_artifact: {path.name}")
        return {}
    except json.JSONDecodeError as exc:
        errors.append(f"invalid_json: {path.name}: {exc}")
        return {}
    if not isinstance(data, dict):
        errors.append(f"artifact_not_object: {path.name}")
        return {}
    return data


def validate_buildroom(room_path: str | Path) -> dict[str, Any]:
    """Validate a local Auto-build v0 buildroom contract chain.

    The validator is intentionally deterministic and filesystem-only. It does
    not call GitHub, Linear, cron, an agent runtime, or any live service.
    """
    room = Path(room_path)
    errors: list[str] = []
    artifacts: list[dict[str, Any]] = []

    for filename, expected_kind in EXPECTED_CHAIN:
        artifact = _read_json(room / filename, errors)
        if not artifact:
            continue
        if artifact.get("schema_version") != "buildroom.v0":
            errors.append(f"unsupported_schema_version: {filename}")
        if artifact.get("kind") != expected_kind:
            errors.append(f"unexpected_kind: {filename}: {artifact.get('kind')} != {expected_kind}")
        artifacts.append(artifact)

    job_ids = {artifact.get("job_id") for artifact in artifacts if artifact.get("job_id")}
    if len(job_ids) != 1:
        errors.append(f"job_id_mismatch: {sorted(job_ids)}")
    job_id = next(iter(job_ids), None) if job_ids else None

    by_kind = {artifact.get("kind"): artifact for artifact in artifacts}
    idea = by_kind.get("idea_contract", {})
    intent = by_kind.get("intent_review", {})
    main = by_kind.get("main_review", {})
    product = by_kind.get("product_plan", {})
    build = by_kind.get("build_plan", {})
    coder = by_kind.get("coder_receipt", {})
    qa = by_kind.get("qa_receipt", {})
    delta = by_kind.get("verification_delta", {})
    trust = by_kind.get("trust_report", {})
    retention = by_kind.get("retention_review", {})

    if idea.get("approval_authority") != "main_review":
        errors.append("idea_contract_must_not_self_approve")
    if intent.get("decision") != "ready_for_main_review":
        errors.append("intent_review_not_ready")
    if main.get("decision") != "approved":
        errors.append("main_review_not_approved")
    if build.get("main_review_id") != main.get("id"):
        errors.append("build_plan_missing_main_review_link")

    allowed_paths = set(product.get("allowed_paths", []))
    planned_files = set(product.get("planned_files", []))
    changed_paths = set(coder.get("changed_paths", []))
    for changed_path in sorted(changed_paths):
        if changed_path not in allowed_paths and changed_path not in planned_files:
            errors.append(f"coder_changed_path_outside_allowed_paths: {changed_path}")

    if coder.get("claims_complete") is not True:
        errors.append("coder_receipt_missing_completion_claim")
    if qa.get("verified_by") == coder.get("implemented_by"):
        errors.append("qa_not_independent")
    if qa.get("decision") != "verified":
        errors.append("qa_not_verified")
    if delta.get("state") != "confirmed":
        errors.append("verification_delta_not_confirmed")
    if retention.get("side_effects") != "none":
        errors.append("retention_must_be_recommendation_only")

    guardrails = {
        "dreamer_cannot_approve": idea.get("approval_authority") == "main_review",
        "main_approved_before_build": main.get("decision") == "approved" and build.get("main_review_id") == main.get("id"),
        "coder_paths_within_product_plan": not any(
            changed_path not in allowed_paths and changed_path not in planned_files
            for changed_path in changed_paths
        ),
        "qa_independent_from_coder": bool(qa.get("verified_by")) and qa.get("verified_by") != coder.get("implemented_by"),
        "retention_recommendation_only": retention.get("side_effects") == "none",
    }

    return {
        "valid": not errors,
        "errors": errors,
        "job_id": job_id,
        "artifact_kinds": [artifact.get("kind") for artifact in artifacts],
        "guardrails": guardrails,
        "trust_state": trust.get("state"),
        "retention_recommendation": retention.get("recommendation"),
        "live_mutations_enabled": any(bool(artifact.get("live_mutations_enabled")) for artifact in artifacts),
    }


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    room = Path(argv[0]) if argv else Path("buildroom/examples/demo-room")
    result = validate_buildroom(room)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
