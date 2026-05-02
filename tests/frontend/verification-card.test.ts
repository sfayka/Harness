import assert from "node:assert/strict";
import test from "node:test";

import { completionAcceptedForDisplay } from "../../components/dashboard/verification-card";
import type { CompletionValidationSummary, VerificationSummary } from "../../lib/types";

function verificationSummary(overrides: Partial<VerificationSummary>): VerificationSummary {
  return {
    result: "accepted",
    completion_accepted: true,
    verification_passed: true,
    evidence_sufficient: true,
    reasons: [],
    evaluated_at: "2026-05-02T12:00:00Z",
    ...overrides,
  };
}

function completionValidationSummary(
  overrides: Partial<CompletionValidationSummary>,
): CompletionValidationSummary {
  return {
    status: "pending",
    summary: "Completion has not been validated.",
    intent_status: "pending",
    evidence_status: "pending",
    reconciliation_status: "pending",
    completion_claimed: false,
    completion_accepted: false,
    manual_review_status: "none",
    automatic_completion_safe: false,
    verification_outcome: "verification_deferred",
    reasons: [],
    required_criteria_count: 0,
    concrete_required_criteria_count: 0,
    required_artifact_types: [],
    validated_artifact_ids: [],
    validated_artifact_count: 0,
    ...overrides,
  };
}

test("verification card display uses completion validation as acceptance truth", () => {
  const legacyAccepted = verificationSummary({
    completion_accepted: true,
    verification_passed: true,
  });
  const canonicalRejected = completionValidationSummary({
    status: "blocked",
    completion_claimed: true,
    completion_accepted: false,
    evidence_status: "insufficient",
  });

  assert.equal(completionAcceptedForDisplay(legacyAccepted, canonicalRejected), false);
});

test("verification card display falls back to verification summary when validation is absent", () => {
  const legacyAccepted = verificationSummary({
    completion_accepted: true,
    verification_passed: undefined,
  });

  assert.equal(completionAcceptedForDisplay(legacyAccepted, null), true);
});
