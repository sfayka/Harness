"use client";

import type { Task } from "@/lib/types";
import { formatDateTime, formatRelativeTime } from "@/lib/utils";
import { StatusBadge, TruthStateBadge } from "@/components/ui/status-badge";
import {
  AlertCircle,
  CheckCircle2,
  ChevronRight,
  Clock3,
  ExternalLink,
  GitBranch,
  XCircle,
} from "lucide-react";

type DashboardView = "tasks" | "verification" | "reconciliation" | "reviews";

interface TaskTableProps {
  tasks: Task[];
  selectedTaskId: string | null;
  onSelectTask: (taskId: string) => void;
  view: DashboardView;
}

export function TaskTable({
  tasks,
  selectedTaskId,
  onSelectTask,
  view,
}: TaskTableProps) {
  return (
    <div className="overflow-hidden rounded-lg border border-border">
      <table className="w-full">
        <thead>
          <tr className="border-b border-border bg-muted/30">
            {getHeaders(view).map((header) => (
              <th
                key={header.label}
                className={`px-4 py-3 text-left text-xs font-medium text-muted-foreground ${header.className ?? ""}`}
              >
                {header.label}
              </th>
            ))}
            <th className="w-8 px-4 py-3 text-left text-xs font-medium text-muted-foreground">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {tasks.map((task) => (
            <TaskRow
              key={task.task_id}
              task={task}
              isSelected={selectedTaskId === task.task_id}
              onSelect={() => onSelectTask(task.task_id)}
              view={view}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TaskRow({
  task,
  isSelected,
  onSelect,
  view,
}: {
  task: Task;
  isSelected: boolean;
  onSelect: () => void;
  view: DashboardView;
}) {
  return (
    <tr
      onClick={onSelect}
      className={`cursor-pointer border-b border-border last:border-b-0 transition-colors ${
        isSelected ? "bg-muted/50" : "hover:bg-muted/20"
      }`}
    >
      {renderCells(task, view)}
      <td className="px-4 py-3">
        <ChevronRight className="h-4 w-4 text-muted-foreground" />
      </td>
    </tr>
  );
}

function getHeaders(view: DashboardView) {
  switch (view) {
    case "verification":
      return [
        { label: "Task" },
        { label: "Verification" },
        { label: "Evidence" },
      ];
    case "reconciliation":
      return [
        { label: "Task" },
        { label: "Status" },
        { label: "Blocking", className: "hidden md:table-cell" },
        { label: "Mismatch Categories", className: "hidden lg:table-cell" },
      ];
    case "reviews":
      return [
        { label: "Task" },
        { label: "Requires Review" },
        { label: "Workflow", className: "hidden md:table-cell" },
        { label: "Latest Activity", className: "hidden xl:table-cell" },
      ];
    case "tasks":
    default:
      return [
        { label: "Task" },
        { label: "Status", className: "hidden lg:table-cell" },
        { label: "Origin", className: "hidden md:table-cell" },
        { label: "Updated", className: "hidden md:table-cell" },
      ];
  }
}

function renderCells(task: Task, view: DashboardView) {
  switch (view) {
    case "verification":
      return (
        <>
          <TaskIdentityCell
            task={task}
            subtitle={task.origin.source_id}
            showTruthBadge={false}
          />
          <td className="px-4 py-3">
            <div className="space-y-2">
              <StrictVerificationBadge task={task} />
              <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                <BooleanState
                  label="Passed"
                  value={task.verification_summary?.verification_passed ?? false}
                />
              </div>
            </div>
          </td>
          <td className="px-4 py-3">
            <div className="space-y-1 text-xs text-muted-foreground">
              <div>
                Sufficient:{" "}
                <InlineBoolean
                  value={
                    task.verification_summary?.evidence_is_sufficient ??
                    task.verification_summary?.evidence_sufficient ??
                    false
                  }
                />
              </div>
              <div>
                Valid:{" "}
                <InlineBoolean
                  value={task.verification_summary?.evidence_is_valid ?? false}
                />
              </div>
            </div>
          </td>
        </>
      );
    case "reconciliation":
      return (
        <>
          <TaskIdentityCell
            task={task}
            subtitle={task.origin.source_id}
            showTruthBadge={false}
          />
          <td className="px-4 py-3">
            <div className="space-y-2">
              <StrictReconciliationBadge task={task} />
            </div>
          </td>
          <td className="hidden px-4 py-3 md:table-cell">
            <BooleanState
              label={task.reconciliation_summary?.blocking ? "Blocking" : "Non-blocking"}
              value={task.reconciliation_summary?.blocking ?? false}
            />
          </td>
          <td className="hidden px-4 py-3 lg:table-cell">
            <TextList
              items={task.reconciliation_summary?.mismatch_categories ?? []}
              emptyLabel="None"
            />
          </td>
        </>
      );
    case "reviews":
      return (
        <>
          <TaskIdentityCell
            task={task}
            subtitle={task.review_summary.latest_request?.requested_by ?? task.origin.source_id}
            showTruthBadge={false}
          />
          <td className="px-4 py-3">
            <div className="space-y-2">
              <StatusBadge status={task.review_summary.status} variant="review" />
              <p className="text-xs text-muted-foreground">
                {task.review_summary.status === "requested"
                  ? "Requires explicit manual decision"
                  : task.review_summary.status === "resolved"
                    ? "Latest review decision recorded"
                    : "No active review"}
              </p>
            </div>
          </td>
          <td className="hidden px-4 py-3 md:table-cell">
            <div className="space-y-1 text-xs text-muted-foreground">
              <div>Requests: {task.review_summary.request_count}</div>
              <div>Decisions: {task.review_summary.decision_count}</div>
              <div>
                Latest decision:{" "}
                {task.review_summary.latest_decision?.outcome ?? "None"}
              </div>
            </div>
          </td>
          <td className="hidden px-4 py-3 xl:table-cell">
            <div className="space-y-1 text-xs text-muted-foreground">
              <div>
                Request:{" "}
                {task.review_summary.latest_request
                  ? formatDateTime(task.review_summary.latest_request.requested_at)
                  : "None"}
              </div>
              <div>
                Decision:{" "}
                {task.review_summary.latest_decision
                  ? formatDateTime(task.review_summary.latest_decision.reviewed_at)
                  : "None"}
              </div>
            </div>
          </td>
        </>
      );
    case "tasks":
    default:
      return (
        <>
          <TaskIdentityCell
            task={task}
            subtitle={task.origin.source_id}
            showTruthBadge
          />
          <td className="hidden px-4 py-3 lg:table-cell">
            <StatusBadge status={task.current_status} variant="task" />
          </td>
          <td className="hidden px-4 py-3 md:table-cell">
            <div className="space-y-1 text-xs text-muted-foreground">
              <div className="flex items-center gap-1">
                <ExternalLink className="h-3 w-3" />
                <span>{task.origin.source_system}</span>
              </div>
              <div>{task.origin.source_type}</div>
            </div>
          </td>
          <td className="hidden px-4 py-3 md:table-cell">
            <div className="space-y-1">
              <span className="text-xs text-muted-foreground">
                {formatRelativeTime(task.timestamps.updated_at)}
              </span>
              <div className="hidden text-[11px] text-muted-foreground xl:block">
                {formatDateTime(task.timestamps.updated_at)}
              </div>
            </div>
          </td>
        </>
      );
  }
}

function TaskIdentityCell({
  task,
  subtitle,
  showTruthBadge = false,
}: {
  task: Task;
  subtitle: string;
  showTruthBadge?: boolean;
}) {
  const needsReview = task.review_summary.status === "requested";

  return (
    <td className="px-4 py-3">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs text-muted-foreground">
              {task.task_id}
            </span>
            {needsReview && (
              <AlertCircle className="h-3.5 w-3.5 text-warning" />
            )}
          </div>
          <p className="mt-0.5 truncate text-sm font-medium text-foreground">
            {task.title}
          </p>
          <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1">
              <ExternalLink className="h-3 w-3" />
              {subtitle}
            </span>
            {task.assigned_executor && (
              <span className="hidden items-center gap-1 lg:inline-flex">
                <GitBranch className="h-3 w-3" />
                {task.assigned_executor.executor_type}
              </span>
            )}
          </div>
        </div>
        <div className={showTruthBadge ? "hidden md:block" : "hidden"}>
          <TruthStateBadge
            verificationStatus={task.verification_summary?.result ?? null}
            reconciliationStatus={task.reconciliation_summary?.result ?? null}
          />
        </div>
      </div>
    </td>
  );
}

function StrictVerificationBadge({ task }: { task: Task }) {
  const isAccepted = task.verification_summary?.completion_accepted ?? false;

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium ${
        isAccepted
          ? "bg-success/15 text-success"
          : "bg-destructive/15 text-destructive"
      }`}
    >
      <span
        className={`h-1.5 w-1.5 rounded-full ${
          isAccepted ? "bg-success" : "bg-destructive"
        }`}
      />
      {isAccepted ? "Accepted" : "Rejected"}
    </span>
  );
}

function StrictReconciliationBadge({ task }: { task: Task }) {
  const summary = task.reconciliation_summary;
  const isAligned =
    summary?.result === "no_mismatch" &&
    !summary.blocking &&
    (summary.mismatch_categories?.length ?? 0) === 0;

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium ${
        isAligned
          ? "bg-success/15 text-success"
          : "bg-warning/15 text-warning"
      }`}
    >
      <span
        className={`h-1.5 w-1.5 rounded-full ${
          isAligned ? "bg-success" : "bg-warning"
        }`}
      />
      {isAligned ? "Aligned" : "Mismatch"}
    </span>
  );
}

function BooleanState({
  label,
  value,
}: {
  label: string;
  value: boolean;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium ${
        value
          ? "bg-success/15 text-success"
          : "bg-muted text-muted-foreground"
      }`}
    >
      {value ? (
        <CheckCircle2 className="h-3.5 w-3.5" />
      ) : (
        <Clock3 className="h-3.5 w-3.5" />
      )}
      {label}
    </span>
  );
}

function InlineBoolean({ value }: { value: boolean }) {
  return (
    <span
      className={`inline-flex items-center gap-1 font-medium ${
        value ? "text-success" : "text-muted-foreground"
      }`}
    >
      {value ? (
        <CheckCircle2 className="h-3.5 w-3.5" />
      ) : (
        <XCircle className="h-3.5 w-3.5" />
      )}
      {value ? "Yes" : "No"}
    </span>
  );
}

function TextList({
  items,
  emptyLabel,
}: {
  items: string[];
  emptyLabel: string;
}) {
  if (items.length === 0) {
    return <span className="text-xs text-muted-foreground">{emptyLabel}</span>;
  }

  return (
    <div className="space-y-1">
      {items.slice(0, 2).map((item) => (
        <div key={item} className="text-xs text-foreground">
          {item}
        </div>
      ))}
      {items.length > 2 && (
        <div className="text-xs text-muted-foreground">
          +{items.length - 2} more
        </div>
      )}
    </div>
  );
}
