import { mockTasks } from "@/lib/mock-data";
import type {
  ReconciliationStatus,
  ReviewDecision,
  ReviewRequest,
  Task,
  TimelineEvent,
  VerificationStatus,
} from "@/lib/types";

const proxyBasePath = "/api/harness";

function mapVerificationStatus(summary: Record<string, unknown> | null): VerificationStatus | null {
  if (!summary) {
    return null;
  }
  switch (summary.outcome) {
    case "accepted_completion":
      return "accepted";
    case "insufficient_evidence":
      return "insufficient_evidence";
    case "verification_deferred":
      return "deferred";
    case "blocked_unresolved_conditions":
    case "review_required":
      return "pending";
    case "external_mismatch":
    case "terminal_invalid":
      return "rejected";
    default:
      return "pending";
  }
}

function mapReconciliationStatus(summary: Record<string, unknown> | null): ReconciliationStatus | null {
  if (!summary) {
    return null;
  }

  const categories = Array.isArray(summary.mismatch_categories)
    ? summary.mismatch_categories.map(String)
    : [];

  if (categories.includes("wrong_repository") || categories.includes("wrong_branch")) {
    return "wrong_target";
  }

  switch (summary.outcome) {
    case "no_mismatch":
      return "no_mismatch";
    case "wrong_target":
      return "wrong_target";
    case "contradictory_facts":
    case "terminal_invalid":
      return "contradictory_facts";
    case "missing_evidence":
      return "stale_evidence";
    case "review_required":
    case "reconciliation_pending":
      return "pending";
    default:
      return "pending";
  }
}

function mapReviewRequest(summary: Record<string, unknown> | null): ReviewRequest | null {
  if (!summary) {
    return null;
  }
  return {
    review_request_id: String(summary.review_request_id ?? ""),
    reason: String(summary.summary ?? summary.reason ?? ""),
    requested_by: String(summary.requested_by ?? "harness"),
    requested_at: String(summary.requested_at ?? ""),
  };
}

function mapReviewDecisionOutcome(outcome: string | null | undefined): ReviewDecision["outcome"] {
  switch (outcome) {
    case "accept_completion":
      return "approved";
    case "keep_blocked":
    case "reject_completion":
    case "mark_failed":
    case "cancel_task":
      return "rejected";
    default:
      return "deferred";
  }
}

function mapReviewDecision(summary: Record<string, unknown> | null): ReviewDecision | null {
  if (!summary) {
    return null;
  }
  const reviewer =
    summary.reviewer && typeof summary.reviewer === "object"
      ? (summary.reviewer as Record<string, unknown>)
      : {};
  const outcome = String(summary.outcome ?? "");
  return {
    review_id: String(summary.review_id ?? ""),
    outcome: mapReviewDecisionOutcome(outcome),
    notes: summary.reasoning ? String(summary.reasoning) : null,
    reviewer: {
      reviewer_name: String(reviewer.reviewer_name ?? "Unknown reviewer"),
      reviewer_type: String(reviewer.authority_role ?? "operator"),
    },
    reviewed_at: String(summary.reviewed_at ?? ""),
  };
}

function mapTimelineEvent(event: Record<string, unknown>): TimelineEvent {
  const details =
    event.details && typeof event.details === "object"
      ? { ...(event.details as Record<string, unknown>) }
      : {};

  if (event.event_type === "artifact_captured") {
    const branch = details.branch;
    if (branch && typeof branch === "object") {
      details.branch = String((branch as Record<string, unknown>).name ?? "");
    }
  }

  if (event.event_type === "review_decided") {
    details.outcome = mapReviewDecisionOutcome(
      typeof details.outcome === "string" ? details.outcome : null,
    );
    if (details.reasoning && !details.notes) {
      details.notes = details.reasoning;
    }
    const reviewer =
      details.reviewer && typeof details.reviewer === "object"
        ? (details.reviewer as Record<string, unknown>)
        : {};
    details.reviewer = {
      reviewer_name: String(reviewer.reviewer_name ?? "Unknown reviewer"),
      reviewer_type: String(reviewer.authority_role ?? "operator"),
    };
  }

  return {
    event_id: String(event.event_id ?? ""),
    event_type: event.event_type as TimelineEvent["event_type"],
    occurred_at: String(event.occurred_at ?? ""),
    summary: String(event.summary ?? ""),
    source: String(event.source ?? "harness"),
    details,
  };
}

function mapTask(readModel: Record<string, unknown>, timelineOverride?: TimelineEvent[]): Task {
  const relationships =
    readModel.relationships && typeof readModel.relationships === "object"
      ? (readModel.relationships as Record<string, unknown>)
      : {};
  const evidenceSummary =
    readModel.evidence_summary && typeof readModel.evidence_summary === "object"
      ? (readModel.evidence_summary as Record<string, unknown>)
      : {};
  const verificationSummary =
    readModel.verification_summary && typeof readModel.verification_summary === "object"
      ? (readModel.verification_summary as Record<string, unknown>)
      : null;
  const reconciliationSummary =
    readModel.reconciliation_summary && typeof readModel.reconciliation_summary === "object"
      ? (readModel.reconciliation_summary as Record<string, unknown>)
      : null;
  const reviewSummary =
    readModel.review_summary && typeof readModel.review_summary === "object"
      ? (readModel.review_summary as Record<string, unknown>)
      : {};
  const evaluationSummary =
    readModel.evaluation_summary && typeof readModel.evaluation_summary === "object"
      ? (readModel.evaluation_summary as Record<string, unknown>)
      : {};
  const timestamps =
    readModel.timestamps && typeof readModel.timestamps === "object"
      ? (readModel.timestamps as Record<string, unknown>)
      : {};
  const timelineSource = timelineOverride ?? (
    Array.isArray(readModel.timeline)
      ? readModel.timeline.map((event) => mapTimelineEvent(event as Record<string, unknown>))
      : []
  );
  const mappedVerificationStatus = mapVerificationStatus(verificationSummary);
  const mappedReconciliationStatus = mapReconciliationStatus(reconciliationSummary);
  const reasons = Array.isArray(verificationSummary?.reasons)
    ? verificationSummary.reasons.map(String)
    : [];
  const mismatches = Array.isArray(reconciliationSummary?.reasons)
    ? reconciliationSummary.reasons.map(String)
    : [];

  return {
    task_id: String(readModel.task_id ?? ""),
    title: String(readModel.title ?? ""),
    description: readModel.description ? String(readModel.description) : null,
    current_status: String(readModel.current_status ?? "intake_ready") as Task["current_status"],
    objective_summary: readModel.objective_summary
      ? String(readModel.objective_summary)
      : null,
    origin: {
      source_system: String((readModel.origin as Record<string, unknown> | undefined)?.source_system ?? "harness"),
      source_type: String((readModel.origin as Record<string, unknown> | undefined)?.source_type ?? "unknown"),
      source_id: String((readModel.origin as Record<string, unknown> | undefined)?.source_id ?? ""),
      ingress_id: ((readModel.origin as Record<string, unknown> | undefined)?.ingress_id as string | null | undefined) ?? null,
      ingress_name: ((readModel.origin as Record<string, unknown> | undefined)?.ingress_name as string | null | undefined) ?? null,
    },
    relationships: {
      parent_task_id: (relationships.parent_task_id as string | null | undefined) ?? null,
      child_task_ids: Array.isArray(relationships.child_task_ids)
        ? relationships.child_task_ids.map(String)
        : [],
      dependencies: Array.isArray(relationships.dependencies)
        ? relationships.dependencies.map((dependency) => ({
            task_id: String((dependency as Record<string, unknown>).task_id ?? ""),
            dependency_type: String((dependency as Record<string, unknown>).dependency_type ?? "depends_on"),
          }))
        : [],
    },
    assigned_executor:
      readModel.assigned_executor && typeof readModel.assigned_executor === "object"
        ? {
            executor_type: String((readModel.assigned_executor as Record<string, unknown>).executor_type ?? ""),
            executor_id: ((readModel.assigned_executor as Record<string, unknown>).executor_id as string | null | undefined) ?? null,
            assignment_reason:
              ((readModel.assigned_executor as Record<string, unknown>).assignment_reason as string | null | undefined) ??
              null,
          }
        : null,
    evidence_summary: {
      artifact_count: Number(evidenceSummary.artifact_count ?? 0),
      artifact_type_counts:
        (evidenceSummary.artifact_type_counts as Record<string, number> | undefined) ?? {},
      verification_status_counts:
        (evidenceSummary.verification_status_counts as Record<string, number> | undefined) ?? {},
      validated_artifact_count: Number(evidenceSummary.validated_artifact_count ?? 0),
      completion_evidence: {
        policy: String((evidenceSummary.completion_evidence as Record<string, unknown> | undefined)?.policy ?? ""),
        status: String((evidenceSummary.completion_evidence as Record<string, unknown> | undefined)?.status ?? ""),
        required_artifact_types: Array.isArray(
          (evidenceSummary.completion_evidence as Record<string, unknown> | undefined)?.required_artifact_types,
        )
          ? (((evidenceSummary.completion_evidence as Record<string, unknown> | undefined)
              ?.required_artifact_types as unknown[]) ?? []).map(String)
          : [],
        validated_artifact_ids: Array.isArray(
          (evidenceSummary.completion_evidence as Record<string, unknown> | undefined)?.validated_artifact_ids,
        )
          ? (((evidenceSummary.completion_evidence as Record<string, unknown> | undefined)
              ?.validated_artifact_ids as unknown[]) ?? []).map(String)
          : [],
        validation_method:
          ((evidenceSummary.completion_evidence as Record<string, unknown> | undefined)?.validation_method as
            | string
            | null
            | undefined) ?? null,
        validated_at:
          ((evidenceSummary.completion_evidence as Record<string, unknown> | undefined)?.validated_at as
            | string
            | null
            | undefined) ?? null,
      },
    },
    verification_summary: verificationSummary && mappedVerificationStatus
      ? {
          result: mappedVerificationStatus,
          completion_accepted: Boolean(verificationSummary.accepted_completion),
          evidence_sufficient: Boolean(verificationSummary.evidence_is_sufficient),
          reasons,
          evaluated_at:
            (evaluationSummary.latest_recorded_at as string | undefined) ??
            ((timestamps.updated_at as string | undefined) ?? ""),
        }
      : null,
    reconciliation_summary: reconciliationSummary && mappedReconciliationStatus
      ? {
          result: mappedReconciliationStatus,
          linear_state:
            (reconciliationSummary.status as string | undefined) ??
            null,
          github_state:
            Array.isArray(reconciliationSummary.mismatch_categories) &&
            reconciliationSummary.mismatch_categories.length > 0
              ? String((reconciliationSummary.mismatch_categories as unknown[])[0])
              : null,
          harness_state: String(readModel.current_status ?? ""),
          mismatches,
          evaluated_at:
            (evaluationSummary.latest_recorded_at as string | undefined) ??
            ((timestamps.updated_at as string | undefined) ?? ""),
        }
      : null,
    review_summary: {
      status:
        (reviewSummary.status as Task["review_summary"]["status"] | undefined) ??
        "none",
      request_count: Number(reviewSummary.request_count ?? 0),
      decision_count: Number(reviewSummary.decision_count ?? 0),
      latest_request: mapReviewRequest(
        reviewSummary.latest_request && typeof reviewSummary.latest_request === "object"
          ? (reviewSummary.latest_request as Record<string, unknown>)
          : null,
      ),
      latest_decision: mapReviewDecision(
        reviewSummary.latest_decision && typeof reviewSummary.latest_decision === "object"
          ? (reviewSummary.latest_decision as Record<string, unknown>)
          : null,
      ),
      requests: Array.isArray(reviewSummary.requests)
        ? reviewSummary.requests.map((request) => mapReviewRequest(request as Record<string, unknown>)).filter(Boolean) as ReviewRequest[]
        : [],
      decisions: Array.isArray(reviewSummary.decisions)
        ? reviewSummary.decisions.map((decision) => mapReviewDecision(decision as Record<string, unknown>)).filter(Boolean) as ReviewDecision[]
        : [],
    },
    timestamps: {
      created_at: String(timestamps.created_at ?? ""),
      updated_at: String(timestamps.updated_at ?? ""),
      completed_at: (timestamps.completed_at as string | null | undefined) ?? null,
    },
    timeline: timelineSource,
    priority: (readModel.priority as Task["priority"] | undefined) ?? "normal",
  };
}

async function fetchJson(path: string): Promise<unknown> {
  const response = await fetch(`${proxyBasePath}${path}`, {
    headers: { Accept: "application/json" },
    cache: "no-store",
  });

  if (!response.ok) {
    let message = `Harness API request failed with ${response.status}`;
    try {
      const payload = (await response.json()) as { error?: string };
      if (payload.error) {
        message = payload.error;
      }
    } catch {
      // Keep the generic error when the proxy body is not JSON.
    }
    throw new Error(message);
  }

  return response.json();
}

export async function fetchDashboardTasks(): Promise<{
  tasks: Task[];
  dataMode: "live" | "mock";
  message: string | null;
}> {
  try {
    const payload = (await fetchJson("/tasks")) as { tasks?: Record<string, unknown>[] };
    return {
      tasks: Array.isArray(payload.tasks)
        ? payload.tasks.map((task) => mapTask(task))
        : [],
      dataMode: "live",
      message: null,
    };
  } catch (error) {
    return {
      tasks: mockTasks,
      dataMode: "mock",
      message:
        `Using sample dashboard data because the configured Harness API is unavailable: ${
          error instanceof Error ? error.message : "unknown error"
        }`,
    };
  }
}

export async function fetchTaskDetail(taskId: string): Promise<Task> {
  const [taskPayload, timelinePayload] = await Promise.all([
    fetchJson(`/tasks/${taskId}/read-model`) as Promise<{ task?: Record<string, unknown> }>,
    fetchJson(`/tasks/${taskId}/timeline`) as Promise<{ timeline?: Record<string, unknown>[] }>,
  ]);

  if (!taskPayload.task) {
    throw new Error(`Task ${taskId} did not return a read model.`);
  }

  const timeline = Array.isArray(timelinePayload.timeline)
    ? timelinePayload.timeline.map((event) => mapTimelineEvent(event))
    : [];
  return mapTask(taskPayload.task, timeline);
}
