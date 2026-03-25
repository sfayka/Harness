import type { ReconciliationSummary } from "@/lib/types";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { ReconciliationBadge } from "@/components/ui/status-badge";
import { formatDateTime } from "@/lib/utils";
import {
  GitCompare,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  AlertCircle,
  Minus,
} from "lucide-react";

interface ReconciliationCardProps {
  summary: ReconciliationSummary | null;
}

// Determine if a system state indicates a problem
function getSystemStatus(
  state: string | null,
  hasMismatch: boolean
): "ok" | "missing" | "mismatch" | "unknown" {
  if (!state || state === "-") return "missing";
  if (hasMismatch) return "mismatch";

  const okStates = [
    "done",
    "completed",
    "merged",
    "closed",
    "resolved",
    "accepted",
  ];
  const lowerState = state.toLowerCase();
  if (okStates.some((s) => lowerState.includes(s))) return "ok";

  return "unknown";
}

// Check if this system is mentioned in mismatches
function systemHasMismatch(system: string, mismatches: string[]): boolean {
  const lowerSystem = system.toLowerCase();
  return mismatches.some((m) => m.toLowerCase().includes(lowerSystem));
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

  const hasMismatches = summary.mismatches.length > 0;
  const isContradictory =
    summary.result === "contradictory_facts" ||
    summary.result === "wrong_target";

  const systems = [
    {
      name: "Linear",
      state: summary.linear_state,
      hasMismatch: systemHasMismatch("linear", summary.mismatches),
    },
    {
      name: "GitHub",
      state: summary.github_state,
      hasMismatch: systemHasMismatch("github", summary.mismatches),
    },
    {
      name: "Harness",
      state: summary.harness_state,
      hasMismatch: systemHasMismatch("harness", summary.mismatches),
    },
  ];

  return (
    <Card
      className={
        isContradictory
          ? "border-destructive/50 bg-destructive/5"
          : hasMismatches
            ? "border-warning/50 bg-warning/5"
            : ""
      }
    >
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
          {/* System States - with tension indicators */}
          <div className="space-y-1.5">
            {systems.map((system) => {
              const status = getSystemStatus(system.state, system.hasMismatch);

              const statusStyles = {
                ok: {
                  bg: "bg-success/10 border-success/30",
                  icon: CheckCircle2,
                  iconColor: "text-success",
                  stateColor: "text-success",
                },
                missing: {
                  bg: "bg-destructive/10 border-destructive/30",
                  icon: XCircle,
                  iconColor: "text-destructive",
                  stateColor: "text-destructive",
                },
                mismatch: {
                  bg: "bg-warning/10 border-warning/30",
                  icon: AlertCircle,
                  iconColor: "text-warning",
                  stateColor: "text-warning",
                },
                unknown: {
                  bg: "bg-muted/50 border-border",
                  icon: Minus,
                  iconColor: "text-muted-foreground",
                  stateColor: "text-foreground",
                },
              };

              const style = statusStyles[status];
              const Icon = style.icon;

              return (
                <div
                  key={system.name}
                  className={`flex items-center justify-between p-2.5 rounded-lg border ${style.bg}`}
                >
                  <div className="flex items-center gap-2">
                    <Icon className={`h-4 w-4 ${style.iconColor}`} />
                    <span className="text-sm font-medium">{system.name}</span>
                  </div>
                  <span className={`font-mono text-sm ${style.stateColor}`}>
                    {system.state || "no data"}
                  </span>
                </div>
              );
            })}
          </div>

          {/* Contradiction Banner */}
          {isContradictory && (
            <div className="flex items-center gap-2 p-3 rounded-lg bg-destructive/20 border border-destructive/40">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-destructive/30">
                <AlertTriangle className="h-4 w-4 text-destructive" />
              </div>
              <div>
                <p className="text-sm font-semibold text-destructive">
                  Systems Disagree
                </p>
                <p className="text-xs text-destructive/80">
                  Truth cannot be established - human review required
                </p>
              </div>
            </div>
          )}

          {/* Mismatch Details */}
          {hasMismatches && !isContradictory && (
            <div className="p-2.5 rounded-lg bg-warning/10 border border-warning/30">
              <div className="flex items-center gap-1.5 mb-1.5">
                <AlertTriangle className="h-3.5 w-3.5 text-warning" />
                <span className="text-xs font-semibold text-warning">
                  Mismatches Detected
                </span>
              </div>
              <ul className="space-y-1">
                {summary.mismatches.map((mismatch, index) => (
                  <li
                    key={index}
                    className="text-xs text-foreground flex items-start gap-1.5"
                  >
                    <span className="text-warning mt-0.5">-</span>
                    {mismatch}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* All Aligned Banner */}
          {!hasMismatches && summary.result === "no_mismatch" && (
            <div className="flex items-center gap-2 p-2.5 rounded-lg bg-success/10 border border-success/30">
              <CheckCircle2 className="h-4 w-4 text-success" />
              <span className="text-sm font-medium text-success">
                All systems aligned
              </span>
            </div>
          )}

          {/* Timestamp */}
          <p className="text-xs text-muted-foreground pt-1">
            Evaluated {formatDateTime(summary.evaluated_at)}
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
