"use client";

import { useState } from "react";
import { mockTasks } from "@/lib/mock-data";
import { DashboardHeader } from "@/components/dashboard/header";
import { TaskTable } from "@/components/dashboard/task-table";
import { TaskDetailPanel } from "@/components/dashboard/task-detail-panel";
import { StatsCards } from "@/components/dashboard/stats-cards";
import { Search, Filter, RefreshCw } from "lucide-react";

export default function DashboardPage() {
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [isDetailExpanded, setIsDetailExpanded] = useState(false);

  const selectedTask = selectedTaskId
    ? mockTasks.find((t) => t.task_id === selectedTaskId)
    : null;

  const filteredTasks = mockTasks.filter(
    (task) =>
      task.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      task.task_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      task.origin.source_id.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <DashboardHeader />

      <div className="flex-1 flex overflow-hidden">
        {/* Main content area */}
        <main
          className={`flex-1 overflow-y-auto transition-all duration-300 ${
            selectedTask ? "lg:mr-[480px]" : ""
          }`}
        >
          <div className="p-6 max-w-7xl mx-auto space-y-6">
            {/* Page header */}
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
                <button className="flex h-9 items-center gap-2 rounded-md border border-border bg-card px-3 text-sm text-muted-foreground hover:bg-muted hover:text-foreground transition-colors">
                  <RefreshCw className="h-4 w-4" />
                  <span className="hidden sm:inline">Refresh</span>
                </button>
              </div>
            </div>

            {/* Stats */}
            <StatsCards tasks={mockTasks} />

            {/* Search and filters */}
            <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <div className="relative flex-1 max-w-md">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <input
                  type="text"
                  placeholder="Search tasks by title, ID, or source..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
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

            {/* Task table */}
            <TaskTable
              tasks={filteredTasks}
              selectedTaskId={selectedTaskId}
              onSelectTask={setSelectedTaskId}
            />
          </div>
        </main>

        {/* Detail panel (slide-in from right, or full-screen) */}
        {selectedTask && (
          <aside
            className={`fixed z-40 transition-all duration-300 ${
              isDetailExpanded
                ? "inset-0 top-14"
                : "right-0 top-14 bottom-0 w-full max-w-[480px] shadow-xl lg:shadow-none"
            }`}
          >
            <TaskDetailPanel
              task={selectedTask}
              onClose={() => {
                setSelectedTaskId(null);
                setIsDetailExpanded(false);
              }}
              isExpanded={isDetailExpanded}
              onToggleExpand={() => setIsDetailExpanded(!isDetailExpanded)}
            />
          </aside>
        )}
      </div>
    </div>
  );
}
