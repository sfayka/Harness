"""Shared contract helpers for Harness modules."""

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
    "ForbiddenTransitionError",
    "LifecycleTransitionError",
    "TransitionAuthorityError",
    "TransitionPreconditionError",
    "TransitionResult",
    "apply_task_transition",
    "assert_valid_task_envelope",
    "validate_task_envelope",
    "validate_task_transition",
]
