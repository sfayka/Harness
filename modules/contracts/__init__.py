"""Shared contract helpers for Harness modules."""

from .task_envelope_evidence import (
    ArtifactValidationError,
    ArtifactValidationResult,
    CompletionEvidenceValidationError,
    CompletionEvidenceValidationResult,
    EvidenceValidationError,
    ValidationIssue,
    assert_valid_artifact_record,
    assert_valid_completion_evidence,
    validate_artifact_record,
    validate_completion_evidence,
    validate_task_evidence,
)
from .task_envelope_lifecycle import (
    ForbiddenTransitionError,
    LifecycleTransitionError,
    TransitionAuthorityError,
    TransitionPreconditionError,
    TransitionResult,
    apply_task_transition,
    validate_task_transition,
)
from .task_envelope_validation import assert_valid_task_envelope, validate_task_envelope

__all__ = [
    "ArtifactValidationError",
    "ArtifactValidationResult",
    "CompletionEvidenceValidationError",
    "CompletionEvidenceValidationResult",
    "EvidenceValidationError",
    "ForbiddenTransitionError",
    "LifecycleTransitionError",
    "TransitionAuthorityError",
    "TransitionPreconditionError",
    "TransitionResult",
    "ValidationIssue",
    "apply_task_transition",
    "assert_valid_artifact_record",
    "assert_valid_completion_evidence",
    "assert_valid_task_envelope",
    "validate_artifact_record",
    "validate_completion_evidence",
    "validate_task_evidence",
    "validate_task_envelope",
    "validate_task_transition",
]
