import { cn } from "@/lib/utils";
import type {
  TaskStatus,
  VerificationStatus,
  ReconciliationStatus,
  ReviewStatus,
  Priority,
} from "@/lib/types";

interface StatusBadgeProps {
  status: string;
  variant?: "task" | "verification" | "reconciliation" | "review" | "priority";
  size?: "sm" | "md";
  className?: string;
}

const taskStatusConfig: Record<
  TaskStatus,
  { label: string; className: string }
> = {
  intake_ready: {
    label: "Intake Ready",
    className: "bg-muted text-muted-foreground",
  },
  planned: {
    label: "Planned",
    className: "bg-info/15 text-info",
  },
  dispatch_ready: {
    label: "Dispatch Ready",
    className: "bg-info/15 text-info",
  },
  assigned: {
    label: "Assigned",
    className: "bg-info/15 text-info",
  },
  executing: {
    label: "Executing",
    className: "bg-warning/15 text-warning",
  },
  blocked: {
    label: "Blocked",
    className: "bg-destructive/15 text-destructive",
  },
  completed: {
    label: "Completed",
    className: "bg-success/15 text-success",
  },
  failed: {
    label: "Failed",
    className: "bg-destructive/15 text-destructive",
  },
  canceled: {
    label: "Canceled",
    className: "bg-muted text-muted-foreground",
  },
};

const verificationStatusConfig: Record<
  VerificationStatus,
  { label: string; className: string }
> = {
  accepted: {
    label: "Accepted",
    className: "bg-success/15 text-success",
  },
  insufficient_evidence: {
    label: "Insufficient",
    className: "bg-warning/15 text-warning",
  },
  deferred: {
    label: "Deferred",
    className: "bg-muted text-muted-foreground",
  },
  pending: {
    label: "Pending",
    className: "bg-info/15 text-info",
  },
  rejected: {
    label: "Rejected",
    className: "bg-destructive/15 text-destructive",
  },
};

const reconciliationStatusConfig: Record<
  ReconciliationStatus,
  { label: string; className: string }
> = {
  no_mismatch: {
    label: "Aligned",
    className: "bg-success/15 text-success",
  },
  wrong_target: {
    label: "Wrong Target",
    className: "bg-destructive/15 text-destructive",
  },
  contradictory_facts: {
    label: "Contradictory",
    className: "bg-destructive/15 text-destructive",
  },
  stale_evidence: {
    label: "Stale",
    className: "bg-warning/15 text-warning",
  },
  pending: {
    label: "Pending",
    className: "bg-info/15 text-info",
  },
};

const reviewStatusConfig: Record<
  ReviewStatus,
  { label: string; className: string }
> = {
  none: {
    label: "No Review",
    className: "bg-muted text-muted-foreground",
  },
  requested: {
    label: "Review Required",
    className: "bg-warning/15 text-warning",
  },
  resolved: {
    label: "Reviewed",
    className: "bg-success/15 text-success",
  },
};

const priorityConfig: Record<Priority, { label: string; className: string }> = {
  critical: {
    label: "Critical",
    className: "bg-destructive/15 text-destructive",
  },
  high: {
    label: "High",
    className: "bg-warning/15 text-warning",
  },
  normal: {
    label: "Normal",
    className: "bg-muted text-muted-foreground",
  },
  low: {
    label: "Low",
    className: "bg-muted text-muted-foreground",
  },
  backlog: {
    label: "Backlog",
    className: "bg-muted text-muted-foreground",
  },
};

export function StatusBadge({
  status,
  variant = "task",
  size = "sm",
  className,
}: StatusBadgeProps) {
  let config: { label: string; className: string } | undefined;

  switch (variant) {
    case "task":
      config = taskStatusConfig[status as TaskStatus];
      break;
    case "verification":
      config = verificationStatusConfig[status as VerificationStatus];
      break;
    case "reconciliation":
      config = reconciliationStatusConfig[status as ReconciliationStatus];
      break;
    case "review":
      config = reviewStatusConfig[status as ReviewStatus];
      break;
    case "priority":
      config = priorityConfig[status as Priority];
      break;
  }

  if (!config) {
    config = { label: status, className: "bg-muted text-muted-foreground" };
  }

  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md font-medium",
        size === "sm" ? "px-2 py-0.5 text-xs" : "px-2.5 py-1 text-sm",
        config.className,
        className
      )}
    >
      {config.label}
    </span>
  );
}

// Specialized badge for showing verification status with icon
export function VerificationBadge({
  status,
  className,
}: {
  status: VerificationStatus | null;
  className?: string;
}) {
  if (!status) {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium bg-muted text-muted-foreground",
          className
        )}
      >
        <span className="h-1.5 w-1.5 rounded-full bg-current opacity-50" />
        Not Evaluated
      </span>
    );
  }

  const config = verificationStatusConfig[status];
  const dotColor =
    status === "accepted"
      ? "bg-success"
      : status === "rejected" || status === "insufficient_evidence"
        ? "bg-destructive"
        : status === "pending"
          ? "bg-info"
          : "bg-muted-foreground";

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium",
        config.className,
        className
      )}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", dotColor)} />
      {config.label}
    </span>
  );
}

// Specialized badge for reconciliation with indicator
export function ReconciliationBadge({
  status,
  className,
}: {
  status: ReconciliationStatus | null;
  className?: string;
}) {
  if (!status) {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium bg-muted text-muted-foreground",
          className
        )}
      >
        <span className="h-1.5 w-1.5 rounded-full bg-current opacity-50" />
        Not Reconciled
      </span>
    );
  }

  const config = reconciliationStatusConfig[status];
  const dotColor =
    status === "no_mismatch"
      ? "bg-success"
      : status === "wrong_target" || status === "contradictory_facts"
        ? "bg-destructive"
        : status === "stale_evidence"
          ? "bg-warning"
          : "bg-info";

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium",
        config.className,
        className
      )}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", dotColor)} />
      {config.label}
    </span>
  );
}

// Combined Truth State indicator - groups verification & reconciliation
export function TruthStateBadge({
  verificationStatus,
  reconciliationStatus,
  className,
}: {
  verificationStatus: VerificationStatus | null;
  reconciliationStatus: ReconciliationStatus | null;
  className?: string;
}) {
  const verificationConfig = verificationStatus
    ? verificationStatusConfig[verificationStatus]
    : null;
  const reconciliationConfig = reconciliationStatus
    ? reconciliationStatusConfig[reconciliationStatus]
    : null;

  // Determine overall truth state
  const isVerified = verificationStatus === "accepted";
  const isAligned = reconciliationStatus === "no_mismatch";
  const hasIssue =
    verificationStatus === "rejected" ||
    reconciliationStatus === "wrong_target" ||
    reconciliationStatus === "contradictory_facts";
  const needsAttention =
    verificationStatus === "insufficient_evidence" ||
    reconciliationStatus === "stale_evidence";

  const containerClass = hasIssue
    ? "border-destructive/30 bg-destructive/5"
    : needsAttention
      ? "border-warning/30 bg-warning/5"
      : isVerified && isAligned
        ? "border-success/30 bg-success/5"
        : "border-border bg-muted/30";

  return (
    <div
      className={cn(
        "inline-flex items-center gap-1 rounded-lg border px-2 py-1.5",
        containerClass,
        className
      )}
    >
      {/* Verification */}
      <span
        className={cn(
          "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium",
          verificationConfig?.className ?? "bg-muted text-muted-foreground"
        )}
      >
        <span
          className={cn(
            "h-1.5 w-1.5 rounded-full",
            verificationStatus === "accepted"
              ? "bg-success"
              : verificationStatus === "rejected"
                ? "bg-destructive"
                : verificationStatus === "insufficient_evidence"
                  ? "bg-warning"
                  : verificationStatus === "pending"
                    ? "bg-info"
                    : "bg-muted-foreground/50"
          )}
        />
        {verificationConfig?.label ?? "Unverified"}
      </span>

      <span className="text-muted-foreground/40 text-xs">|</span>

      {/* Reconciliation */}
      <span
        className={cn(
          "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium",
          reconciliationConfig?.className ?? "bg-muted text-muted-foreground"
        )}
      >
        <span
          className={cn(
            "h-1.5 w-1.5 rounded-full",
            reconciliationStatus === "no_mismatch"
              ? "bg-success"
              : reconciliationStatus === "wrong_target" ||
                  reconciliationStatus === "contradictory_facts"
                ? "bg-destructive"
                : reconciliationStatus === "stale_evidence"
                  ? "bg-warning"
                  : reconciliationStatus === "pending"
                    ? "bg-info"
                    : "bg-muted-foreground/50"
          )}
        />
        {reconciliationConfig?.label ?? "Unreconciled"}
      </span>
    </div>
  );
}
