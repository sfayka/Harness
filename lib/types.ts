export type TaskStatus =
  | "intake_ready"
  | "planned"
  | "dispatch_ready"
  | "assigned"
  | "executing"
  | "reconciling"
  | "blocked"
  | "in_review"
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
  outcome?: string | null;
  completion_accepted: boolean;
  verification_passed?: boolean;
  evidence_sufficient: boolean;
  evidence_is_valid?: boolean;
  evidence_is_sufficient?: boolean;
  reasons: string[];
  evaluated_at: string;
}

export interface CompletionValidationSummary {
  status:
    | "accepted"
    | "blocked"
    | "review_required"
    | "pending"
    | "failed"
    | "canceled";
  summary: string;
  intent_status: "matched" | "not_validated" | "needs_review" | "not_accepted" | "pending";
  evidence_status: "sufficient" | "insufficient" | "invalid" | "not_required" | "pending";
  reconciliation_status: string;
  completion_claimed: boolean;
  completion_accepted: boolean;
  manual_review_status: string | null;
  automatic_completion_safe: boolean;
  verification_outcome: string;
  reasons: string[];
  required_criteria_count: number;
  concrete_required_criteria_count: number;
  required_artifact_types: string[];
  validated_artifact_ids: string[];
  validated_artifact_count: number;
}

export interface ReconciliationSummary {
  result: ReconciliationStatus;
  outcome?: string | null;
  status?: string | null;
  blocking?: boolean;
  mismatch_categories?: string[];
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

export interface ExecutionSummary {
  attempt_count: number;
  latest_status: string | null;
  latest_dispatch_origin: string | null;
  latest_execution_transport_status: string | null;
  latest_live_dispatch_enabled: boolean | null;
  latest_completion_authority: string | null;
  latest_runner_completion_is_truth: boolean | null;
}

export interface TimelineEvent {
  event_id: string;
  event_type:
    | "task_created"
    | "status_transition"
    | "artifact_captured"
    | "reconciliation_attempt_recorded"
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
  completion_validation_summary: CompletionValidationSummary;
  verification_summary: VerificationSummary | null;
  reconciliation_summary: ReconciliationSummary | null;
  review_summary: ReviewSummary;
  execution_summary?: ExecutionSummary;
  evaluation_summary: {
    count: number;
    latest_action: string | null;
    latest_recorded_at: string | null;
    latest_target_status: string | null;
  };
  timestamps: {
    created_at: string;
    updated_at: string;
    completed_at: string | null;
  };
  timeline: TimelineEvent[];
  priority: Priority;
}

export interface ExecutionSubstrateHandoff {
  task_id: string;
  attention_type: string;
  current_status: string;
  last_activity_at: string | null;
  completion_validation_summary: CompletionValidationSummary | null;
  handoff: {
    adapter: string;
    mode: string;
    intent: {
      intent_type: string;
      substrate_kind: string;
      task_id: string;
      source: string;
      reason: string;
      suggested_action: string;
      advisory_only: boolean;
      events_endpoint: string;
      completion_authority: string;
      prohibited_actions: string[];
    };
    harness_boundary: {
      completion_authority: string;
      advisory_only: boolean;
      runner_completion_is_truth: boolean;
      artifact_verification_required: boolean;
    };
    runner_policy: {
      substrate_kind: string;
      allowed_intent_type: string;
      prohibited_actions: string[];
    };
    callback: {
      events_endpoint: string;
      events_url: string;
      event_contract: string;
    };
    metadata: {
      task_id: string;
      source: string;
      safe_to_execute_live: boolean;
    };
  };
}

export interface ExecutionSubstrateHandoffPreview {
  generated_at: string;
  handoff_count: number;
  handoffs: ExecutionSubstrateHandoff[];
  source: string;
  advisory_only: boolean;
  dispatch_enabled: boolean;
  completion_authority: string;
}

export interface ExecutionSubstrateTransportStatus {
  generated_at: string;
  substrate_kind: string;
  preferred_runner: string;
  transport_status: string;
  dispatch_enabled: boolean;
  live_dispatch_enabled: boolean;
  advisory_only: boolean;
  completion_authority: string;
  runner_completion_is_truth: boolean;
  safe_to_execute_live: boolean;
  events_contract: string;
  handoff_preview_endpoint: string;
  intents_endpoint: string;
  message: string;
}
