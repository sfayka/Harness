export type TaskStatus =
  | "intake_ready"
  | "planned"
  | "dispatch_ready"
  | "assigned"
  | "executing"
  | "blocked"
  | "completed"
  | "failed"
  | "canceled";

export type VerificationStatus =
  | "accepted"
  | "insufficient_evidence"
  | "deferred"
  | "pending"
  | "rejected";

export type ReconciliationStatus =
  | "no_mismatch"
  | "wrong_target"
  | "contradictory_facts"
  | "stale_evidence"
  | "pending";

export type ReviewStatus = "none" | "requested" | "resolved";

export type ArtifactType =
  | "pull_request"
  | "commit"
  | "branch"
  | "changed_file"
  | "log"
  | "output"
  | "review_note";

export type Priority = "critical" | "high" | "normal" | "low" | "backlog";

export interface Origin {
  source_system: string;
  source_type: string;
  source_id: string;
  ingress_id?: string | null;
  ingress_name?: string | null;
}

export interface Artifact {
  id: string;
  type: ArtifactType;
  title: string | null;
  description: string | null;
  location: string | null;
  verification_status: "unverified" | "verified" | "rejected" | "informational";
  repository?: {
    owner: string;
    name: string;
  } | null;
  branch?: {
    name: string;
    ref: string;
  } | null;
  commit_sha?: string | null;
  pull_request_number?: number | null;
  captured_at: string;
}

export interface EvidenceSummary {
  artifact_count: number;
  artifact_type_counts: Record<string, number>;
  verification_status_counts: Record<string, number>;
  validated_artifact_count: number;
  completion_evidence: {
    policy: string | null;
    status: string | null;
    required_artifact_types: string[];
    validated_artifact_ids: string[];
    validation_method: string | null;
    validated_at: string | null;
  };
}

export interface VerificationSummary {
  result: VerificationStatus;
  completion_accepted: boolean;
  evidence_sufficient: boolean;
  reasons: string[];
  evaluated_at: string;
}

export interface ReconciliationSummary {
  result: ReconciliationStatus;
  linear_state: string | null;
  github_state: string | null;
  harness_state: string | null;
  mismatches: string[];
  evaluated_at: string;
}

export interface ReviewRequest {
  review_request_id: string;
  reason: string;
  requested_by: string;
  requested_at: string;
}

export interface ReviewDecision {
  review_id: string;
  outcome: "approved" | "rejected" | "deferred";
  notes: string | null;
  reviewer: {
    reviewer_name: string;
    reviewer_type: string;
  };
  reviewed_at: string;
}

export interface ReviewSummary {
  status: ReviewStatus;
  request_count: number;
  decision_count: number;
  latest_request: ReviewRequest | null;
  latest_decision: ReviewDecision | null;
  requests: ReviewRequest[];
  decisions: ReviewDecision[];
}

export interface TimelineEvent {
  event_id: string;
  event_type:
    | "task_created"
    | "status_transition"
    | "artifact_captured"
    | "evaluation_recorded"
    | "review_requested"
    | "review_decided";
  occurred_at: string;
  summary: string;
  source: string;
  details: Record<string, unknown>;
}

export interface Task {
  task_id: string;
  title: string;
  description: string | null;
  current_status: TaskStatus;
  objective_summary: string | null;
  origin: Origin;
  relationships: {
    parent_task_id: string | null;
    child_task_ids: string[];
    dependencies: { task_id: string; dependency_type: string }[];
  };
  assigned_executor: {
    executor_type: string;
    executor_id: string | null;
    assignment_reason: string | null;
  } | null;
  evidence_summary: EvidenceSummary;
  verification_summary: VerificationSummary | null;
  reconciliation_summary: ReconciliationSummary | null;
  review_summary: ReviewSummary;
  timestamps: {
    created_at: string;
    updated_at: string;
    completed_at: string | null;
  };
  timeline: TimelineEvent[];
  priority: Priority;
}
