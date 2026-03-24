"""Minimal public evaluation entry point for Harness control-plane cases."""

from __future__ import annotations

from dataclasses import dataclass

from modules.contracts.task_envelope_end_to_end import (
    CanonicalCaseInput,
    CanonicalExternalFactBundle,
    enforce_canonical_task_case,
)
from modules.contracts.task_envelope_enforcement import EnforcementAction, EnforcementResult
from modules.contracts.task_envelope_review import ReviewDecisionResult, ReviewRequest
from modules.contracts.task_envelope_validation import assert_valid_task_envelope
from modules.contracts.task_envelope_verification import RuntimeVerificationFacts

TaskEnvelope = dict[str, object]


@dataclass(frozen=True)
class HarnessEvaluationRequest:
    """Stable top-level input surface for evaluating one canonical task case."""

    task_envelope: TaskEnvelope
    external_facts: CanonicalExternalFactBundle | None = None
    claimed_completion: bool = False
    acceptance_criteria_satisfied: bool = False
    runtime_facts: RuntimeVerificationFacts = RuntimeVerificationFacts()
    unresolved_conditions: tuple[str, ...] = ()
    review_reasons: tuple[str, ...] = ()
    review_request: ReviewRequest | None = None
    review_decision: ReviewDecisionResult | None = None


@dataclass(frozen=True)
class HarnessEvaluationResult:
    """Stable top-level output surface for Harness evaluation callers."""

    action: EnforcementAction
    target_status: str | None
    task_envelope: TaskEnvelope
    enforcement_result: EnforcementResult
    accepted_completion: bool
    requires_review: bool
    invalid_input: bool
    reasons: tuple[str, ...]
    error: str | None


class HarnessEvaluator:
    """Minimal callable service object for control-plane evaluation."""

    def evaluate(self, request: HarnessEvaluationRequest) -> HarnessEvaluationResult:
        """Evaluate one canonical TaskEnvelope case through the integrated control plane."""

        assert_valid_task_envelope(request.task_envelope)

        enforcement_result = enforce_canonical_task_case(
            request.task_envelope,
            case_input=CanonicalCaseInput(
                claimed_completion=request.claimed_completion,
                acceptance_criteria_satisfied=request.acceptance_criteria_satisfied,
                runtime_facts=request.runtime_facts,
                external_facts=request.external_facts,
                unresolved_conditions=request.unresolved_conditions,
                review_reasons=request.review_reasons,
                review_request=request.review_request,
                review_decision=request.review_decision,
            ),
        )

        verification_result = enforcement_result.verification_result
        return HarnessEvaluationResult(
            action=enforcement_result.action,
            target_status=enforcement_result.target_status,
            task_envelope=enforcement_result.task_envelope,
            enforcement_result=enforcement_result,
            accepted_completion=bool(verification_result and verification_result.accepted_completion),
            requires_review=bool(verification_result and verification_result.requires_review),
            invalid_input=enforcement_result.action == EnforcementAction.INVALID_INPUT,
            reasons=enforcement_result.reasons,
            error=enforcement_result.error,
        )


def evaluate_task_case(request: HarnessEvaluationRequest) -> HarnessEvaluationResult:
    """Evaluate a canonical task case through Harness's minimal public entry point."""

    return HarnessEvaluator().evaluate(request)


__all__ = [
    "HarnessEvaluationRequest",
    "HarnessEvaluationResult",
    "HarnessEvaluator",
    "evaluate_task_case",
]
