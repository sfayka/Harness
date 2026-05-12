"use client";

import { useState } from "react";
import {
  Activity,
  CheckCircle2,
  CircleDot,
  FileCheck2,
  GitPullRequest,
  LockKeyhole,
  Network,
  RadioTower,
  ShieldCheck,
  Split,
} from "lucide-react";

const stages = [
  {
    label: "Intent",
    detail: "Linear issue and user objective normalized",
    state: "locked",
    icon: FileCheck2,
  },
  {
    label: "TaskEnvelope",
    detail: "Canonical work contract created",
    state: "active",
    icon: CircleDot,
  },
  {
    label: "Agent Claim",
    detail: "Completion report received as advisory input",
    state: "held",
    icon: RadioTower,
  },
  {
    label: "Evidence",
    detail: "Commits, PRs, tests, and artifacts checked",
    state: "active",
    icon: GitPullRequest,
  },
  {
    label: "Reconcile",
    detail: "GitHub and Linear facts compared",
    state: "active",
    icon: Split,
  },
  {
    label: "Review Gate",
    detail: "Manual review stays sticky until resolved",
    state: "watch",
    icon: LockKeyhole,
  },
  {
    label: "Accepted",
    detail: "Lifecycle transition is evidence-backed",
    state: "passed",
    icon: CheckCircle2,
  },
];

const mapNodes = [
  { id: "intent", label: "Intent", detail: "Linear issue + objective", x: 0, y: 0, state: "active" },
  { id: "contract", label: "TaskEnvelope", detail: "Canonical contract", x: 232, y: 0, state: "active" },
  { id: "claim", label: "Agent Claim", detail: "Advisory done signal", x: 464, y: 0, state: "held" },
  { id: "evidence", label: "Evidence Bus", detail: "PRs, commits, tests", x: 696, y: 0, state: "active" },
  { id: "reconcile", label: "Reconcile", detail: "GitHub + Linear facts", x: 696, y: 222, state: "active" },
  { id: "review", label: "Review Gate", detail: "Sticky manual hold", x: 464, y: 222, state: "watch" },
  { id: "accepted", label: "Accepted", detail: "Proof-backed lifecycle", x: 232, y: 222, state: "passed" },
];

const auditEvents = [
  "task.created",
  "claim.received",
  "evidence.validated",
  "reconciliation.passed",
  "policy.accepted",
];

const scenarioRows = [
  {
    name: "Accepted completion",
    evidence: "4 artifacts",
    reconciliation: "no mismatch",
    outcome: "accepted",
  },
  {
    name: "Missing PR proof",
    evidence: "insufficient",
    reconciliation: "pending",
    outcome: "review required",
  },
  {
    name: "Wrong target branch",
    evidence: "present",
    reconciliation: "mismatch",
    outcome: "blocked",
  },
];

export default function AcceptanceCircuitDemoPage() {
  const [variant, setVariant] = useState<"circuit" | "lab">("circuit");

  return (
    <main className="min-h-screen bg-[#080b0e] text-slate-100">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 px-4 py-5 sm:px-6 lg:px-8">
        <header className="flex flex-col gap-4 border-b border-white/10 pb-5 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-cyan-300/80">
              Proofline demo prototype
            </p>
            <h1 className="mt-2 max-w-3xl text-3xl font-semibold tracking-tight text-white sm:text-5xl">
              Two visual directions for the acceptance circuit
            </h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-400 sm:text-base">
              Both concepts show the same thing: an agent claim is held until
              intent, evidence, reconciliation, lifecycle policy, and review
              gates complete the circuit.
            </p>
          </div>
          <div className="grid w-full max-w-md grid-cols-2 gap-2 rounded-lg border border-white/10 bg-white/[0.04] p-1">
            <button
              type="button"
              className={tabClass(variant === "circuit")}
              onClick={() => setVariant("circuit")}
            >
              <Network className="h-4 w-4" />
              Circuit Board
            </button>
            <button
              type="button"
              className={tabClass(variant === "lab")}
              onClick={() => setVariant("lab")}
            >
              <ShieldCheck className="h-4 w-4" />
              Evidence Lab
            </button>
          </div>
        </header>

        {variant === "circuit" ? <CircuitBoardVersion /> : <EvidenceLabVersion />}
      </div>
    </main>
  );
}

function CircuitBoardVersion() {
  return (
    <section className="overflow-hidden rounded-lg border border-cyan-300/20 bg-[#071014] shadow-2xl shadow-cyan-950/40">
      <div className="relative min-h-[760px] bg-[radial-gradient(circle_at_20%_18%,rgba(34,211,238,0.14),transparent_28%),linear-gradient(90deg,rgba(255,255,255,0.035)_1px,transparent_1px),linear-gradient(180deg,rgba(255,255,255,0.035)_1px,transparent_1px)] bg-[length:auto,28px_28px,28px_28px] p-5 sm:p-8">
        <div className="relative z-10 flex flex-col gap-8">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <h2 className="text-2xl font-semibold tracking-tight text-white">
                Version A: Acceptance Circuit
              </h2>
              <p className="mt-1 max-w-2xl text-sm text-slate-400">
                Dark infrastructure board. The drama comes from current
                flowing through real acceptance checks.
              </p>
            </div>
            <div className="flex items-center gap-2 rounded-md border border-cyan-300/20 bg-cyan-300/10 px-3 py-2 text-xs font-medium uppercase tracking-[0.18em] text-cyan-200">
              <Activity className="h-4 w-4" />
              Replay / read-only
            </div>
          </div>

          <div className="space-y-4">
            <div className="acceptance-map relative h-[560px] overflow-hidden rounded-lg border border-cyan-300/20 bg-black/25 p-4">
              <div className="flow-arrow horizontal right" style={{ left: "calc(var(--map-left) + 177px)", top: "calc(var(--map-top) + 75px)" }} />
              <div className="flow-arrow horizontal right" style={{ left: "calc(var(--map-left) + 409px)", top: "calc(var(--map-top) + 75px)" }} />
              <div className="flow-arrow horizontal right" style={{ left: "calc(var(--map-left) + 641px)", top: "calc(var(--map-top) + 75px)" }} />
              <div className="flow-arrow vertical down" style={{ left: "calc(var(--map-left) + 776px)", top: "calc(var(--map-top) + 162px)" }} />
              <div className="flow-arrow horizontal left" style={{ left: "calc(var(--map-left) + 641px)", top: "calc(var(--map-top) + 297px)" }} />
              <div className="flow-arrow horizontal left" style={{ left: "calc(var(--map-left) + 409px)", top: "calc(var(--map-top) + 297px)" }} />
              <div className="flow-arrow vertical up amber" style={{ left: "calc(var(--map-left) + 544px)", top: "calc(var(--map-top) + 172px)" }} />
              <div className="absolute z-20 rounded-md border border-cyan-200/40 bg-cyan-200 px-3 py-1.5 font-mono text-xs font-semibold text-slate-950 shadow-[0_0_28px_rgba(103,232,249,0.65)] motion-safe:animate-[payload-map_12s_cubic-bezier(.65,0,.35,1)_infinite]" style={{ left: "calc(var(--map-left) + 80px)", top: "calc(var(--map-top) + 75px)" }}>
                claim packet
              </div>
              {mapNodes.map((node, index) => (
                <MapNode key={node.id} node={node} index={index} />
              ))}
            </div>

            <aside className="rounded-lg border border-white/10 bg-black/30 p-3">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
                <h3 className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-300">
                  Audit ticks
                </h3>
                <div className="flex flex-wrap gap-2">
                  {auditEvents.map((event, index) => (
                    <div
                      key={event}
                      className="flex items-center gap-2 rounded-md border border-white/10 bg-white/[0.03] px-3 py-2"
                    >
                      <span className="flex h-6 w-6 items-center justify-center rounded bg-cyan-300/10 text-[11px] font-semibold text-cyan-200">
                        {index + 1}
                      </span>
                      <span className="font-mono text-xs text-slate-300">
                        {event}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </aside>
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            {scenarioRows.map((row) => (
              <div
                key={row.name}
                className="rounded-lg border border-white/10 bg-black/25 p-4"
              >
                <p className="text-sm font-semibold text-white">{row.name}</p>
                <dl className="mt-4 grid grid-cols-2 gap-3 text-xs">
                  <div>
                    <dt className="uppercase tracking-[0.16em] text-slate-500">
                      Evidence
                    </dt>
                    <dd className="mt-1 font-mono text-slate-200">
                      {row.evidence}
                    </dd>
                  </div>
                  <div>
                    <dt className="uppercase tracking-[0.16em] text-slate-500">
                      Outcome
                    </dt>
                    <dd className={outcomeClass(row.outcome)}>
                      {row.outcome}
                    </dd>
                  </div>
                </dl>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function EvidenceLabVersion() {
  return (
    <section className="overflow-hidden rounded-lg bg-[#eef2f4] text-slate-950">
      <div className="grid min-h-[720px] gap-0 lg:grid-cols-[340px_1fr]">
        <aside className="border-r border-slate-300/80 bg-[#dfe7ea] p-6">
          <div className="flex h-full flex-col justify-between gap-8">
            <div>
              <h2 className="text-2xl font-semibold tracking-tight">
                Version B: Evidence Lab
              </h2>
              <p className="mt-3 text-sm leading-6 text-slate-600">
                Brighter, more forensic. The UI feels like a validation lab
                where each artifact is inspected before acceptance is released.
              </p>
              <div className="mt-6 rounded-md border border-slate-300 bg-white/70 p-4">
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                  Current replay
                </p>
                <p className="mt-2 text-lg font-semibold">
                  Agent claim under review
                </p>
                <p className="mt-1 font-mono text-xs text-slate-500">
                  task-kno-demo-acceptance
                </p>
              </div>
            </div>
            <div className="rounded-md bg-slate-950 p-4 text-slate-100">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-200">
                Design intent
              </p>
              <p className="mt-2 text-sm leading-6 text-slate-300">
                Less cinematic than Version A, more credible for regulated
                enterprise buyers who want proof paths and auditability.
              </p>
            </div>
          </div>
        </aside>

        <div className="p-5 sm:p-8">
          <div className="flex flex-col gap-4 border-b border-slate-300 pb-5 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">
                Read-only visual replay
              </p>
              <h3 className="mt-2 text-3xl font-semibold tracking-tight">
                Acceptance dossier
              </h3>
            </div>
            <div className="flex items-center gap-2 rounded-md border border-emerald-700/30 bg-emerald-600/10 px-3 py-2 text-sm font-semibold text-emerald-800">
              <CheckCircle2 className="h-4 w-4" />
              Proof-backed path
            </div>
          </div>

          <div className="mt-6 grid gap-5 xl:grid-cols-[1fr_320px]">
            <div className="space-y-3">
              {stages.map((stage, index) => (
                <LabStep key={stage.label} stage={stage} index={index} />
              ))}
            </div>
            <div className="space-y-4">
              <div className="rounded-lg border border-slate-300 bg-white p-5 shadow-sm">
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                  Outcome split
                </p>
                <div className="mt-5 space-y-3">
                  {["accepted", "review required", "blocked"].map((outcome) => (
                    <div
                      key={outcome}
                      className="flex items-center justify-between border-b border-slate-100 pb-3 last:border-0 last:pb-0"
                    >
                      <span className="text-sm font-medium capitalize">
                        {outcome}
                      </span>
                      <span className={labOutcomeClass(outcome)}>
                        {outcome === "accepted" ? "clear" : "divert"}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
              <div className="rounded-lg border border-slate-300 bg-white p-5 shadow-sm">
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                  Timeline
                </p>
                <div className="mt-4 space-y-3">
                  {auditEvents.map((event) => (
                    <div key={event} className="flex items-start gap-3">
                      <span className="mt-1 h-2 w-2 rounded-full bg-slate-950" />
                      <span className="font-mono text-xs text-slate-600">
                        {event}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function MapNode({
  node,
  index,
}: {
  node: (typeof mapNodes)[number];
  index: number;
}) {
  const isAccepted = node.state === "passed";
  const isHeld = node.state === "held" || node.state === "watch";

  return (
    <div
      className={`absolute z-10 h-[150px] w-[160px] overflow-hidden rounded-lg border p-4 after:pointer-events-none after:absolute after:inset-[-1px] after:rounded-lg after:border after:border-transparent after:opacity-0 after:content-[''] ${
        isAccepted
          ? `${nodePulseClass(index)} border-emerald-300/50 bg-emerald-300/10`
          : isHeld
            ? `${nodePulseClass(index)} border-amber-300/45 bg-amber-300/10`
            : `${nodePulseClass(index)} border-cyan-300/30 bg-cyan-300/[0.06]`
      }`}
      style={{
        left: `calc(var(--map-left) + ${node.x}px)`,
        top: `calc(var(--map-top) + ${node.y}px)`,
      }}
    >
      <div className="flex items-start justify-between gap-3">
        <div
          className={`flex h-8 w-8 items-center justify-center rounded-md border ${
            isAccepted
              ? "border-emerald-200/50 text-emerald-200"
              : isHeld
                ? "border-amber-200/50 text-amber-200"
                : "border-cyan-200/50 text-cyan-200"
          }`}
        >
          <CircleDot className="h-4 w-4" />
        </div>
        <span className="font-mono text-xs text-slate-500">
          {String(index + 1).padStart(2, "0")}
        </span>
      </div>
      <h3 className="mt-3 text-sm font-semibold text-white">{node.label}</h3>
      <p className="mt-1 text-xs leading-5 text-slate-400">{node.detail}</p>
    </div>
  );
}

function LabStep({
  stage,
  index,
}: {
  stage: (typeof stages)[number];
  index: number;
}) {
  const Icon = stage.icon;
  const isAccepted = stage.state === "passed";
  const isReview = stage.state === "held" || stage.state === "watch";

  return (
    <div className="grid gap-3 rounded-lg border border-slate-300 bg-white p-4 shadow-sm sm:grid-cols-[52px_1fr_auto] sm:items-center">
      <div
        className={`flex h-12 w-12 items-center justify-center rounded-md ${
          isAccepted
            ? "bg-emerald-100 text-emerald-800"
            : isReview
              ? "bg-amber-100 text-amber-800"
              : "bg-cyan-100 text-cyan-800"
        }`}
      >
        <Icon className="h-5 w-5" />
      </div>
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-xs text-slate-400">
            {String(index + 1).padStart(2, "0")}
          </span>
          <h4 className="font-semibold">{stage.label}</h4>
        </div>
        <p className="mt-1 text-sm text-slate-600">{stage.detail}</p>
      </div>
      <span
        className={`w-fit rounded px-2.5 py-1 font-mono text-xs ${
          isAccepted
            ? "bg-emerald-100 text-emerald-800"
            : isReview
              ? "bg-amber-100 text-amber-800"
              : "bg-slate-100 text-slate-600"
        }`}
      >
        {stage.state}
      </span>
    </div>
  );
}

function tabClass(active: boolean) {
  return `flex items-center justify-center gap-2 rounded-md px-3 py-2 text-sm font-semibold transition ${
    active
      ? "bg-white text-slate-950"
      : "text-slate-400 hover:bg-white/5 hover:text-white"
  }`;
}

function nodePulseClass(index: number) {
  const classes = [
    "after:motion-safe:animate-[node-pulse-1_12s_linear_infinite]",
    "after:motion-safe:animate-[node-pulse-2_12s_linear_infinite]",
    "after:motion-safe:animate-[node-pulse-3_12s_linear_infinite]",
    "after:motion-safe:animate-[node-pulse-4_12s_linear_infinite]",
    "after:motion-safe:animate-[node-pulse-5_12s_linear_infinite]",
    "after:motion-safe:animate-[node-pulse-6_12s_linear_infinite]",
    "after:motion-safe:animate-[node-pulse-7_12s_linear_infinite]",
    "after:motion-safe:animate-[node-pulse-8_12s_linear_infinite]",
  ];

  return classes[index] ?? "after:motion-safe:animate-[node-pulse-1_12s_linear_infinite]";
}

function outcomeClass(outcome: string) {
  if (outcome === "accepted") {
    return "mt-1 font-mono text-emerald-300";
  }
  if (outcome === "blocked") {
    return "mt-1 font-mono text-red-300";
  }
  return "mt-1 font-mono text-amber-300";
}

function labOutcomeClass(outcome: string) {
  if (outcome === "accepted") {
    return "rounded bg-emerald-100 px-2 py-1 font-mono text-xs text-emerald-800";
  }
  if (outcome === "blocked") {
    return "rounded bg-red-100 px-2 py-1 font-mono text-xs text-red-800";
  }
  return "rounded bg-amber-100 px-2 py-1 font-mono text-xs text-amber-800";
}
