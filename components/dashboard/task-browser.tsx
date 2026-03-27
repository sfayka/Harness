"use client";

import { startTransition, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Filter,
  GitCompare,
  RefreshCw,
  Search,
  ShieldCheck,
  UserCheck,
  XCircle,
} from "lucide-react";
import { DashboardHeader } from "@/components/dashboard/header";
import { StatsCards } from "@/components/dashboard/stats-cards";
import { TaskTable } from "@/components/dashboard/task-table";
import { TaskDetailPanel } from "@/components/dashboard/task-detail-panel";
import { Card, CardContent } from "@/components/ui/card";
import { fetchDashboardTasks, fetchTaskDetail } from "@/lib/harness-api";
import type { Task } from "@/lib/types";

type DashboardView = "tasks" | "verification" | "reconciliation" | "reviews";

interface TaskBrowserProps {
  view: DashboardView;
}

interface FocusStat {
  label: string;
  value: number;
  icon: React.ElementType;
  tone: "success" | "warning" | "destructive" | "info";
}

const toneClassNames: Record<FocusStat["tone"], string> = {
  success: "text-success",
  warning: "text-warning",
  destructive: "text-destructive",
  info: "text-info",
};

const viewConfig: Record<
  DashboardView,
  {
    title: string;
    description: string;
    emptyTitle: string;
    emptyDescription: string;
    filterTask: (task: Task) => boolean;
    getStats?: (tasks: Task[]) => FocusStat[];
  }
> = {
  tasks: {
    title: "Task Overview",
    description:
      "Monitor AI-driven work verification and reconciliation status.",
    emptyTitle: "No tasks returned",
    emptyDescription:
      "Harness did not return any tasks from the configured backend.",
    filterTask: () => true,
  },
  verification: {
    title: "Verification",
    description:
      "Review completion acceptance, evidence sufficiency, and pending verification states.",
    emptyTitle: "No verification records returned",
    emptyDescription:
      "Harness did not return any tasks with verification context yet.",
    filterTask: (task) =>
      task.verification_summary !== null ||
      task.current_status === "executing" ||
      task.current_status === "completed",
    getStats: (tasks) => [
      {
        label: "Accepted",
        value: tasks.filter(
          (task) => task.verification_summary?.result === "accepted",
        ).length,
        icon: CheckCircle2,
        tone: "success",
      },
      {
        label: "Pending",
        value: tasks.filter((task) => {
          const result = task.verification_summary?.result;
          return result === "pending" || result === "deferred" || result === null;
        }).length,
        icon: Clock3,
        tone: "info",
      },
      {
        label: "Insufficient",
        value: tasks.filter(
          (task) =>
            task.verification_summary?.result === "insufficient_evidence",
        ).length,
        icon: AlertTriangle,
        tone: "warning",
      },
      {
        label: "Rejected",
        value: tasks.filter(
          (task) => task.verification_summary?.result === "rejected",
        ).length,
        icon: XCircle,
        tone: "destructive",
      },
    ],
  },
  reconciliation: {
    title: "Reconciliation",
    description:
      "Inspect cross-system alignment between Harness, GitHub, and upstream sources.",
    emptyTitle: "No reconciliation results returned",
    emptyDescription:
      "Harness did not return any tasks with reconciliation summaries yet.",
    filterTask: (task) => task.reconciliation_summary !== null,
    getStats: (tasks) => [
      {
        label: "Aligned",
        value: tasks.filter(
          (task) => task.reconciliation_summary?.result === "no_mismatch",
        ).length,
        icon: CheckCircle2,
        tone: "success",
      },
      {
        label: "Pending",
        value: tasks.filter(
          (task) => task.reconciliation_summary?.result === "pending",
        ).length,
        icon: Clock3,
        tone: "info",
      },
      {
        label: "Stale Evidence",
        value: tasks.filter(
          (task) => task.reconciliation_summary?.result === "stale_evidence",
        ).length,
        icon: AlertTriangle,
        tone: "warning",
      },
      {
        label: "Contradictions",
        value: tasks.filter((task) => {
          const result = task.reconciliation_summary?.result;
          return (
            result === "contradictory_facts" || result === "wrong_target"
          );
        }).length,
        icon: GitCompare,
        tone: "destructive",
      },
    ],
  },
  reviews: {
    title: "Reviews",
    description:
      "Track tasks that require manual review and the latest review decisions.",
    emptyTitle: "No reviews returned",
    emptyDescription:
      "Harness did not return any tasks with manual review activity yet.",
    filterTask: (task) =>
      task.review_summary.status !== "none" ||
      task.review_summary.request_count > 0 ||
      task.review_summary.decision_count > 0,
    getStats: (tasks) => [
      {
        label: "Review Required",
        value: tasks.filter(
          (task) => task.review_summary.status === "requested",
        ).length,
        icon: AlertTriangle,
        tone: "warning",
      },
      {
        label: "Resolved",
        value: tasks.filter(
          (task) => task.review_summary.status === "resolved",
        ).length,
        icon: UserCheck,
        tone: "success",
      },
      {
        label: "Requests",
        value: tasks.reduce(
          (total, task) => total + task.review_summary.request_count,
          0,
        ),
        icon: Search,
        tone: "info",
      },
      {
        label: "Decisions",
        value: tasks.reduce(
          (total, task) => total + task.review_summary.decision_count,
          0,
        ),
        icon: CheckCircle2,
        tone: "info",
      },
    ],
  },
};

export function TaskBrowser({ view }: TaskBrowserProps) {
  const config = viewConfig[view];
  const [tasks, setTasks] = useState<Task[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [isDetailExpanded, setIsDetailExpanded] = useState(false);
  const [isLoadingTasks, setIsLoadingTasks] = useState(true);
  const [isLoadingTaskDetail, setIsLoadingTaskDetail] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);

  useEffect(() => {
    const initialTaskId = new URLSearchParams(window.location.search).get("task");
    if (initialTaskId) {
      setSelectedTaskId(initialTaskId);
    }
  }, []);

  useEffect(() => {
    const url = new URL(window.location.href);
    if (selectedTaskId) {
      url.searchParams.set("task", selectedTaskId);
    } else {
      url.searchParams.delete("task");
    }
    window.history.replaceState({}, "", url);
  }, [selectedTaskId]);

  const scopedTasks = useMemo(
    () => tasks.filter((task) => config.filterTask(task)),
    [config, tasks],
  );

  const filteredTasks = useMemo(() => {
    const normalizedQuery = searchQuery.trim().toLowerCase();
    if (!normalizedQuery) {
      return scopedTasks;
    }

    return scopedTasks.filter(
      (task) =>
        task.title.toLowerCase().includes(normalizedQuery) ||
        task.task_id.toLowerCase().includes(normalizedQuery) ||
        task.origin.source_id.toLowerCase().includes(normalizedQuery),
    );
  }, [scopedTasks, searchQuery]);

  useEffect(() => {
    if (!selectedTaskId) {
      setSelectedTask(null);
      setDetailError(null);
      return;
    }

    if (!scopedTasks.some((task) => task.task_id === selectedTaskId)) {
      setSelectedTaskId(null);
      setSelectedTask(null);
      setDetailError(null);
    }
  }, [scopedTasks, selectedTaskId]);

  useEffect(() => {
    let cancelled = false;

    async function loadTasks() {
      setIsLoadingTasks(true);
      setLoadError(null);
      try {
        const result = await fetchDashboardTasks();
        if (cancelled) {
          return;
        }

        setTasks(result.tasks);
        setSelectedTask((currentSelectedTask) => {
          if (!currentSelectedTask) {
            return currentSelectedTask;
          }

          return (
            result.tasks.find((task) => task.task_id === currentSelectedTask.task_id) ??
            currentSelectedTask
          );
        });
      } catch (error) {
        if (!cancelled) {
          setLoadError(
            error instanceof Error
              ? error.message
              : "Tasks could not be loaded from Harness.",
          );
        }
      } finally {
        if (!cancelled) {
          setIsLoadingTasks(false);
        }
      }
    }

    void loadTasks();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    if (!selectedTaskId) {
      return;
    }
    const taskId = selectedTaskId;

    async function loadTaskDetail() {
      setIsLoadingTaskDetail(true);
      setDetailError(null);
      try {
        const task = await fetchTaskDetail(taskId);
        if (cancelled) {
          return;
        }

        startTransition(() => {
          setSelectedTask(task);
          setTasks((currentTasks) =>
            currentTasks.map((currentTask) =>
              currentTask.task_id === task.task_id ? task : currentTask,
            ),
          );
        });
      } catch (error) {
        if (!cancelled) {
          setDetailError(
            error instanceof Error
              ? error.message
              : "Task detail could not be loaded.",
          );
        }
      } finally {
        if (!cancelled) {
          setIsLoadingTaskDetail(false);
        }
      }
    }

    void loadTaskDetail();

    return () => {
      cancelled = true;
    };
  }, [selectedTaskId]);

  const selectedTaskForPanel =
    selectedTaskId && selectedTask?.task_id === selectedTaskId
      ? selectedTask
      : scopedTasks.find((task) => task.task_id === selectedTaskId) ?? null;

  const focusStats = config.getStats?.(scopedTasks) ?? [];

  async function handleRefresh() {
    setIsLoadingTasks(true);
    setLoadError(null);
    try {
      const result = await fetchDashboardTasks();
      setTasks(result.tasks);
    } catch (error) {
      setLoadError(
        error instanceof Error
          ? error.message
          : "Tasks could not be loaded from Harness.",
      );
    } finally {
      setIsLoadingTasks(false);
    }
  }

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <DashboardHeader />

      <div className="flex-1 flex overflow-hidden">
        <main
          className={`flex-1 overflow-y-auto transition-all duration-300 ${
            selectedTaskForPanel ? "lg:mr-[480px]" : ""
          }`}
        >
          <div className="p-6 max-w-7xl mx-auto space-y-6">
            <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
              <div>
                <div className="flex items-center gap-2">
                  {view === "verification" && (
                    <ShieldCheck className="h-5 w-5 text-info" />
                  )}
                  {view === "reconciliation" && (
                    <GitCompare className="h-5 w-5 text-info" />
                  )}
                  {view === "reviews" && (
                    <UserCheck className="h-5 w-5 text-info" />
                  )}
                  <h1 className="text-2xl font-semibold text-foreground">
                    {config.title}
                  </h1>
                </div>
                <p className="text-sm text-muted-foreground mt-1">
                  {config.description}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => void handleRefresh()}
                  disabled={isLoadingTasks}
                  className="flex h-9 items-center gap-2 rounded-md border border-border bg-card px-3 text-sm text-muted-foreground hover:bg-muted hover:text-foreground transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
                >
                  <RefreshCw
                    className={`h-4 w-4 ${isLoadingTasks ? "animate-spin" : ""}`}
                  />
                  <span className="hidden sm:inline">
                    {isLoadingTasks ? "Refreshing" : "Refresh"}
                  </span>
                </button>
              </div>
            </div>

            {view === "tasks" ? (
              <StatsCards tasks={filteredTasks} />
            ) : (
              <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
                {focusStats.map((stat) => (
                  <Card key={stat.label}>
                    <CardContent className="p-4">
                      <div className="flex items-center justify-between">
                        <div>
                          <p className="text-xs text-muted-foreground">
                            {stat.label}
                          </p>
                          <p className="text-2xl font-semibold mt-1">
                            {stat.value}
                          </p>
                        </div>
                        <div
                          className={`flex h-10 w-10 items-center justify-center rounded-md bg-muted ${toneClassNames[stat.tone]}`}
                        >
                          <stat.icon className="h-5 w-5" />
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}

            <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <div className="relative flex-1 max-w-md">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <input
                  type="text"
                  placeholder="Search tasks by title, ID, or source..."
                  value={searchQuery}
                  onChange={(event) => setSearchQuery(event.target.value)}
                  className="w-full h-9 pl-9 pr-4 rounded-md border border-border bg-card text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 focus:ring-offset-background"
                />
              </div>
              <div className="flex items-center gap-2">
                <div className="flex h-9 items-center gap-2 rounded-md border border-border bg-card px-3 text-sm text-muted-foreground">
                  <Filter className="h-4 w-4" />
                  <span>{config.title}</span>
                </div>
                <div className="text-sm text-muted-foreground">
                  {filteredTasks.length} task{filteredTasks.length !== 1 ? "s" : ""}
                </div>
              </div>
            </div>

            {loadError ? (
              <Card className="border-destructive/40">
                <CardContent className="p-6">
                  <div className="flex items-start gap-3">
                    <AlertTriangle className="h-5 w-5 text-destructive shrink-0 mt-0.5" />
                    <div className="space-y-2">
                      <p className="text-sm font-medium text-foreground">
                        Harness data could not be loaded
                      </p>
                      <p className="text-sm text-muted-foreground">{loadError}</p>
                    </div>
                  </div>
                </CardContent>
              </Card>
            ) : isLoadingTasks ? (
              <div className="rounded-lg border border-border bg-card p-8 text-sm text-muted-foreground">
                Loading tasks from Harness...
              </div>
            ) : filteredTasks.length === 0 ? (
              <Card>
                <CardContent className="p-8">
                  <p className="text-sm font-medium text-foreground">
                    {searchQuery ? "No matching tasks found" : config.emptyTitle}
                  </p>
                  <p className="text-sm text-muted-foreground mt-1">
                    {searchQuery
                      ? "Try a different title, task ID, or source identifier."
                      : config.emptyDescription}
                  </p>
                </CardContent>
              </Card>
            ) : (
              <TaskTable
                tasks={filteredTasks}
                selectedTaskId={selectedTaskId}
                onSelectTask={setSelectedTaskId}
              />
            )}
          </div>
        </main>

        {selectedTaskForPanel && (
          <aside
            className={`fixed z-40 transition-all duration-300 ${
              isDetailExpanded
                ? "inset-0 top-14"
                : "right-0 top-14 bottom-0 w-full max-w-[480px] shadow-xl lg:shadow-none"
            }`}
          >
            <div className="h-full">
              {isLoadingTaskDetail ? (
                <div className="flex h-full items-center justify-center bg-card border-l border-border text-sm text-muted-foreground">
                  Loading task detail...
                </div>
              ) : detailError ? (
                <div className="flex h-full items-center justify-center bg-card border-l border-border p-6">
                  <div className="max-w-sm rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm">
                    <p className="font-medium text-foreground">
                      Task detail could not be loaded
                    </p>
                    <p className="mt-1 text-muted-foreground">{detailError}</p>
                  </div>
                </div>
              ) : (
                <TaskDetailPanel
                  task={selectedTaskForPanel}
                  onClose={() => {
                    setSelectedTaskId(null);
                    setIsDetailExpanded(false);
                  }}
                  isExpanded={isDetailExpanded}
                  onToggleExpand={() => setIsDetailExpanded((current) => !current)}
                />
              )}
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}
