"use client";

import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  Power,
  RefreshCw,
  Route,
  ShieldCheck,
} from "lucide-react";
import { DashboardHeader } from "@/components/dashboard/header";
import { Card, CardContent } from "@/components/ui/card";
import {
  fetchExecutionSubstrateHandoffs,
  fetchExecutionSubstrateTransportStatus,
} from "@/lib/harness-api";
import type {
  ExecutionSubstrateHandoffPreview,
  ExecutionSubstrateTransportStatus,
} from "@/lib/types";

export function ExecutionHandoffBrowser() {
  const [preview, setPreview] = useState<ExecutionSubstrateHandoffPreview | null>(null);
  const [transportStatus, setTransportStatus] =
    useState<ExecutionSubstrateTransportStatus | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const handoffs = useMemo(() => preview?.handoffs ?? [], [preview]);
  const safetyStats = useMemo(
    () => [
      {
        label: "Rendered Handoffs",
        value: handoffs.length,
        icon: Route,
        tone: "text-info",
      },
      {
        label: "Dispatch Disabled",
        value: transportStatus && !transportStatus.dispatch_enabled ? 1 : 0,
        icon: Ban,
        tone: "text-warning",
      },
      {
        label: "Harness Authority",
        value: transportStatus?.completion_authority === "harness_verification" ? 1 : 0,
        icon: ShieldCheck,
        tone: "text-success",
      },
      {
        label: "Live-Safe Payloads",
        value: handoffs.filter((entry) => entry.handoff.metadata.safe_to_execute_live).length,
        icon: Power,
        tone: "text-destructive",
      },
    ],
    [handoffs, transportStatus],
  );

  async function loadPreview() {
    setIsLoading(true);
    setLoadError(null);
    try {
      const [nextTransportStatus, nextPreview] = await Promise.all([
        fetchExecutionSubstrateTransportStatus(),
        fetchExecutionSubstrateHandoffs(),
      ]);
      setTransportStatus(nextTransportStatus);
      setPreview(nextPreview);
    } catch (error) {
      setLoadError(
        error instanceof Error
          ? error.message
          : "Execution substrate handoffs could not be loaded.",
      );
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    void loadPreview();
  }, []);

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <DashboardHeader />

      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-7xl space-y-6 p-6">
          <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <div>
              <div className="flex items-center gap-2">
                <Route className="h-5 w-5 text-info" />
                <h1 className="text-2xl font-semibold text-foreground">
                  Execution
                </h1>
              </div>
              <p className="mt-1 text-sm text-muted-foreground">
                Read-only preview of Symphony-compatible handoff payloads from the Harness supervision queue.
              </p>
            </div>
            <button
              onClick={() => void loadPreview()}
              disabled={isLoading}
              className="flex h-9 items-center gap-2 rounded-md border border-border bg-card px-3 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-60"
            >
              <RefreshCw className={`h-4 w-4 ${isLoading ? "animate-spin" : ""}`} />
              <span>{isLoading ? "Refreshing" : "Refresh"}</span>
            </button>
          </div>

          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            {safetyStats.map((stat) => (
              <Card key={stat.label}>
                <CardContent className="p-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-xs text-muted-foreground">{stat.label}</p>
                      <p className="mt-1 text-2xl font-semibold">{stat.value}</p>
                    </div>
                    <div
                      className={`flex h-10 w-10 items-center justify-center rounded-md bg-muted ${stat.tone}`}
                    >
                      <stat.icon className="h-5 w-5" />
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>

          <Card>
            <CardContent className="p-5">
              <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Power className="h-4 w-4 text-warning" />
                    <p className="text-sm font-medium text-foreground">
                      Transport Status
                    </p>
                    <span className="rounded-md bg-muted px-2 py-1 text-xs text-muted-foreground">
                      {transportStatus?.transport_status || "unknown"}
                    </span>
                  </div>
                  <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
                    {transportStatus?.message ||
                      "Harness has not returned execution transport posture yet."}
                  </p>
                </div>
                <div className="grid min-w-0 gap-3 sm:grid-cols-2 lg:min-w-[28rem]">
                  <PreviewField
                    label="Runner"
                    value={transportStatus?.preferred_runner || "unknown"}
                  />
                  <PreviewField
                    label="Live Dispatch"
                    value={transportStatus?.live_dispatch_enabled ? "enabled" : "disabled"}
                  />
                  <PreviewField
                    label="Authority"
                    value={transportStatus?.completion_authority || "unknown"}
                  />
                  <PreviewField
                    label="Event Contract"
                    value={transportStatus?.events_contract || "unknown"}
                  />
                </div>
              </div>
            </CardContent>
          </Card>

          {loadError ? (
            <Card className="border-destructive/40">
              <CardContent className="p-6">
                <div className="flex items-start gap-3">
                  <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" />
                  <div className="space-y-2">
                    <p className="text-sm font-medium text-foreground">
                      Execution handoffs could not be loaded
                    </p>
                    <p className="text-sm text-muted-foreground">{loadError}</p>
                  </div>
                </div>
              </CardContent>
            </Card>
          ) : isLoading ? (
            <div className="rounded-lg border border-border bg-card p-8 text-sm text-muted-foreground">
              Loading execution handoffs from Harness...
            </div>
          ) : handoffs.length === 0 ? (
            <Card>
              <CardContent className="p-8">
                <p className="text-sm font-medium text-foreground">
                  No execution handoffs returned
                </p>
                <p className="mt-1 text-sm text-muted-foreground">
                  Harness did not return any runner-facing handoff previews from the current supervision queue.
                </p>
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-3">
              {handoffs.map((entry) => (
                <Card key={`${entry.task_id}:${entry.handoff.intent.intent_type}`}>
                  <CardContent className="space-y-4 p-5">
                    <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                      <div>
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="font-mono text-sm font-semibold text-foreground">
                            {entry.task_id}
                          </p>
                          <span className="rounded-md bg-muted px-2 py-1 text-xs text-muted-foreground">
                            {entry.attention_type}
                          </span>
                          <span className="rounded-md bg-muted px-2 py-1 text-xs text-muted-foreground">
                            {entry.current_status}
                          </span>
                        </div>
                        <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
                          {entry.handoff.intent.reason}
                        </p>
                      </div>
                      <div className="flex items-center gap-2 rounded-md border border-border bg-muted px-3 py-2 text-xs text-muted-foreground">
                        <CheckCircle2 className="h-4 w-4 text-success" />
                        {entry.handoff.mode}
                      </div>
                    </div>

                    <div className="grid gap-3 md:grid-cols-3">
                      <PreviewField
                        label="Intent"
                        value={entry.handoff.intent.intent_type}
                      />
                      <PreviewField
                        label="Authority"
                        value={entry.handoff.harness_boundary.completion_authority}
                      />
                      <PreviewField
                        label="Callback"
                        value={entry.handoff.callback.events_endpoint}
                      />
                    </div>

                    <div className="rounded-md border border-border bg-muted/50 p-3">
                      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                        Runner Prohibitions
                      </p>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {entry.handoff.runner_policy.prohibited_actions.map((action) => (
                          <span
                            key={action}
                            className="rounded-md bg-background px-2 py-1 text-xs text-muted-foreground"
                          >
                            {action}
                          </span>
                        ))}
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

function PreviewField({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-md border border-border bg-muted/50 p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 truncate font-mono text-sm text-foreground" title={value}>
        {value || "none"}
      </p>
    </div>
  );
}
