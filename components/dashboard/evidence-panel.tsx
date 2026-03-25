import type { EvidenceSummary, TimelineEvent } from "@/lib/types";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { formatDateTime } from "@/lib/utils";
import {
  ShieldCheck,
  GitPullRequest,
  GitCommit,
  FileCode,
  FileText,
  CheckCircle2,
  XCircle,
  Clock,
  ExternalLink,
  AlertCircle,
  FileOutput,
  ScrollText,
} from "lucide-react";

interface EvidencePanelProps {
  evidence: EvidenceSummary;
  timeline?: TimelineEvent[];
}

// Extract artifact details from timeline events
function extractArtifacts(timeline?: TimelineEvent[]) {
  if (!timeline) return [];

  return timeline
    .filter((e) => e.event_type === "artifact_captured")
    .map((e) => ({
      id: typeof e.details.artifact_id === "string" ? e.details.artifact_id : e.event_id,
      type: (e.details.type as string) || "unknown",
      pr_number: e.details.pull_request_number as number | undefined,
      commit_sha: e.details.commit_sha as string | undefined,
      branch: e.details.branch as string | undefined,
      captured_at: e.occurred_at,
      source: e.source,
    }));
}

export function EvidencePanel({ evidence, timeline }: EvidencePanelProps) {
  const { completion_evidence } = evidence;
  const artifacts = extractArtifacts(timeline);

  const statusConfig = {
    satisfied: {
      icon: CheckCircle2,
      color: "text-success",
      bg: "bg-success/10",
      label: "Satisfied",
    },
    insufficient: {
      icon: AlertCircle,
      color: "text-warning",
      bg: "bg-warning/10",
      label: "Insufficient",
    },
    pending: {
      icon: Clock,
      color: "text-info",
      bg: "bg-info/10",
      label: "Pending",
    },
    deferred: {
      icon: Clock,
      color: "text-muted-foreground",
      bg: "bg-muted",
      label: "Deferred",
    },
    not_applicable: {
      icon: FileOutput,
      color: "text-muted-foreground",
      bg: "bg-muted",
      label: "Not Applicable",
    },
  };

  const status =
    statusConfig[completion_evidence.status as keyof typeof statusConfig] ||
    statusConfig.deferred;

  // Check which required types are present
  const presentTypes = new Set(Object.keys(evidence.artifact_type_counts));
  const requiredTypes = completion_evidence.required_artifact_types;

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-muted-foreground" />
            Evidence & Proof
          </CardTitle>
          <div
            className={`flex items-center gap-1.5 text-xs px-2 py-1 rounded-md ${status.bg} ${status.color}`}
          >
            <status.icon className="h-3.5 w-3.5" />
            <span className="font-medium">{status.label}</span>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          {/* Required vs Present - Visual Checklist */}
          {requiredTypes.length > 0 && (
            <div className="rounded-lg border border-border p-3">
              <p className="text-xs font-medium text-foreground mb-2">
                Required Evidence
              </p>
              <div className="space-y-1.5">
                {requiredTypes.map((type) => {
                  const isPresent = presentTypes.has(type);
                  const count = evidence.artifact_type_counts[type] || 0;
                  return (
                    <div
                      key={type}
                      className={`flex items-center justify-between px-2 py-1.5 rounded-md text-sm ${
                        isPresent
                          ? "bg-success/10 border border-success/20"
                          : "bg-destructive/5 border border-destructive/20"
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        {isPresent ? (
                          <CheckCircle2 className="h-4 w-4 text-success" />
                        ) : (
                          <XCircle className="h-4 w-4 text-destructive" />
                        )}
                        <ArtifactIcon type={type} className="h-3.5 w-3.5" />
                        <span className="capitalize font-medium">
                          {type.replace("_", " ")}
                        </span>
                      </div>
                      <span className={`text-xs font-mono ${isPresent ? "text-success" : "text-destructive"}`}>
                        {isPresent ? `${count} present` : "missing"}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Captured Artifacts - The Proof */}
          {artifacts.length > 0 && (
            <div>
              <p className="text-xs font-medium text-foreground mb-2">
                Captured Artifacts
              </p>
              <div className="space-y-2">
                {artifacts.map((artifact) => {
                  const isValidated =
                    completion_evidence.validated_artifact_ids.some((id) =>
                      artifact.id.includes(id.replace("art-", ""))
                    );

                  return (
                    <div
                      key={artifact.id}
                      className={`group relative flex items-center gap-3 p-2.5 rounded-lg border transition-colors ${
                        isValidated
                          ? "border-success/30 bg-success/5 hover:bg-success/10"
                          : "border-border bg-muted/30 hover:bg-muted/50"
                      }`}
                    >
                      {/* Artifact Icon */}
                      <div
                        className={`flex h-9 w-9 items-center justify-center rounded-md ${
                          isValidated ? "bg-success/20" : "bg-muted"
                        }`}
                      >
                        <ArtifactIcon
                          type={artifact.type}
                          className={`h-4 w-4 ${isValidated ? "text-success" : "text-muted-foreground"}`}
                        />
                      </div>

                      {/* Artifact Details */}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium capitalize">
                            {artifact.type.replace("_", " ")}
                          </span>
                          {isValidated && (
                            <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium bg-success/20 text-success">
                              <CheckCircle2 className="h-2.5 w-2.5" />
                              Validated
                            </span>
                          )}
                        </div>

                        {/* Reference Details */}
                        <div className="flex items-center gap-2 mt-0.5">
                          {artifact.pr_number && (
                            <span className="inline-flex items-center gap-1 text-xs font-mono text-muted-foreground hover:text-foreground cursor-pointer">
                              <GitPullRequest className="h-3 w-3" />
                              PR #{artifact.pr_number}
                              <ExternalLink className="h-2.5 w-2.5 opacity-0 group-hover:opacity-100 transition-opacity" />
                            </span>
                          )}
                          {artifact.commit_sha && (
                            <span className="inline-flex items-center gap-1 text-xs font-mono text-muted-foreground hover:text-foreground cursor-pointer">
                              <GitCommit className="h-3 w-3" />
                              {artifact.commit_sha.substring(0, 7)}
                              <ExternalLink className="h-2.5 w-2.5 opacity-0 group-hover:opacity-100 transition-opacity" />
                            </span>
                          )}
                          {artifact.branch && (
                            <span className="inline-flex items-center gap-1 text-xs font-mono text-muted-foreground">
                              <FileCode className="h-3 w-3" />
                              {artifact.branch}
                            </span>
                          )}
                          {!artifact.pr_number &&
                            !artifact.commit_sha &&
                            !artifact.branch && (
                              <span className="text-xs text-muted-foreground">
                                from {artifact.source}
                              </span>
                            )}
                        </div>
                      </div>

                      {/* Timestamp */}
                      <div className="text-[10px] text-muted-foreground">
                        {formatDateTime(artifact.captured_at)}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Empty State */}
          {artifacts.length === 0 && evidence.artifact_count === 0 && (
            <div className="flex flex-col items-center justify-center py-6 text-center">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-muted mb-3">
                <ShieldCheck className="h-6 w-6 text-muted-foreground" />
              </div>
              <p className="text-sm font-medium text-muted-foreground">
                No evidence captured yet
              </p>
              <p className="text-xs text-muted-foreground/70 mt-1">
                Artifacts will appear here as work progresses
              </p>
            </div>
          )}

          {/* Validation Metadata */}
          {(completion_evidence.policy ||
            completion_evidence.validation_method ||
            completion_evidence.validated_at) && (
            <div className="border-t border-border pt-3 mt-3">
              <p className="text-xs text-muted-foreground mb-2">
                Validation Details
              </p>
              <div className="grid grid-cols-2 gap-2 text-xs">
                {completion_evidence.policy && (
                  <div className="flex flex-col">
                    <span className="text-muted-foreground">Policy</span>
                    <span className="font-mono font-medium">
                      {completion_evidence.policy}
                    </span>
                  </div>
                )}
                {completion_evidence.validation_method && (
                  <div className="flex flex-col">
                    <span className="text-muted-foreground">Method</span>
                    <span className="font-mono font-medium">
                      {completion_evidence.validation_method}
                    </span>
                  </div>
                )}
                {completion_evidence.validated_at && (
                  <div className="flex flex-col col-span-2">
                    <span className="text-muted-foreground">Validated</span>
                    <span className="font-medium">
                      {formatDateTime(completion_evidence.validated_at)}
                    </span>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function ArtifactIcon({
  type,
  className = "h-3 w-3",
}: {
  type: string;
  className?: string;
}) {
  switch (type) {
    case "pull_request":
      return <GitPullRequest className={className} />;
    case "commit":
      return <GitCommit className={className} />;
    case "changed_file":
    case "branch":
      return <FileCode className={className} />;
    case "log":
      return <ScrollText className={className} />;
    case "output":
      return <FileOutput className={className} />;
    default:
      return <FileText className={className} />;
  }
}
