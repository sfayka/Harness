import type {
  Priority,
  ReconciliationStatus,
  ReviewStatus,
  TaskStatus,
  VerificationStatus,
} from "@/lib/types";

export type OutcomeSeverity = "success" | "warning" | "failure" | "neutral";

const severityClassMap: Record<
  OutcomeSeverity,
  { soft: string; text: string; dot: string; border: string }
> = {
  success: {
    soft: "bg-success/15 text-success",
    text: "text-success",
    dot: "bg-success",
    border: "border-success/30 bg-success/5",
  },
  warning: {
    soft: "bg-warning/15 text-warning",
    text: "text-warning",
    dot: "bg-warning",
    border: "border-warning/30 bg-warning/5",
  },
  failure: {
    soft: "bg-destructive/15 text-destructive",
    text: "text-destructive",
    dot: "bg-destructive",
    border: "border-destructive/30 bg-destructive/5",
  },
  neutral: {
    soft: "bg-muted text-muted-foreground",
    text: "text-muted-foreground",
    dot: "bg-muted-foreground",
    border: "border-border bg-muted/30",
  },
};

export function getSeverityClasses(severity: OutcomeSeverity) {
  return severityClassMap[severity];
}

export function getTaskStatusSeverity(status: TaskStatus): OutcomeSeverity {
  switch (status) {
    case "completed":
      return "success";
    case "blocked":
    case "failed":
      return "failure";
    case "executing":
      return "warning";
    case "intake_ready":
    case "planned":
    case "dispatch_ready":
    case "assigned":
    case "canceled":
    default:
      return "neutral";
  }
}

export function getVerificationSeverity(
  status: VerificationStatus | null,
): OutcomeSeverity {
  switch (status) {
    case "accepted":
      return "success";
    case "insufficient_evidence":
    case "pending":
      return "warning";
    case "rejected":
      return "failure";
    case "deferred":
    default:
      return "neutral";
  }
}

export function getReconciliationSeverity(
  status: ReconciliationStatus | null,
): OutcomeSeverity {
  switch (status) {
    case "no_mismatch":
      return "success";
    case "wrong_target":
    case "contradictory_facts":
      return "warning";
    case "stale_evidence":
    case "pending":
      return "warning";
    default:
      return "neutral";
  }
}

export function getReviewSeverity(status: ReviewStatus): OutcomeSeverity {
  switch (status) {
    case "requested":
      return "warning";
    case "resolved":
    case "none":
    default:
      return "neutral";
  }
}

export function getPrioritySeverity(priority: Priority): OutcomeSeverity {
  switch (priority) {
    case "critical":
      return "failure";
    case "high":
      return "warning";
    case "normal":
    case "low":
    case "backlog":
    default:
      return "neutral";
  }
}

export function getBooleanOutcomeSeverity(value: boolean): OutcomeSeverity {
  return value ? "success" : "neutral";
}

export function getEvidenceSeverity(
  isSufficient: boolean | null,
): OutcomeSeverity {
  if (isSufficient === null) {
    return "neutral";
  }
  return isSufficient ? "success" : "warning";
}

export function getBlockingSeverity(isBlocking: boolean | null): OutcomeSeverity {
  if (isBlocking === null) {
    return "neutral";
  }
  return isBlocking ? "failure" : "success";
}

export function getMismatchSeverity(hasMismatch: boolean | null): OutcomeSeverity {
  if (hasMismatch === null) {
    return "neutral";
  }
  return hasMismatch ? "warning" : "success";
}
