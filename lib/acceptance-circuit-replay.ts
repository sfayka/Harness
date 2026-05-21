import acceptedReadModel from "@/docs/demo/kno-183-pr-create-readback-validation/scenario-a-read-model-final.json";
import acceptedTimeline from "@/docs/demo/kno-183-pr-create-readback-validation/scenario-a-timeline-final.json";
import insufficientReadModel from "@/docs/demo/kno-184-missing-commit-recovery-validation/scenario-a-read-model-final.json";
import insufficientTimeline from "@/docs/demo/kno-184-missing-commit-recovery-validation/scenario-a-timeline-final.json";
import mismatchReadModel from "@/docs/demo/kno-184-missing-commit-recovery-validation/scenario-b-read-model-final.json";
import mismatchTimeline from "@/docs/demo/kno-184-missing-commit-recovery-validation/scenario-b-timeline-final.json";
import reviewReadModel from "@/docs/demo/kno-181-invalid-execution-attempt-gate/scenario-b-read-model-final.json";
import reviewTimeline from "@/docs/demo/kno-181-invalid-execution-attempt-gate/scenario-b-timeline-final.json";

export type AcceptanceNodeId =
  | "intent"
  | "contract"
  | "claim"
  | "evidence"
  | "reconcile"
  | "review"
  | "accepted";

export type AcceptanceEventTone =
  | "active"
  | "held"
  | "watch"
  | "passed"
  | "blocked";

export interface AcceptanceCircuitEvent {
  id: string;
  vocabulary: string;
  label: string;
  detail: string;
  nodeId: AcceptanceNodeId;
  source: string;
  occurredAt: string | null;
  tone: AcceptanceEventTone;
}

export interface AcceptanceCircuitScenario {
  id: string;
  title: string;
  description: string;
  taskId: string;
  modeLabel: string;
  readModelSource: string;
  timelineSource: string;
  evidenceLabel: string;
  reconciliationLabel: string;
  outcome: string;
  outcomeTone: AcceptanceEventTone;
  events: AcceptanceCircuitEvent[];
}

interface RawTimelineEvent {
  event_id?: string;
  event_type?: string;
  occurred_at?: string;
  source?: string;
  summary?: string;
  details?: Record<string, unknown>;
}

interface RawTaskReadModel {
  task_id?: string;
  title?: string;
  evidence_summary?: {
    artifact_count?: number;
    validated_artifact_count?: number;
    completion_evidence?: {
      status?: string;
      policy?: string;
    };
  };
  reconciliation_summary?: {
    status?: string;
    outcome?: string;
    mismatch_categories?: string[];
  } | null;
  verification_summary?: {
    outcome?: string;
    accepted_completion?: boolean;
    evidence_is_sufficient?: boolean;
    requires_review?: boolean;
    target_status?: string;
  } | null;
  review_summary?: {
    status?: string;
    request_count?: number;
  };
}

interface ReadModelFixture {
  task?: RawTaskReadModel;
}

interface TimelineFixture {
  timeline?: RawTimelineEvent[];
}

const fixtureScenarios = [
  {
    id: "accepted",
    title: "Accepted completion",
    description: "Canonical replay where evidence and reconciliation support completion.",
    readModel: acceptedReadModel,
    timeline: acceptedTimeline,
    readModelSource:
      "docs/demo/kno-183-pr-create-readback-validation/scenario-a-read-model-final.json",
    timelineSource:
      "docs/demo/kno-183-pr-create-readback-validation/scenario-a-timeline-final.json",
  },
  {
    id: "insufficient-evidence",
    title: "Insufficient evidence",
    description: "The claim exists, but completion evidence does not authorize acceptance.",
    readModel: insufficientReadModel,
    timeline: insufficientTimeline,
    readModelSource:
      "docs/demo/kno-184-missing-commit-recovery-validation/scenario-a-read-model-final.json",
    timelineSource:
      "docs/demo/kno-184-missing-commit-recovery-validation/scenario-a-timeline-final.json",
  },
  {
    id: "tracker-mismatch",
    title: "GitHub or tracker mismatch",
    description: "Reconciliation finds a blocking artifact mismatch instead of accepting the claim.",
    readModel: mismatchReadModel,
    timeline: mismatchTimeline,
    readModelSource:
      "docs/demo/kno-184-missing-commit-recovery-validation/scenario-b-read-model-final.json",
    timelineSource:
      "docs/demo/kno-184-missing-commit-recovery-validation/scenario-b-timeline-final.json",
  },
  {
    id: "manual-review",
    title: "Sticky manual review gate",
    description: "Reconciliation escalates to explicit review and keeps the task out of completed.",
    readModel: reviewReadModel,
    timeline: reviewTimeline,
    readModelSource:
      "docs/demo/kno-181-invalid-execution-attempt-gate/scenario-b-read-model-final.json",
    timelineSource:
      "docs/demo/kno-181-invalid-execution-attempt-gate/scenario-b-timeline-final.json",
  },
] satisfies Array<{
  id: string;
  title: string;
  description: string;
  readModel: ReadModelFixture;
  timeline: TimelineFixture;
  readModelSource: string;
  timelineSource: string;
}>;

export const acceptanceCircuitScenarios: AcceptanceCircuitScenario[] =
  fixtureScenarios.map((fixture) =>
    buildScenario({
      id: fixture.id,
      title: fixture.title,
      description: fixture.description,
      readModel: fixture.readModel,
      timeline: fixture.timeline,
      readModelSource: fixture.readModelSource,
      timelineSource: fixture.timelineSource,
    }),
  );

function buildScenario({
  id,
  title,
  description,
  readModel,
  timeline,
  readModelSource,
  timelineSource,
}: {
  id: string;
  title: string;
  description: string;
  readModel: ReadModelFixture;
  timeline: TimelineFixture;
  readModelSource: string;
  timelineSource: string;
}): AcceptanceCircuitScenario {
  const task = readModel.task ?? {};
  const events = mapTimelineToAcceptanceEvents(timeline.timeline ?? [], task);
  const outcome = getOutcome(task);

  return {
    id,
    title,
    description,
    taskId: task.task_id ?? id,
    modeLabel: "Sample replay: canonical fixture",
    readModelSource,
    timelineSource,
    evidenceLabel: getEvidenceLabel(task),
    reconciliationLabel: getReconciliationLabel(task),
    outcome,
    outcomeTone: getOutcomeTone(task),
    events,
  };
}

export function mapTimelineToAcceptanceEvents(
  timeline: RawTimelineEvent[],
  task: RawTaskReadModel = {},
): AcceptanceCircuitEvent[] {
  const mappedEvents = timeline.flatMap((event) => mapTimelineEvent(event, task));
  const hasTerminal = mappedEvents.some((event) => event.nodeId === "accepted");

  if (!hasTerminal) {
    mappedEvents.push(buildTerminalEvent(task));
  }

  return dedupeByVocabularyAndNode(mappedEvents);
}

function mapTimelineEvent(
  event: RawTimelineEvent,
  task: RawTaskReadModel,
): AcceptanceCircuitEvent[] {
  const eventType = event.event_type ?? "unknown";
  const source = event.source ?? "proofline";
  const occurredAt = event.occurred_at ?? null;
  const summary = event.summary ?? eventType;

  switch (eventType) {
    case "task_created":
      return [
        buildEvent(event, {
          vocabulary: "intent.registered",
          label: "Intent registered",
          detail: summary,
          nodeId: "intent",
          tone: "active",
        }),
        {
          id: `${event.event_id ?? "task"}:contract`,
          vocabulary: "contract.created",
          label: "TaskEnvelope created",
          detail: "Canonical task contract is available for evaluation.",
          nodeId: "contract",
          source,
          occurredAt,
          tone: "active",
        },
      ];
    case "execution_attempt_recorded":
      return [
        buildEvent(event, {
          vocabulary: "claim.received",
          label: "Agent claim received",
          detail: "Executor-reported success is advisory until evidence is checked.",
          nodeId: "claim",
          tone: "held",
        }),
      ];
    case "artifact_captured":
    case "execution_artifact_attached":
      return [
        buildEvent(event, {
          vocabulary: getEvidenceVocabulary(task),
          label: getEvidenceEventLabel(task),
          detail: summary,
          nodeId: "evidence",
          tone: getEvidenceTone(task),
        }),
      ];
    case "linear_linkage_recorded":
    case "reconciliation_attempt_recorded":
      return [
        buildEvent(event, {
          vocabulary: getReconciliationVocabulary(task),
          label: getReconciliationEventLabel(task),
          detail: summary,
          nodeId: "reconcile",
          tone: getReconciliationTone(task),
        }),
      ];
    case "review_requested":
      return [
        buildEvent(event, {
          vocabulary: "review.requested",
          label: "Manual review requested",
          detail: summary,
          nodeId: "review",
          tone: "watch",
        }),
      ];
    case "evaluation_recorded":
      return [
        buildEvent(event, {
          vocabulary: getPolicyVocabulary(task),
          label: getPolicyLabel(task),
          detail: summary,
          nodeId: "accepted",
          tone: getOutcomeTone(task),
        }),
      ];
    default:
      return [];
  }
}

function buildEvent(
  event: RawTimelineEvent,
  mapped: Omit<AcceptanceCircuitEvent, "id" | "source" | "occurredAt">,
): AcceptanceCircuitEvent {
  return {
    id: event.event_id ?? `${mapped.vocabulary}:${mapped.nodeId}`,
    source: event.source ?? "proofline",
    occurredAt: event.occurred_at ?? null,
    ...mapped,
  };
}

function buildTerminalEvent(task: RawTaskReadModel): AcceptanceCircuitEvent {
  return {
    id: `${task.task_id ?? "task"}:policy`,
    vocabulary: getPolicyVocabulary(task),
    label: getPolicyLabel(task),
    detail: getOutcome(task),
    nodeId:
      task.review_summary?.status === "requested" || task.verification_summary?.requires_review
        ? "review"
        : "accepted",
    source: "read-model",
    occurredAt: null,
    tone: getOutcomeTone(task),
  };
}

function dedupeByVocabularyAndNode(
  events: AcceptanceCircuitEvent[],
): AcceptanceCircuitEvent[] {
  const seen = new Set<string>();
  return events.filter((event) => {
    const key = `${event.vocabulary}:${event.nodeId}`;
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

function getEvidenceVocabulary(task: RawTaskReadModel) {
  const status = task.evidence_summary?.completion_evidence?.status;
  if (status === "satisfied") {
    return "evidence.validated";
  }
  if (status === "not_applicable" || status === "deferred") {
    return "evidence.insufficient";
  }
  return "evidence.observed";
}

function getEvidenceEventLabel(task: RawTaskReadModel) {
  return task.evidence_summary?.completion_evidence?.status === "satisfied"
    ? "Evidence validated"
    : "Evidence insufficient";
}

function getEvidenceTone(task: RawTaskReadModel): AcceptanceEventTone {
  return task.evidence_summary?.completion_evidence?.status === "satisfied"
    ? "passed"
    : "held";
}

function getReconciliationVocabulary(task: RawTaskReadModel) {
  const status = task.reconciliation_summary?.status;
  if (status === "passed") {
    return "reconciliation.passed";
  }
  if (status === "review_required") {
    return "reconciliation.review_required";
  }
  if (status === "mismatch") {
    return "reconciliation.mismatch";
  }
  return "reconciliation.pending";
}

function getReconciliationEventLabel(task: RawTaskReadModel) {
  const status = task.reconciliation_summary?.status;
  if (status === "passed") {
    return "Reconciliation passed";
  }
  if (status === "review_required") {
    return "Review required";
  }
  if (status === "mismatch") {
    return "Mismatch found";
  }
  return "Reconciliation pending";
}

function getReconciliationTone(task: RawTaskReadModel): AcceptanceEventTone {
  const status = task.reconciliation_summary?.status;
  if (status === "passed") {
    return "passed";
  }
  if (status === "mismatch") {
    return "blocked";
  }
  if (status === "review_required") {
    return "watch";
  }
  return "held";
}

function getPolicyVocabulary(task: RawTaskReadModel) {
  if (task.verification_summary?.accepted_completion) {
    return "policy.accepted";
  }
  if (task.review_summary?.status === "requested" || task.verification_summary?.requires_review) {
    return "policy.review_gate";
  }
  return "policy.blocked";
}

function getPolicyLabel(task: RawTaskReadModel) {
  if (task.verification_summary?.accepted_completion) {
    return "Accepted by policy";
  }
  if (task.review_summary?.status === "requested" || task.verification_summary?.requires_review) {
    return "Held for review";
  }
  return "Not accepted";
}

function getOutcome(task: RawTaskReadModel) {
  if (task.verification_summary?.accepted_completion) {
    return "accepted";
  }
  if (task.review_summary?.status === "requested" || task.verification_summary?.requires_review) {
    return "review required";
  }
  if (task.reconciliation_summary?.status === "mismatch") {
    return "blocked";
  }
  if (task.verification_summary?.outcome === "insufficient_evidence") {
    return "insufficient evidence";
  }
  return "not accepted";
}

function getOutcomeTone(task: RawTaskReadModel): AcceptanceEventTone {
  if (task.verification_summary?.accepted_completion) {
    return "passed";
  }
  if (task.review_summary?.status === "requested" || task.verification_summary?.requires_review) {
    return "watch";
  }
  if (task.reconciliation_summary?.status === "mismatch") {
    return "blocked";
  }
  return "held";
}

function getEvidenceLabel(task: RawTaskReadModel) {
  const artifactCount = task.evidence_summary?.artifact_count ?? 0;
  const validatedCount = task.evidence_summary?.validated_artifact_count ?? 0;
  const status = task.evidence_summary?.completion_evidence?.status ?? "unknown";
  return `${validatedCount}/${artifactCount} validated (${status})`;
}

function getReconciliationLabel(task: RawTaskReadModel) {
  const summary = task.reconciliation_summary;
  if (!summary) {
    return "pending";
  }
  const mismatchCategories = summary.mismatch_categories ?? [];
  return mismatchCategories.length > 0
    ? `${summary.status}: ${mismatchCategories.join(", ")}`
    : summary.status ?? summary.outcome ?? "pending";
}
