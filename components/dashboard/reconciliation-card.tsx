import type { ReconciliationSummary } from "@/lib/types";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { ReconciliationBadge } from "@/components/ui/status-badge";
import { formatDateTime } from "@/lib/utils";
import { GitCompare, AlertTriangle } from "lucide-react";

interface ReconciliationCardProps {
  summary: ReconciliationSummary | null;
}

export function ReconciliationCard({ summary }: ReconciliationCardProps) {
  if (!summary) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <GitCompare className="h-4 w-4 text-muted-foreground" />
              Reconciliation
            </CardTitle>
            <ReconciliationBadge status={null} />
          </div>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            No reconciliation check has been performed yet.
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
            <GitCompare className="h-4 w-4 text-muted-foreground" />
            Reconciliation
          </CardTitle>
          <ReconciliationBadge status={summary.result} />
        </div>
      </CardHeader>
      <CardContent>
        <div className="space-y-3">
          {/* System States */}
          <div className="grid grid-cols-3 gap-2 text-sm">
            <div className="p-2 rounded-md bg-muted/50">
              <p className="text-xs text-muted-foreground mb-0.5">Linear</p>
              <p className="font-mono text-xs">
                {summary.linear_state || "-"}
              </p>
            </div>
            <div className="p-2 rounded-md bg-muted/50">
              <p className="text-xs text-muted-foreground mb-0.5">GitHub</p>
              <p className="font-mono text-xs">
                {summary.github_state || "-"}
              </p>
            </div>
            <div className="p-2 rounded-md bg-muted/50">
              <p className="text-xs text-muted-foreground mb-0.5">Harness</p>
              <p className="font-mono text-xs">
                {summary.harness_state || "-"}
              </p>
            </div>
          </div>

          {/* Mismatches */}
          {summary.mismatches.length > 0 && (
            <div className="p-2 rounded-md bg-destructive/10 border border-destructive/20">
              <div className="flex items-center gap-1.5 mb-1">
                <AlertTriangle className="h-3.5 w-3.5 text-destructive" />
                <span className="text-xs font-medium text-destructive">
                  Mismatches Detected
                </span>
              </div>
              <ul className="space-y-1">
                {summary.mismatches.map((mismatch, index) => (
                  <li key={index} className="text-xs text-foreground">
                    {mismatch}
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
