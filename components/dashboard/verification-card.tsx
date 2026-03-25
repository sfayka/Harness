import type { VerificationSummary } from "@/lib/types";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { VerificationBadge } from "@/components/ui/status-badge";
import { formatDateTime } from "@/lib/utils";
import { ShieldCheck, CheckCircle2, XCircle, FileSearch } from "lucide-react";

interface VerificationCardProps {
  summary: VerificationSummary | null;
}

export function VerificationCard({ summary }: VerificationCardProps) {
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
          <p className="text-sm text-muted-foreground">
            No verification evaluation has been performed yet.
          </p>
        </CardContent>
      </Card>
    );
  }

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
          {/* Key indicators */}
          <div className="flex items-center gap-4 text-sm">
            <div className="flex items-center gap-1.5">
              {summary.completion_accepted ? (
                <CheckCircle2 className="h-4 w-4 text-success" />
              ) : (
                <XCircle className="h-4 w-4 text-destructive" />
              )}
              <span className="text-muted-foreground">
                Completion {summary.completion_accepted ? "Accepted" : "Not Accepted"}
              </span>
            </div>
            <div className="flex items-center gap-1.5">
              {summary.evidence_sufficient ? (
                <FileSearch className="h-4 w-4 text-success" />
              ) : (
                <FileSearch className="h-4 w-4 text-warning" />
              )}
              <span className="text-muted-foreground">
                Evidence {summary.evidence_sufficient ? "Sufficient" : "Insufficient"}
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
