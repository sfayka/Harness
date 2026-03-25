"use client";

import type { Task } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { StatusBadge } from "@/components/ui/status-badge";
import {
  X,
  ExternalLink,
  GitBranch,
  FileCode2,
  Clock,
  Link2,
  Maximize2,
  Minimize2,
} from "lucide-react";
import { TaskTimeline } from "./task-timeline";
import { EvidencePanel } from "./evidence-panel";
import { ReviewPanel } from "./review-panel";
import { VerificationCard } from "./verification-card";
import { ReconciliationCard } from "./reconciliation-card";

interface TaskDetailPanelProps {
  task: Task;
  onClose: () => void;
  isExpanded?: boolean;
  onToggleExpand?: () => void;
}

export function TaskDetailPanel({
  task,
  onClose,
  isExpanded = false,
  onToggleExpand,
}: TaskDetailPanelProps) {
  return (
    <div className="flex flex-col h-full bg-card border-l border-border">
      {/* Header */}
      <div className="flex items-start justify-between p-4 border-b border-border">
        <div className="flex-1 min-w-0 pr-4">
          <div className="flex items-center gap-2 mb-1">
            <span className="font-mono text-xs text-muted-foreground">
              {task.task_id}
            </span>
            <StatusBadge status={task.current_status} variant="task" />
            <StatusBadge status={task.priority} variant="priority" />
          </div>
          <h2 className="text-lg font-semibold text-foreground truncate">
            {task.title}
          </h2>
          {task.description && (
            <p className="text-sm text-muted-foreground mt-1 line-clamp-2">
              {task.description}
            </p>
          )}
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {onToggleExpand && (
            <button
              onClick={onToggleExpand}
              className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
              title={isExpanded ? "Collapse panel" : "Expand to full screen"}
            >
              {isExpanded ? (
                <Minimize2 className="h-4 w-4" />
              ) : (
                <Maximize2 className="h-4 w-4" />
              )}
              <span className="sr-only">
                {isExpanded ? "Collapse panel" : "Expand to full screen"}
              </span>
            </button>
          )}
          <button
            onClick={onClose}
            className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
          >
            <X className="h-4 w-4" />
            <span className="sr-only">Close panel</span>
          </button>
        </div>
      </div>

      {/* Scrollable Content */}
      <div className="flex-1 overflow-y-auto">
        <div
          className={`p-4 ${
            isExpanded
              ? "grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-6 max-w-[1800px] mx-auto"
              : "space-y-4"
          }`}
        >
          {/* Left column (in expanded) - Context & Metadata */}
          <div className={isExpanded ? "space-y-4" : "contents"}>
            {/* Identity & Origin */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle>Identity & Origin</CardTitle>
              </CardHeader>
              <CardContent>
                <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
                  <div>
                    <dt className="text-xs text-muted-foreground">Source</dt>
                    <dd className="flex items-center gap-1 mt-0.5">
                      <ExternalLink className="h-3 w-3 text-muted-foreground" />
                      <span className="font-medium">
                        {task.origin.source_system}
                      </span>
                      <span className="text-muted-foreground">
                        / {task.origin.source_id}
                      </span>
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">Ingress</dt>
                    <dd className="mt-0.5">
                      {task.origin.ingress_name || (
                        <span className="text-muted-foreground">-</span>
                      )}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">Created</dt>
                    <dd className="flex items-center gap-1 mt-0.5">
                      <Clock className="h-3 w-3 text-muted-foreground" />
                      {formatDateTime(task.timestamps.created_at)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">Updated</dt>
                    <dd className="flex items-center gap-1 mt-0.5">
                      <Clock className="h-3 w-3 text-muted-foreground" />
                      {formatDateTime(task.timestamps.updated_at)}
                    </dd>
                  </div>
                </dl>
              </CardContent>
            </Card>

            {/* Executor */}
            {task.assigned_executor && (
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle>Assigned Executor</CardTitle>
                </CardHeader>
                <CardContent>
                  <dl className="space-y-2 text-sm">
                    <div className="flex items-center gap-2">
                      <GitBranch className="h-4 w-4 text-muted-foreground" />
                      <span className="font-medium">
                        {task.assigned_executor.executor_type}
                      </span>
                      {task.assigned_executor.executor_id && (
                        <span className="text-muted-foreground font-mono text-xs">
                          ({task.assigned_executor.executor_id})
                        </span>
                      )}
                    </div>
                    {task.assigned_executor.assignment_reason && (
                      <p className="text-xs text-muted-foreground pl-6">
                        {task.assigned_executor.assignment_reason}
                      </p>
                    )}
                  </dl>
                </CardContent>
              </Card>
            )}

            {/* Relationships */}
            {(task.relationships.parent_task_id ||
              task.relationships.child_task_ids.length > 0 ||
              task.relationships.dependencies.length > 0) && (
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle>Relationships</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="space-y-3 text-sm">
                    {task.relationships.parent_task_id && (
                      <div>
                        <span className="text-xs text-muted-foreground">
                          Parent:
                        </span>
                        <div className="flex items-center gap-1 mt-0.5">
                          <Link2 className="h-3 w-3 text-muted-foreground" />
                          <span className="font-mono text-xs">
                            {task.relationships.parent_task_id}
                          </span>
                        </div>
                      </div>
                    )}
                    {task.relationships.child_task_ids.length > 0 && (
                      <div>
                        <span className="text-xs text-muted-foreground">
                          Children:
                        </span>
                        <div className="flex flex-wrap gap-1 mt-0.5">
                          {task.relationships.child_task_ids.map((id) => (
                            <span
                              key={id}
                              className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-muted text-xs font-mono"
                            >
                              <FileCode2 className="h-3 w-3" />
                              {id}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                    {task.relationships.dependencies.length > 0 && (
                      <div>
                        <span className="text-xs text-muted-foreground">
                          Dependencies:
                        </span>
                        <div className="flex flex-wrap gap-1 mt-0.5">
                          {task.relationships.dependencies.map((dep) => (
                            <span
                              key={dep.task_id}
                              className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-muted text-xs font-mono"
                            >
                              <Link2 className="h-3 w-3" />
                              {dep.task_id}
                              <span className="text-muted-foreground">
                                ({dep.dependency_type})
                              </span>
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </CardContent>
              </Card>
            )}

            {/* Timeline - moves to left column in expanded mode */}
            {isExpanded && <TaskTimeline events={task.timeline} />}
          </div>

          {/* Center column (in expanded) - Truth State: Verification, Reconciliation, Evidence */}
          <div className={isExpanded ? "space-y-4" : "contents"}>
            {/* Section header only in expanded mode */}
            {isExpanded && (
              <div className="pb-2 border-b border-border">
                <h3 className="text-sm font-semibold text-foreground">
                  Truth State
                </h3>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Verification, reconciliation, and supporting evidence
                </p>
              </div>
            )}

            {/* Verification & Reconciliation */}
            <div className="grid grid-cols-1 gap-4">
              <VerificationCard summary={task.verification_summary} />
              <ReconciliationCard summary={task.reconciliation_summary} />
            </div>

            {/* Evidence */}
            <EvidencePanel
              evidence={task.evidence_summary}
              timeline={task.timeline}
            />
          </div>

          {/* Right column (in expanded) - Review & Timeline */}
          <div className={isExpanded ? "space-y-4" : "contents"}>
            {/* Review */}
            <ReviewPanel review={task.review_summary} />

            {/* Timeline - only shown here in non-expanded mode */}
            {!isExpanded && <TaskTimeline events={task.timeline} />}
          </div>
        </div>
      </div>
    </div>
  );
}
