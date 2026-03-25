import type { EvidenceSummary } from "@/lib/types";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { formatDateTime } from "@/lib/utils";
import {
  FileBox,
  GitPullRequest,
  GitCommit,
  FileCode,
  FileText,
  CheckCircle2,
  XCircle,
  Clock,
} from "lucide-react";

interface EvidencePanelProps {
  evidence: EvidenceSummary;
}

export function EvidencePanel({ evidence }: EvidencePanelProps) {
  const { completion_evidence } = evidence;

  const statusConfig = {
    validated: { icon: CheckCircle2, color: "text-success", label: "Validated" },
    insufficient: { icon: XCircle, color: "text-warning", label: "Insufficient" },
    pending: { icon: Clock, color: "text-info", label: "Pending" },
    awaiting: { icon: Clock, color: "text-muted-foreground", label: "Awaiting" },
    missing: { icon: XCircle, color: "text-destructive", label: "Missing" },
  };

  const status =
    statusConfig[completion_evidence.status as keyof typeof statusConfig] ||
    statusConfig.awaiting;

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <FileBox className="h-4 w-4 text-muted-foreground" />
            Evidence
          </CardTitle>
          <div className={`flex items-center gap-1.5 text-xs ${status.color}`}>
            <status.icon className="h-3.5 w-3.5" />
            <span>{status.label}</span>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          {/* Summary Stats */}
          <div className="grid grid-cols-3 gap-2">
            <div className="p-2 rounded-md bg-muted/50 text-center">
              <p className="text-lg font-semibold">{evidence.artifact_count}</p>
              <p className="text-xs text-muted-foreground">Artifacts</p>
            </div>
            <div className="p-2 rounded-md bg-muted/50 text-center">
              <p className="text-lg font-semibold">
                {evidence.validated_artifact_count}
              </p>
              <p className="text-xs text-muted-foreground">Validated</p>
            </div>
            <div className="p-2 rounded-md bg-muted/50 text-center">
              <p className="text-lg font-semibold">
                {evidence.verification_status_counts.verified || 0}
              </p>
              <p className="text-xs text-muted-foreground">Verified</p>
            </div>
          </div>

          {/* Artifact Types Breakdown */}
          {Object.keys(evidence.artifact_type_counts).length > 0 && (
            <div>
              <p className="text-xs text-muted-foreground mb-2">
                Artifact Types
              </p>
              <div className="flex flex-wrap gap-2">
                {Object.entries(evidence.artifact_type_counts).map(
                  ([type, count]) => (
                    <div
                      key={type}
                      className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-muted text-xs"
                    >
                      <ArtifactIcon type={type} />
                      <span className="capitalize">{type.replace("_", " ")}</span>
                      <span className="text-muted-foreground">({count})</span>
                    </div>
                  )
                )}
              </div>
            </div>
          )}

          {/* Completion Evidence Details */}
          <div className="border-t border-border pt-3">
            <p className="text-xs text-muted-foreground mb-2">
              Completion Evidence
            </p>
            <div className="space-y-2 text-sm">
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Policy</span>
                <span className="font-mono text-xs">
                  {completion_evidence.policy || "-"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Method</span>
                <span className="font-mono text-xs">
                  {completion_evidence.validation_method || "-"}
                </span>
              </div>
              {completion_evidence.required_artifact_types.length > 0 && (
                <div>
                  <span className="text-muted-foreground text-xs">Required Types:</span>
                  <div className="flex flex-wrap gap-1 mt-1">
                    {completion_evidence.required_artifact_types.map((type) => (
                      <span
                        key={type}
                        className="px-1.5 py-0.5 rounded bg-muted text-xs font-mono"
                      >
                        {type}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              {completion_evidence.validated_at && (
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Validated At</span>
                  <span className="text-xs">
                    {formatDateTime(completion_evidence.validated_at)}
                  </span>
                </div>
              )}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function ArtifactIcon({ type }: { type: string }) {
  switch (type) {
    case "pull_request":
      return <GitPullRequest className="h-3 w-3" />;
    case "commit":
      return <GitCommit className="h-3 w-3" />;
    case "changed_file":
    case "branch":
      return <FileCode className="h-3 w-3" />;
    default:
      return <FileText className="h-3 w-3" />;
  }
}
