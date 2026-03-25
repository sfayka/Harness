"""Evidence validation primitives for canonical TaskEnvelope artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_PATH = _REPO_ROOT / "schemas" / "task_envelope.schema.json"
_ROOT_SCHEMA = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def _build_defs_validator(def_name: str) -> Draft202012Validator:
    return Draft202012Validator(
        {
            "$schema": _ROOT_SCHEMA["$schema"],
            "$defs": _ROOT_SCHEMA["$defs"],
            "$ref": f"#/$defs/{def_name}",
        }
    )


_ARTIFACT_VALIDATOR = _build_defs_validator("artifactRecord")
_COMPLETION_EVIDENCE_VALIDATOR = _build_defs_validator("completionEvidence")

_EVIDENCE_RELEVANT_TYPES = {
    "pull_request",
    "commit",
    "branch",
    "changed_file",
    "log",
    "output",
    "review_note",
}
_LONG_RUNNING_CONTEXT_TYPES = {
    "progress_artifact",
    "plan_artifact",
    "handoff_artifact",
}
_SATISFYING_VERIFICATION_STATUSES = {"verified"}


@dataclass(frozen=True)
class ValidationIssue:
    """Machine-readable evidence validation issue."""

    code: str
    message: str
    path: str = "/"
    artifact_id: str | None = None


@dataclass(frozen=True)
class ArtifactValidationResult:
    """Validation outcome for a single canonical artifact record."""

    artifact_id: str | None
    artifact_type: str | None
    is_valid: bool
    issues: tuple[ValidationIssue, ...]


@dataclass(frozen=True)
class CompletionEvidenceValidationResult:
    """Validation outcome for completion evidence plus attached artifacts."""

    is_valid: bool
    is_sufficient: bool
    artifact_results: tuple[ArtifactValidationResult, ...]
    issues: tuple[ValidationIssue, ...]
    validated_artifact_ids: tuple[str, ...]
    missing_required_artifact_types: tuple[str, ...]
    unknown_validated_artifact_ids: tuple[str, ...]


class EvidenceValidationError(ValueError):
    """Base error for invalid evidence structures."""


class ArtifactValidationError(EvidenceValidationError):
    """Raised when a canonical artifact record is malformed."""


class CompletionEvidenceValidationError(EvidenceValidationError):
    """Raised when completion evidence is malformed or contradictory."""


def _schema_issues(validator: Draft202012Validator, instance: Any, *, artifact_id: str | None = None) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for error in sorted(validator.iter_errors(instance), key=lambda item: list(item.absolute_path)):
        path = "/" + "/".join(str(part) for part in error.absolute_path)
        issues.append(
            ValidationIssue(
                code="schema_validation_error",
                message=error.message,
                path=path if path != "/" else "/",
                artifact_id=artifact_id,
            )
        )
    return issues


def _append_issue(
    issues: list[ValidationIssue],
    *,
    code: str,
    message: str,
    path: str = "/",
    artifact_id: str | None = None,
) -> None:
    issues.append(ValidationIssue(code=code, message=message, path=path, artifact_id=artifact_id))


def validate_artifact_record(artifact: dict[str, Any]) -> ArtifactValidationResult:
    """Validate a single canonical artifact record."""

    artifact_id = artifact.get("id") if isinstance(artifact, dict) else None
    artifact_type = artifact.get("type") if isinstance(artifact, dict) else None
    issues = _schema_issues(_ARTIFACT_VALIDATOR, artifact, artifact_id=artifact_id)

    # Long-running context artifacts are valid first-class artifacts in the schema,
    # but they do not carry extra completion-bearing semantics by default.
    if not issues and artifact_type in _LONG_RUNNING_CONTEXT_TYPES:
        return ArtifactValidationResult(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            is_valid=True,
            issues=(),
        )

    if not issues and artifact_type in _EVIDENCE_RELEVANT_TYPES:
        if artifact_type == "pull_request" and artifact.get("pull_request_number") is None:
            _append_issue(
                issues,
                code="required_artifact_field_missing",
                message="pull_request artifacts must include a non-null pull_request_number",
                path="/pull_request_number",
                artifact_id=artifact_id,
            )
        if artifact_type == "commit" and not artifact.get("commit_sha"):
            _append_issue(
                issues,
                code="required_artifact_field_missing",
                message="commit artifacts must include a non-null commit_sha",
                path="/commit_sha",
                artifact_id=artifact_id,
            )
        if artifact_type in {"pull_request", "commit", "branch", "changed_file"} and artifact.get("repository") is None:
            _append_issue(
                issues,
                code="required_artifact_field_missing",
                message=f"{artifact_type} artifacts must include repository identity",
                path="/repository",
                artifact_id=artifact_id,
            )
        if artifact_type in {"pull_request", "branch", "changed_file"} and artifact.get("branch") is None:
            _append_issue(
                issues,
                code="required_artifact_field_missing",
                message=f"{artifact_type} artifacts must include branch identity",
                path="/branch",
                artifact_id=artifact_id,
            )
        if artifact_type == "changed_file" and not (artifact.get("changed_files") or []):
            _append_issue(
                issues,
                code="required_artifact_field_missing",
                message="changed_file artifacts must include at least one changed file record",
                path="/changed_files",
                artifact_id=artifact_id,
            )
        changed_files = artifact.get("changed_files") or []
        if artifact_type != "changed_file" and changed_files and artifact.get("repository") is None:
            _append_issue(
                issues,
                code="artifact_repository_missing",
                message="Artifacts carrying changed_files must include repository identity",
                path="/repository",
                artifact_id=artifact_id,
            )

    return ArtifactValidationResult(
        artifact_id=artifact_id,
        artifact_type=artifact_type,
        is_valid=not issues,
        issues=tuple(issues),
    )


def assert_valid_artifact_record(artifact: dict[str, Any]) -> ArtifactValidationResult:
    """Raise if a canonical artifact record is malformed."""

    result = validate_artifact_record(artifact)
    if not result.is_valid:
        joined = "; ".join(f"{issue.path} {issue.message}" for issue in result.issues)
        raise ArtifactValidationError(f"Invalid artifact record: {joined}")
    return result


def validate_completion_evidence(
    artifacts: list[dict[str, Any]],
    completion_evidence: dict[str, Any],
) -> CompletionEvidenceValidationResult:
    """Validate completion evidence and its relationship to attached artifacts."""

    issues: list[ValidationIssue] = []
    artifact_results = tuple(validate_artifact_record(artifact) for artifact in artifacts)
    for artifact_result in artifact_results:
        issues.extend(artifact_result.issues)

    issues.extend(_schema_issues(_COMPLETION_EVIDENCE_VALIDATOR, completion_evidence))

    artifact_id_map: dict[str, ArtifactValidationResult] = {}
    duplicate_ids: set[str] = set()
    for artifact_result in artifact_results:
        if artifact_result.artifact_id is None:
            continue
        if artifact_result.artifact_id in artifact_id_map:
            duplicate_ids.add(artifact_result.artifact_id)
        artifact_id_map[artifact_result.artifact_id] = artifact_result

    for artifact_id in sorted(duplicate_ids):
        _append_issue(
            issues,
            code="duplicate_artifact_id",
            message=f"Artifact id {artifact_id!r} appears more than once",
            path="/artifacts/items",
            artifact_id=artifact_id,
        )

    validated_artifact_ids = tuple(completion_evidence.get("validated_artifact_ids", []))
    required_artifact_types = tuple(completion_evidence.get("required_artifact_types", []))
    policy = completion_evidence.get("policy")
    status = completion_evidence.get("status")
    validation_method = completion_evidence.get("validation_method")

    unknown_validated_artifact_ids = tuple(
        artifact_id for artifact_id in validated_artifact_ids if artifact_id not in artifact_id_map
    )
    for artifact_id in unknown_validated_artifact_ids:
        _append_issue(
            issues,
            code="unknown_validated_artifact_id",
            message=f"Validated artifact id {artifact_id!r} does not refer to an attached artifact",
            path="/validated_artifact_ids",
            artifact_id=artifact_id,
        )

    validated_artifacts = [artifact_id_map[artifact_id] for artifact_id in validated_artifact_ids if artifact_id in artifact_id_map]
    validated_types = {result.artifact_type for result in validated_artifacts}
    missing_required_artifact_types = tuple(
        artifact_type for artifact_type in required_artifact_types if artifact_type not in validated_types
    )

    if policy == "required":
        if status == "satisfied" and not validated_artifact_ids:
            _append_issue(
                issues,
                code="validated_artifacts_required",
                message="Required satisfied evidence must cite at least one validated artifact id",
                path="/validated_artifact_ids",
            )
        if status == "satisfied" and missing_required_artifact_types:
            _append_issue(
                issues,
                code="missing_required_artifact_types",
                message="Required satisfied evidence is missing one or more required artifact types",
                path="/required_artifact_types",
            )
        if status == "satisfied":
            for artifact_result in validated_artifacts:
                artifact = next(item for item in artifacts if item.get("id") == artifact_result.artifact_id)
                verification_status = artifact.get("verification_status")
                if verification_status not in _SATISFYING_VERIFICATION_STATUSES:
                    _append_issue(
                        issues,
                        code="validated_artifact_not_verified",
                        message=(
                            f"Validated artifact {artifact_result.artifact_id!r} must be verified for "
                            "required satisfied evidence"
                        ),
                        path="/validated_artifact_ids",
                        artifact_id=artifact_result.artifact_id,
                    )

    if status == "satisfied" and validation_method in {"deferred", "none"}:
        _append_issue(
            issues,
            code="invalid_validation_method",
            message="Satisfied evidence cannot use deferred or none as the validation method",
            path="/validation_method",
        )

    if validated_artifact_ids and validation_method in {"deferred", "none"}:
        _append_issue(
            issues,
            code="validated_artifacts_without_validation_method",
            message="Validated artifact ids require a non-deferred validation method",
            path="/validated_artifact_ids",
        )

    if policy == "not_applicable":
        if status != "not_applicable":
            _append_issue(
                issues,
                code="not_applicable_status_mismatch",
                message="not_applicable policy requires not_applicable status",
                path="/status",
            )
        if required_artifact_types:
            _append_issue(
                issues,
                code="not_applicable_requires_no_types",
                message="not_applicable policy must not declare required artifact types",
                path="/required_artifact_types",
            )
        if validated_artifact_ids:
            _append_issue(
                issues,
                code="not_applicable_requires_no_validated_artifacts",
                message="not_applicable policy must not cite validated artifact ids",
                path="/validated_artifact_ids",
            )

    if policy == "deferred" and status not in {"deferred", "pending"}:
        _append_issue(
            issues,
            code="deferred_policy_status_mismatch",
            message="deferred policy may only use deferred or pending status",
            path="/status",
        )

    if status == "not_applicable" and policy != "not_applicable":
        _append_issue(
            issues,
            code="status_policy_mismatch",
            message="not_applicable status requires not_applicable policy",
            path="/policy",
        )

    invalid_codes = {
        "schema_validation_error",
        "artifact_repository_missing",
        "duplicate_artifact_id",
        "required_artifact_field_missing",
        "unknown_validated_artifact_id",
        "invalid_validation_method",
        "validated_artifacts_without_validation_method",
        "not_applicable_status_mismatch",
        "not_applicable_requires_no_types",
        "not_applicable_requires_no_validated_artifacts",
        "deferred_policy_status_mismatch",
        "status_policy_mismatch",
        "validated_artifacts_required",
        "validated_artifact_not_verified",
    }
    insufficient_codes = {"missing_required_artifact_types"}

    invalid_issues = [issue for issue in issues if issue.code in invalid_codes]
    insufficient_issues = [issue for issue in issues if issue.code in insufficient_codes]

    is_valid = not invalid_issues
    is_sufficient = False
    if is_valid:
        if policy == "advisory_only":
            is_sufficient = True
        elif policy == "not_applicable":
            # Structurally valid not_applicable evidence must not be treated as an
            # implicit authorization for completion. Later verification policy still
            # has to decide what completion means for that task type.
            is_sufficient = False
        elif policy == "required":
            is_sufficient = status == "satisfied" and not insufficient_issues
        elif policy == "deferred":
            is_sufficient = False

    return CompletionEvidenceValidationResult(
        is_valid=is_valid,
        is_sufficient=is_sufficient,
        artifact_results=artifact_results,
        issues=tuple(issues),
        validated_artifact_ids=validated_artifact_ids,
        missing_required_artifact_types=missing_required_artifact_types,
        unknown_validated_artifact_ids=unknown_validated_artifact_ids,
    )


def assert_valid_completion_evidence(
    artifacts: list[dict[str, Any]],
    completion_evidence: dict[str, Any],
) -> CompletionEvidenceValidationResult:
    """Raise if completion evidence is malformed or contradictory."""

    result = validate_completion_evidence(artifacts, completion_evidence)
    if not result.is_valid:
        joined = "; ".join(f"{issue.path} {issue.message}" for issue in result.issues)
        raise CompletionEvidenceValidationError(f"Invalid completion evidence: {joined}")
    return result


def validate_task_evidence(task_envelope: dict[str, Any]) -> CompletionEvidenceValidationResult:
    """Validate the artifact/evidence surface attached to a TaskEnvelope."""

    artifacts = task_envelope.get("artifacts", {}).get("items", [])
    completion_evidence = task_envelope.get("artifacts", {}).get("completion_evidence", {})
    return validate_completion_evidence(artifacts, completion_evidence)


__all__ = [
    "ArtifactValidationError",
    "ArtifactValidationResult",
    "CompletionEvidenceValidationError",
    "CompletionEvidenceValidationResult",
    "EvidenceValidationError",
    "ValidationIssue",
    "assert_valid_artifact_record",
    "assert_valid_completion_evidence",
    "validate_artifact_record",
    "validate_completion_evidence",
    "validate_task_evidence",
]
