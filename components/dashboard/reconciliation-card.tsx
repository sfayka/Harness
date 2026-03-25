import type { EvidenceSummary, ReconciliationSummary, TimelineEvent } from "@/lib/types";
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
  evidence?: EvidenceSummary | null;
  timeline?: TimelineEvent[];
  currentStatus?: string | null;
}

function systemHasMismatch(system: string, mismatches: string[]): boolean {
  const lowerSystem = system.toLowerCase();
  return mismatches.some((m) => m.toLowerCase().includes(lowerSystem));
}

function inferGithubState(
  evidence?: EvidenceSummary | null,
  timeline?: TimelineEvent[],
): string | null {
  const artifactTypeCounts = evidence?.artifact_type_counts ?? {};
  const githubArtifactCount =
    Number(artifactTypeCounts.pull_request ?? 0) +
    Number(artifactTypeCounts.commit ?? 0) +
    Number(artifactTypeCounts.branch ?? 0) +
    Number(artifactTypeCounts.changed_file ?? 0);

  if (githubArtifactCount > 0) {
    const validatedCount = Number(evidence?.validated_artifact_count ?? 0);
    return validatedCount > 0 ? `${validatedCount} validated artifact${validatedCount === 1 ? "" : "s"}` : `${githubArtifactCount} artifact${githubArtifactCount === 1 ? "" : "s"}`;
  }

  const timelineHasGithubArtifact = (timeline ?? []).some(
    (event) =>
      event.event_type === "artifact_captured" &&
      ((event.source?.toLowerCase() === "github") ||
        typeof event.details.pull_request_number === "number" ||
        typeof event.details.commit_sha === "string"),
  );

  return timelineHasGithubArtifact ? "artifacts present" : null;
}

export function ReconciliationCard({
  summary,
  evidence,
  timeline,
  currentStatus,
}: ReconciliationCardProps) {
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

  const mismatchCategories = summary.mismatch_categories ?? [];
  const mismatchReasons = summary.mismatches ?? [];
  const hasMismatches = mismatchCategories.length > 0;
  const isContradictory =
    summary.outcome === "contradictory_facts" ||
    summary.outcome === "wrong_target" ||
    summary.outcome === "terminal_invalid";

  const systems = [
    {
      name: "Linear",
      state: summary.status ?? summary.linear_state,
      status: hasMismatches && systemHasMismatch("linear", mismatchCategories) ? "mismatch" : summary.status === "passed" ? "ok" : "unknown",
    },
    {
      name: "GitHub",
      state: summary.github_state ?? inferGithubState(evidence, timeline),
      status: hasMismatches && systemHasMismatch("github", mismatchCategories) ? "mismatch" : inferGithubState(evidence, timeline) ? "ok" : "missing",
    },
    {
      name: "Harness",
      state: currentStatus ?? summary.harness_state,
      status: hasMismatches && systemHasMismatch("harness", mismatchCategories) ? "mismatch" : (currentStatus ?? summary.harness_state) ? "ok" : "unknown",
    },
  ] as const;

  const statusStyles = {
    ok: {
      bg: "bg-success/10 border-success/30",
      icon: CheckCircle2,
      iconColor: "text-success",
      stateColor: "text-success",
    },
    missing: {
      bg: "bg-muted/50 border-border",
      icon: Minus,
      iconColor: "text-muted-foreground",
      stateColor: "text-muted-foreground",
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
  } as const;

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
              const style = statusStyles[system.status];
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
                {(mismatchReasons.length > 0 ? mismatchReasons : mismatchCategories).map((mismatch, index) => (
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
          {!hasMismatches && summary.outcome === "no_mismatch" && !summary.blocking && (
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
