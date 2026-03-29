import { cn } from "@/lib/utils";
import {
  getPrioritySeverity,
  getReconciliationSeverity,
  getReviewSeverity,
  getSeverityClasses,
  getTaskStatusSeverity,
  getVerificationSeverity,
} from "@/lib/outcome-severity";
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
  { label: string }
> = {
  intake_ready: {
    label: "Intake Ready",
  },
  planned: {
    label: "Planned",
  },
  dispatch_ready: {
    label: "Dispatch Ready",
  },
  assigned: {
    label: "Assigned",
  },
  executing: {
    label: "Executing",
  },
  blocked: {
    label: "Blocked",
  },
  in_review: {
    label: "In Review",
  },
  completed: {
    label: "Completed",
  },
  failed: {
    label: "Failed",
  },
  canceled: {
    label: "Canceled",
  },
};

const verificationStatusConfig: Record<
  VerificationStatus,
  { label: string }
> = {
  accepted: {
    label: "Accepted",
  },
  insufficient_evidence: {
    label: "Insufficient",
  },
  deferred: {
    label: "Deferred",
  },
  pending: {
    label: "Pending",
  },
  rejected: {
    label: "Rejected",
  },
};

const reconciliationStatusConfig: Record<
  ReconciliationStatus,
  { label: string }
> = {
  no_mismatch: {
    label: "Aligned",
  },
  wrong_target: {
    label: "Wrong Target",
  },
  contradictory_facts: {
    label: "Contradictory",
  },
  stale_evidence: {
    label: "Stale",
  },
  pending: {
    label: "Pending",
  },
};

const reviewStatusConfig: Record<
  ReviewStatus,
  { label: string }
> = {
  none: {
    label: "No Review",
  },
  requested: {
    label: "Review Required",
  },
  resolved: {
    label: "Reviewed",
  },
};

const priorityConfig: Record<Priority, { label: string }> = {
  critical: {
    label: "Critical",
  },
  high: {
    label: "High",
  },
  normal: {
    label: "Normal",
  },
  low: {
    label: "Low",
  },
  backlog: {
    label: "Backlog",
  },
};

export function StatusBadge({
  status,
  variant = "task",
  size = "sm",
  className,
}: StatusBadgeProps) {
  let config: { label: string } | undefined;
  let severity = getSeverityClasses("neutral");

  switch (variant) {
    case "task":
      config = taskStatusConfig[status as TaskStatus];
      severity = getSeverityClasses(getTaskStatusSeverity(status as TaskStatus));
      break;
    case "verification":
      config = verificationStatusConfig[status as VerificationStatus];
      severity = getSeverityClasses(
        getVerificationSeverity(status as VerificationStatus),
      );
      break;
    case "reconciliation":
      config = reconciliationStatusConfig[status as ReconciliationStatus];
      severity = getSeverityClasses(
        getReconciliationSeverity(status as ReconciliationStatus),
      );
      break;
    case "review":
      config = reviewStatusConfig[status as ReviewStatus];
      severity = getSeverityClasses(getReviewSeverity(status as ReviewStatus));
      break;
    case "priority":
      config = priorityConfig[status as Priority];
      severity = getSeverityClasses(getPrioritySeverity(status as Priority));
      break;
  }

  if (!config) {
    config = { label: status };
    severity = getSeverityClasses("neutral");
  }

  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md font-medium",
        size === "sm" ? "px-2 py-0.5 text-xs" : "px-2.5 py-1 text-sm",
        severity.soft,
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
    const severity = getSeverityClasses("neutral");
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium",
          severity.soft,
          className
        )}
      >
        <span className={cn("h-1.5 w-1.5 rounded-full opacity-50", severity.dot)} />
        Not Evaluated
      </span>
    );
  }

  const config = verificationStatusConfig[status];
  const severity = getSeverityClasses(getVerificationSeverity(status));

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium",
        severity.soft,
        className
      )}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", severity.dot)} />
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
    const severity = getSeverityClasses("neutral");
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium",
          severity.soft,
          className
        )}
      >
        <span className={cn("h-1.5 w-1.5 rounded-full opacity-50", severity.dot)} />
        Not Reconciled
      </span>
    );
  }

  const config = reconciliationStatusConfig[status];
  const severity = getSeverityClasses(getReconciliationSeverity(status));

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium",
        severity.soft,
        className
      )}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", severity.dot)} />
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
  const verificationSeverity = getSeverityClasses(
    getVerificationSeverity(verificationStatus),
  );
  const reconciliationSeverity = getSeverityClasses(
    getReconciliationSeverity(reconciliationStatus),
  );

  const containerSeverity =
    verificationStatus === "accepted" && reconciliationStatus === "no_mismatch"
      ? "success"
      : verificationStatus === "rejected"
        ? "failure"
        : verificationStatus === "insufficient_evidence" ||
            reconciliationStatus === "wrong_target" ||
            reconciliationStatus === "contradictory_facts" ||
            reconciliationStatus === "stale_evidence" ||
            reconciliationStatus === "pending"
          ? "warning"
          : "neutral";
  const containerClass = getSeverityClasses(containerSeverity).border;

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
          verificationConfig ? verificationSeverity.soft : getSeverityClasses("neutral").soft
        )}
      >
        <span
          className={cn(
            "h-1.5 w-1.5 rounded-full",
            verificationConfig ? verificationSeverity.dot : "bg-muted-foreground/50"
          )}
        />
        {verificationConfig?.label ?? "Unverified"}
      </span>

      <span className="text-muted-foreground/40 text-xs">|</span>

      {/* Reconciliation */}
      <span
        className={cn(
          "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium",
          reconciliationConfig
            ? reconciliationSeverity.soft
            : getSeverityClasses("neutral").soft
        )}
      >
        <span
          className={cn(
            "h-1.5 w-1.5 rounded-full",
            reconciliationConfig
              ? reconciliationSeverity.dot
              : "bg-muted-foreground/50"
          )}
        />
        {reconciliationConfig?.label ?? "Unreconciled"}
      </span>
    </div>
  );
}
