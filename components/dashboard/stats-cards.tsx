import type { Task } from "@/lib/types";
import { Card, CardContent } from "@/components/ui/card";
import {
  ShieldCheck,
  XOctagon,
  AlertTriangle,
  Search,
  Clock,
} from "lucide-react";

interface StatsCardsProps {
  tasks: Task[];
}

export function StatsCards({ tasks }: StatsCardsProps) {
  // System truth states - derived from verification and reconciliation
  const stats = {
    // Verified & Accepted: completed + verification accepted + no reconciliation mismatches
    verifiedAccepted: tasks.filter(
      (t) =>
        t.current_status === "completed" &&
        t.verification_summary?.result === "accepted" &&
        (!t.reconciliation_summary ||
          t.reconciliation_summary.result === "no_mismatch")
    ).length,

    // Blocked (Unresolved Conditions): blocked status OR has unresolved dependencies
    blockedUnresolved: tasks.filter(
      (t) =>
        t.current_status === "blocked" ||
        (t.reconciliation_summary?.result === "stale_evidence")
    ).length,

    // Invalid / Contradicted: failed OR rejected verification OR contradictory reconciliation
    invalidContradicted: tasks.filter(
      (t) =>
        t.current_status === "failed" ||
        t.verification_summary?.result === "rejected" ||
        t.reconciliation_summary?.result === "contradictory_facts" ||
        t.reconciliation_summary?.result === "wrong_target"
    ).length,

    // Review Required: explicit review requested OR insufficient evidence
    reviewRequired: tasks.filter(
      (t) =>
        t.review_summary.status === "requested" ||
        t.verification_summary?.result === "insufficient_evidence"
    ).length,

    // Pending Verification: in progress states awaiting verification
    pendingVerification: tasks.filter(
      (t) =>
        (t.current_status === "executing" ||
          t.current_status === "completed") &&
        (!t.verification_summary ||
          t.verification_summary.result === "pending" ||
          t.verification_summary.result === "deferred")
    ).length,
  };

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
      <StatCard
        label="Verified & Accepted"
        value={stats.verifiedAccepted}
        icon={ShieldCheck}
        variant="success"
      />
      <StatCard
        label="Blocked"
        value={stats.blockedUnresolved}
        icon={AlertTriangle}
        variant="warning"
        sublabel="Unresolved Conditions"
      />
      <StatCard
        label="Invalid"
        value={stats.invalidContradicted}
        icon={XOctagon}
        variant="destructive"
        sublabel="Contradicted"
      />
      <StatCard
        label="Review Required"
        value={stats.reviewRequired}
        icon={Search}
        variant="warning"
      />
      <StatCard
        label="Pending Verification"
        value={stats.pendingVerification}
        icon={Clock}
        variant="info"
        className="col-span-2 md:col-span-1"
      />
    </div>
  );
}

interface StatCardProps {
  label: string;
  value: number;
  icon: React.ElementType;
  variant: "success" | "warning" | "destructive" | "info";
  sublabel?: string;
  className?: string;
}

function StatCard({
  label,
  value,
  icon: Icon,
  variant,
  sublabel,
  className,
}: StatCardProps) {
  const variantStyles = {
    success: "text-success",
    warning: "text-warning",
    destructive: "text-destructive",
    info: "text-info",
  };

  return (
    <Card className={className}>
      <CardContent className="p-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-xs text-muted-foreground">{label}</p>
            {sublabel && (
              <p className="text-[10px] text-muted-foreground/70">{sublabel}</p>
            )}
            <p className="text-2xl font-semibold mt-1">{value}</p>
          </div>
          <div
            className={`flex h-10 w-10 items-center justify-center rounded-md bg-muted ${variantStyles[variant]}`}
          >
            <Icon className="h-5 w-5" />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
