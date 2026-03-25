"use client";

import type { Task } from "@/lib/types";
import { formatRelativeTime } from "@/lib/utils";
import {
  StatusBadge,
  TruthStateBadge,
} from "@/components/ui/status-badge";
import {
  AlertCircle,
  GitBranch,
  ExternalLink,
  ChevronRight,
} from "lucide-react";

interface TaskTableProps {
  tasks: Task[];
  selectedTaskId: string | null;
  onSelectTask: (taskId: string) => void;
}

export function TaskTable({
  tasks,
  selectedTaskId,
  onSelectTask,
}: TaskTableProps) {
  return (
    <div className="border border-border rounded-lg overflow-hidden">
      <table className="w-full">
        <thead>
          <tr className="border-b border-border bg-muted/30">
            <th className="text-left text-xs font-medium text-muted-foreground px-4 py-3">
              Task
            </th>
            <th className="text-left text-xs font-medium text-muted-foreground px-4 py-3 hidden lg:table-cell">
              Status
            </th>
            <th className="text-left text-xs font-medium text-muted-foreground px-4 py-3 hidden md:table-cell">
              Truth State
            </th>
            <th className="text-left text-xs font-medium text-muted-foreground px-4 py-3 hidden md:table-cell">
              Updated
            </th>
            <th className="text-left text-xs font-medium text-muted-foreground px-4 py-3 w-8">
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
}: {
  task: Task;
  isSelected: boolean;
  onSelect: () => void;
}) {
  const needsReview = task.review_summary.status === "requested";

  return (
    <tr
      onClick={onSelect}
      className={`border-b border-border last:border-b-0 cursor-pointer transition-colors ${
        isSelected
          ? "bg-muted/50"
          : "hover:bg-muted/20"
      }`}
    >
      <td className="px-4 py-3">
        <div className="flex items-start gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs text-muted-foreground">
                {task.task_id}
              </span>
              {needsReview && (
                <AlertCircle className="h-3.5 w-3.5 text-warning" />
              )}
            </div>
            <p className="text-sm font-medium text-foreground truncate mt-0.5">
              {task.title}
            </p>
            <div className="flex items-center gap-2 mt-1">
              {task.origin.source_system && (
                <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                  <ExternalLink className="h-3 w-3" />
                  {task.origin.source_id}
                </span>
              )}
              {task.assigned_executor && (
                <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                  <GitBranch className="h-3 w-3" />
                  {task.assigned_executor.executor_type}
                </span>
              )}
            </div>
          </div>
          <div className="lg:hidden">
            <StatusBadge status={task.current_status} variant="task" />
          </div>
        </div>
      </td>
      <td className="px-4 py-3 hidden lg:table-cell">
        <StatusBadge status={task.current_status} variant="task" />
      </td>
      <td className="px-4 py-3 hidden md:table-cell">
        <TruthStateBadge
          verificationStatus={task.verification_summary?.result ?? null}
          reconciliationStatus={task.reconciliation_summary?.result ?? null}
        />
      </td>
      <td className="px-4 py-3 hidden md:table-cell">
        <span className="text-xs text-muted-foreground">
          {formatRelativeTime(task.timestamps.updated_at)}
        </span>
      </td>
      <td className="px-4 py-3">
        <ChevronRight className="h-4 w-4 text-muted-foreground" />
      </td>
    </tr>
  );
}
