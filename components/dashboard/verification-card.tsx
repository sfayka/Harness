import type { CompletionValidationSummary, VerificationSummary } from "@/lib/types";
import { getEvidenceSeverity, getSeverityClasses, getVerificationSeverity } from "@/lib/outcome-severity";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { VerificationBadge } from "@/components/ui/status-badge";
import { formatDateTime } from "@/lib/utils";
import { ShieldCheck, CheckCircle2, XCircle, FileSearch } from "lucide-react";

interface VerificationCardProps {
  summary: VerificationSummary | null;
  completionValidation?: CompletionValidationSummary | null;
}

export function completionAcceptedForDisplay(
  summary: VerificationSummary | null,
  completionValidation?: CompletionValidationSummary | null,
): boolean {
  if (completionValidation) {
    return completionValidation.completion_accepted;
  }
  return Boolean(summary?.verification_passed ?? summary?.completion_accepted);
}

export function VerificationCard({ summary, completionValidation }: VerificationCardProps) {
  if (!summary) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <ShieldCheck className="h-4 w-4 text-muted-foreground" />
              Verification
            </CardTitle>
            <VerificationBadge status={null} />
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            <p className="text-sm text-muted-foreground">
              No verification evaluation has been performed yet.
            </p>
            {completionValidation && (
              <p className="text-sm text-foreground">
                {completionValidation.summary}
              </p>
            )}
          </div>
        </CardContent>
      </Card>
    );
  }

  const decisionSeverity = getSeverityClasses(getVerificationSeverity(summary.result));
  const evidenceSeverity = getSeverityClasses(
    getEvidenceSeverity(
      summary.evidence_is_sufficient ?? summary.evidence_sufficient ?? null,
    ),
  );
  const completionAccepted = completionAcceptedForDisplay(summary, completionValidation);

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-muted-foreground" />
            Verification
          </CardTitle>
          <VerificationBadge status={summary.result} />
        </div>
      </CardHeader>
      <CardContent>
        <div className="space-y-3">
          {completionValidation && (
            <div className="rounded-md border border-border bg-muted/30 p-3">
              <p className="text-xs font-medium uppercase tracking-normal text-muted-foreground">
                Completion validation
              </p>
              <p className="mt-1 text-sm text-foreground">
                {completionValidation.summary}
              </p>
              <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                <span>Intent: {completionValidation.intent_status.replaceAll("_", " ")}</span>
                <span>Evidence: {completionValidation.evidence_status.replaceAll("_", " ")}</span>
                <span>Claimed: {completionValidation.completion_claimed ? "yes" : "no"}</span>
                <span>Accepted: {completionValidation.completion_accepted ? "yes" : "no"}</span>
              </div>
            </div>
          )}

          {/* Key indicators */}
          <div className="flex items-center gap-4 text-sm">
            <div className="flex items-center gap-1.5">
              {completionAccepted ? (
                <CheckCircle2 className={`h-4 w-4 ${decisionSeverity.text}`} />
              ) : (
                <XCircle className={`h-4 w-4 ${decisionSeverity.text}`} />
              )}
              <span className="text-muted-foreground">
                Completion {completionAccepted ? "Accepted" : "Not Accepted"}
              </span>
            </div>
            <div className="flex items-center gap-1.5">
              {(summary.evidence_is_sufficient ?? summary.evidence_sufficient) ? (
                <FileSearch className={`h-4 w-4 ${evidenceSeverity.text}`} />
              ) : (
                <FileSearch className={`h-4 w-4 ${evidenceSeverity.text}`} />
              )}
              <span className="text-muted-foreground">
                Evidence {(summary.evidence_is_sufficient ?? summary.evidence_sufficient) ? "Sufficient" : "Insufficient"}
              </span>
            </div>
          </div>

          {/* Reasons */}
          {summary.reasons.length > 0 && (
            <div>
              <p className="text-xs text-muted-foreground mb-1">Reasons:</p>
              <ul className="space-y-1">
                {summary.reasons.map((reason, index) => (
                  <li
                    key={index}
                    className="text-sm text-foreground flex items-start gap-2"
                  >
                    <span className="text-muted-foreground">-</span>
                    {reason}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Timestamp */}
          <p className="text-xs text-muted-foreground">
            Evaluated at {formatDateTime(summary.evaluated_at)}
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
