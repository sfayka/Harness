"""Integrated TaskEnvelope enforcement flow built from contract primitives."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from modules.contracts.task_envelope_evidence import (
    CompletionEvidenceValidationResult,
    validate_task_evidence,
)
from modules.contracts.task_envelope_lifecycle import (
    LifecycleTransitionError,
    TransitionResult,
    apply_task_transition,
)
from modules.contracts.task_envelope_reconciliation import (
    ReconciliationEvaluationInput,
    ReconciliationResult,
    evaluate_reconciliation,
)
from modules.contracts.task_envelope_review import ReviewDecisionResult, ReviewRequest, validate_review_request
from modules.contracts.task_envelope_validation import assert_valid_task_envelope
from modules.contracts.task_envelope_verification import (
    ReconciliationFacts,
    RuntimeVerificationFacts,
    VerificationDecisionInput,
    VerificationDecisionResult,
    VerificationOutcome,
    evaluate_verification_decision,
)

TaskEnvelope = dict[str, object]


class EnforcementAction(StrEnum):
    """Top-level integrated enforcement actions.

    NO_OP means the control plane evaluated the task and determined that
    nothing should change yet.

    TRANSITION_REJECTED means the flow attempted or was given a concrete
    lifecycle action, but that action failed lifecycle policy enforcement.
    """

    NO_OP = "no_op"
    TRANSITION_APPLIED = "transition_applied"
    REVIEW_REQUIRED = "review_required"
    FOLLOW_UP_AUTHORIZED = "follow_up_authorized"
    TRANSITION_REJECTED = "transition_rejected"
    INVALID_INPUT = "invalid_input"


@dataclass(frozen=True)
class EnforcementInput:
    """Structured input bundle for integrated TaskEnvelope enforcement."""

    claimed_completion: bool = False
    acceptance_criteria_satisfied: bool = False
    runtime_facts: RuntimeVerificationFacts = RuntimeVerificationFacts()
    reconciliation_input: ReconciliationEvaluationInput | None = None
    unresolved_conditions: tuple[str, ...] = ()
    review_reasons: tuple[str, ...] = ()
    review_request: ReviewRequest | None = None
    review_decision: ReviewDecisionResult | None = None


@dataclass(frozen=True)
class EnforcementResult:
    """Integrated enforcement result with auditable intermediate decisions."""

    action: EnforcementAction
    task_envelope: TaskEnvelope
    evidence_result: CompletionEvidenceValidationResult | None
    reconciliation_result: ReconciliationResult | None
    verification_result: VerificationDecisionResult | None
    review_request: ReviewRequest | None
    review_decision: ReviewDecisionResult | None
    transition_result: TransitionResult | None
    target_status: str | None
    reasons: tuple[str, ...]
    error: str | None = None


def _automatic_transition_facts(
    verification_result: VerificationDecisionResult,
    *,
    acceptance_criteria_satisfied: bool,
    reconciliation_result: ReconciliationResult | None,
) -> dict[str, object]:
    facts: dict[str, object] = {
        "acceptance_criteria_satisfied": acceptance_criteria_satisfied,
        "reconciliation_passed": bool(reconciliation_result and not reconciliation_result.blocking),
    }
    if verification_result.outcome == VerificationOutcome.ACCEPTED_COMPLETION:
        facts["verification_passed"] = True
        facts["acceptance_criteria_satisfied"] = True
        facts["reconciliation_passed"] = True
    if verification_result.outcome == VerificationOutcome.TERMINAL_INVALID:
        facts["terminal_failure"] = True
    return facts


def _result_with_error(
    task_envelope: TaskEnvelope,
    *,
    action: EnforcementAction,
    error: Exception,
    evidence_result: CompletionEvidenceValidationResult | None = None,
    reconciliation_result: ReconciliationResult | None = None,
    verification_result: VerificationDecisionResult | None = None,
    review_request: ReviewRequest | None = None,
    review_decision: ReviewDecisionResult | None = None,
) -> EnforcementResult:
    return EnforcementResult(
        action=action,
        task_envelope=task_envelope,
        evidence_result=evidence_result,
        reconciliation_result=reconciliation_result,
        verification_result=verification_result,
        review_request=review_request,
        review_decision=review_decision,
        transition_result=None,
        target_status=None,
        reasons=(str(error),),
        error=str(error),
    )


def _apply_transition(
    task_envelope: TaskEnvelope,
    *,
    actor: str,
    to_status: str,
    reason: str,
    facts: dict[str, object] | None = None,
    evidence_result: CompletionEvidenceValidationResult | None = None,
    reconciliation_result: ReconciliationResult | None = None,
    verification_result: VerificationDecisionResult | None = None,
    review_request: ReviewRequest | None = None,
    review_decision: ReviewDecisionResult | None = None,
) -> EnforcementResult:
    try:
        transition_result = apply_task_transition(
            task_envelope,
            to_status=to_status,
            actor=actor,
            reason=reason,
            facts=facts,
        )
    except LifecycleTransitionError as error:
        # A specific lifecycle change was attempted here, so failure is not a
        # no-op. It is an explicit rejected action that must remain auditable.
        return _result_with_error(
            task_envelope,
            action=EnforcementAction.TRANSITION_REJECTED,
            error=error,
            evidence_result=evidence_result,
            reconciliation_result=reconciliation_result,
            verification_result=verification_result,
            review_request=review_request,
            review_decision=review_decision,
        )

    action = EnforcementAction.FOLLOW_UP_AUTHORIZED if review_decision and review_decision.follow_up_action.value != "none" else EnforcementAction.TRANSITION_APPLIED
    return EnforcementResult(
        action=action,
        task_envelope=transition_result.task_envelope,
        evidence_result=evidence_result,
        reconciliation_result=reconciliation_result,
        verification_result=verification_result,
        review_request=review_request,
        review_decision=review_decision,
        transition_result=transition_result,
        target_status=to_status,
        reasons=(reason,),
    )


def enforce_task_envelope(
    task_envelope: TaskEnvelope,
    *,
    enforcement_input: EnforcementInput,
) -> EnforcementResult:
    """Compose evidence, reconciliation, verification, review, and lifecycle enforcement."""

    try:
        assert_valid_task_envelope(task_envelope)
    except Exception as error:  # pragma: no cover - defensive wrapper
        return _result_with_error(task_envelope, action=EnforcementAction.INVALID_INPUT, error=error)

    evidence_result = validate_task_evidence(task_envelope)
    if not evidence_result.is_valid:
        return _result_with_error(
            task_envelope,
            action=EnforcementAction.INVALID_INPUT,
            error=ValueError("Task evidence is structurally invalid"),
            evidence_result=evidence_result,
        )

    if enforcement_input.review_decision is not None:
        review_decision = enforcement_input.review_decision
        reason = review_decision.record.reasoning
        review_transition_facts = {"terminal_failure": review_decision.record.outcome.value == "mark_failed"}
        if review_decision.recommended_target_status == "completed":
            review_transition_facts.update(
                {
                    "verification_passed": True,
                    "acceptance_criteria_satisfied": True,
                    "reconciliation_passed": True,
                }
            )
        return _apply_transition(
            task_envelope,
            actor="manual_review",
            to_status=review_decision.recommended_target_status,
            reason=reason,
            facts=review_transition_facts,
            evidence_result=evidence_result,
            review_decision=review_decision,
        )

    reconciliation_result: ReconciliationResult | None = None
    if enforcement_input.reconciliation_input is not None:
        try:
            reconciliation_result = evaluate_reconciliation(
                task_envelope,
                reconciliation_input=enforcement_input.reconciliation_input,
            )
        except Exception as error:
            return _result_with_error(
                task_envelope,
                action=EnforcementAction.INVALID_INPUT,
                error=error,
                evidence_result=evidence_result,
            )

    reconciliation_facts = (
        reconciliation_result.to_verification_facts() if reconciliation_result is not None else ReconciliationFacts()
    )

    try:
        verification_result = evaluate_verification_decision(
            task_envelope,
            decision_input=VerificationDecisionInput(
                claimed_completion=enforcement_input.claimed_completion,
                acceptance_criteria_satisfied=enforcement_input.acceptance_criteria_satisfied,
                evidence_result=evidence_result,
                runtime_facts=enforcement_input.runtime_facts,
                reconciliation_facts=reconciliation_facts,
                unresolved_conditions=enforcement_input.unresolved_conditions,
                review_reasons=enforcement_input.review_reasons,
            ),
        )
    except Exception as error:
        return _result_with_error(
            task_envelope,
            action=EnforcementAction.INVALID_INPUT,
            error=error,
            evidence_result=evidence_result,
            reconciliation_result=reconciliation_result,
        )

    if verification_result.outcome == VerificationOutcome.VERIFICATION_DEFERRED:
        # Verification concluded that nothing should move yet. No lifecycle
        # change was attempted, so this remains a true no-op.
        return EnforcementResult(
            action=EnforcementAction.NO_OP,
            task_envelope=task_envelope,
            evidence_result=evidence_result,
            reconciliation_result=reconciliation_result,
            verification_result=verification_result,
            review_request=None,
            review_decision=None,
            transition_result=None,
            target_status=None,
            reasons=verification_result.reasons,
        )

    if verification_result.outcome == VerificationOutcome.REVIEW_REQUIRED:
        review_request = enforcement_input.review_request
        if review_request is not None:
            try:
                validate_review_request(review_request)
            except Exception as error:
                return _result_with_error(
                    task_envelope,
                    action=EnforcementAction.INVALID_INPUT,
                    error=error,
                    evidence_result=evidence_result,
                    reconciliation_result=reconciliation_result,
                    verification_result=verification_result,
                )

        transition_result = None
        transitioned_task = task_envelope
        if verification_result.target_status and task_envelope["status"] != verification_result.target_status:
            try:
                transition_result = apply_task_transition(
                    task_envelope,
                    to_status=verification_result.target_status,
                    actor="verification",
                    reason="; ".join(verification_result.reasons),
                )
            except LifecycleTransitionError as error:
                return _result_with_error(
                    task_envelope,
                    action=EnforcementAction.TRANSITION_REJECTED,
                    error=error,
                    evidence_result=evidence_result,
                    reconciliation_result=reconciliation_result,
                    verification_result=verification_result,
                    review_request=review_request,
                )
            transitioned_task = transition_result.task_envelope

        return EnforcementResult(
            action=EnforcementAction.REVIEW_REQUIRED,
            task_envelope=transitioned_task,
            evidence_result=evidence_result,
            reconciliation_result=reconciliation_result,
            verification_result=verification_result,
            review_request=review_request,
            review_decision=None,
            transition_result=transition_result,
            target_status=verification_result.target_status,
            reasons=verification_result.reasons,
        )

    target_status = verification_result.target_status
    if target_status is None or target_status == task_envelope["status"]:
        # The integrated evaluation produced no lifecycle delta to apply.
        return EnforcementResult(
            action=EnforcementAction.NO_OP,
            task_envelope=task_envelope,
            evidence_result=evidence_result,
            reconciliation_result=reconciliation_result,
            verification_result=verification_result,
            review_request=None,
            review_decision=None,
            transition_result=None,
            target_status=target_status,
            reasons=verification_result.reasons,
        )

    return _apply_transition(
        task_envelope,
        actor="verification",
        to_status=target_status,
        reason="; ".join(verification_result.reasons),
        facts=_automatic_transition_facts(
            verification_result,
            acceptance_criteria_satisfied=enforcement_input.acceptance_criteria_satisfied,
            reconciliation_result=reconciliation_result,
        ),
        evidence_result=evidence_result,
        reconciliation_result=reconciliation_result,
        verification_result=verification_result,
    )


__all__ = [
    "EnforcementAction",
    "EnforcementInput",
    "EnforcementResult",
    "enforce_task_envelope",
]
