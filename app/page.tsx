"use client";

import { useEffect, useState, startTransition } from "react";
import { DashboardHeader } from "@/components/dashboard/header";
import { TaskTable } from "@/components/dashboard/task-table";
import { TaskDetailPanel } from "@/components/dashboard/task-detail-panel";
import { StatsCards } from "@/components/dashboard/stats-cards";
import { fetchDashboardTasks, fetchTaskDetail } from "@/lib/harness-api";
import type { Task } from "@/lib/types";
import { Search, Filter, RefreshCw, AlertTriangle, Database } from "lucide-react";

export default function DashboardPage() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [isDetailExpanded, setIsDetailExpanded] = useState(false);
  const [isLoadingTasks, setIsLoadingTasks] = useState(true);
  const [isLoadingTaskDetail, setIsLoadingTaskDetail] = useState(false);
  const [dataMode, setDataMode] = useState<"live" | "mock">("mock");
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadTasks() {
      setIsLoadingTasks(true);
      const result = await fetchDashboardTasks();
      if (cancelled) {
        return;
      }

      setTasks(result.tasks);
      setDataMode(result.dataMode);
      setStatusMessage(result.message);

      if (!result.tasks.some((task) => task.task_id === selectedTaskId)) {
        setSelectedTaskId(null);
        setSelectedTask(null);
      }

      setIsLoadingTasks(false);
    }

    void loadTasks();

    return () => {
      cancelled = true;
    };
  }, [selectedTaskId]);

  useEffect(() => {
    if (!selectedTaskId) {
      setSelectedTask(null);
      setDetailError(null);
      return;
    }

    if (dataMode === "mock") {
      setSelectedTask(tasks.find((task) => task.task_id === selectedTaskId) ?? null);
      setDetailError(null);
    }
  }, [dataMode, selectedTaskId, tasks]);

  useEffect(() => {
    let cancelled = false;

    if (!selectedTaskId || dataMode !== "live") {
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
  }, [dataMode, selectedTaskId]);

  const filteredTasks = tasks.filter(
    (task) =>
      task.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      task.task_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      task.origin.source_id.toLowerCase().includes(searchQuery.toLowerCase()),
  );

  const selectedTaskForPanel =
    selectedTaskId && selectedTask?.task_id === selectedTaskId
      ? selectedTask
      : tasks.find((task) => task.task_id === selectedTaskId) ?? null;

  async function handleRefresh() {
    setIsLoadingTasks(true);
    const result = await fetchDashboardTasks();
    setTasks(result.tasks);
    setDataMode(result.dataMode);
    setStatusMessage(result.message);
    setIsLoadingTasks(false);
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
                <h1 className="text-2xl font-semibold text-foreground">
                  Task Overview
                </h1>
                <p className="text-sm text-muted-foreground mt-1">
                  Monitor AI-driven work verification and reconciliation status
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

            {statusMessage && (
              <div
                className={`flex items-start gap-3 rounded-lg border px-4 py-3 text-sm ${
                  dataMode === "live"
                    ? "border-info/30 bg-info/5 text-foreground"
                    : "border-warning/30 bg-warning/10 text-foreground"
                }`}
              >
                {dataMode === "live" ? (
                  <Database className="h-4 w-4 mt-0.5 text-info shrink-0" />
                ) : (
                  <AlertTriangle className="h-4 w-4 mt-0.5 text-warning shrink-0" />
                )}
                <div>
                  <p className="font-medium">
                    {dataMode === "live"
                      ? "Live Harness data"
                      : "Sample dashboard data"}
                  </p>
                  <p className="text-muted-foreground">{statusMessage}</p>
                </div>
              </div>
            )}

            <StatsCards tasks={filteredTasks} />

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
                <button className="flex h-9 items-center gap-2 rounded-md border border-border bg-card px-3 text-sm text-muted-foreground hover:bg-muted hover:text-foreground transition-colors">
                  <Filter className="h-4 w-4" />
                  <span>Filter</span>
                </button>
                <div className="text-sm text-muted-foreground">
                  {filteredTasks.length} task{filteredTasks.length !== 1 ? "s" : ""}
                </div>
              </div>
            </div>

            {isLoadingTasks ? (
              <div className="rounded-lg border border-border bg-card p-8 text-sm text-muted-foreground">
                Loading tasks from Harness...
              </div>
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
              {isLoadingTaskDetail && dataMode === "live" ? (
                <div className="flex h-full items-center justify-center bg-card border-l border-border text-sm text-muted-foreground">
                  Loading task detail...
                </div>
              ) : detailError ? (
                <div className="flex h-full items-center justify-center bg-card border-l border-border p-6 text-center text-sm text-muted-foreground">
                  {detailError}
                </div>
              ) : (
                <TaskDetailPanel
                  task={selectedTaskForPanel}
                  onClose={() => {
                    setSelectedTaskId(null);
                    setIsDetailExpanded(false);
                    setDetailError(null);
                  }}
                  isExpanded={isDetailExpanded}
                  onToggleExpand={() => setIsDetailExpanded(!isDetailExpanded)}
                />
              )}
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}
