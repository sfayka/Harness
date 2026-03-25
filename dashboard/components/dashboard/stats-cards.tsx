import type { Task } from "@/lib/types";
import { Card, CardContent } from "@/components/ui/card";
import {
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Clock,
  ShieldAlert,
} from "lucide-react";

interface StatsCardsProps {
  tasks: Task[];
}

export function StatsCards({ tasks }: StatsCardsProps) {
  const stats = {
    completed: tasks.filter((t) => t.current_status === "completed").length,
    executing: tasks.filter((t) => t.current_status === "executing").length,
    blocked: tasks.filter((t) => t.current_status === "blocked").length,
    failed: tasks.filter((t) => t.current_status === "failed").length,
    reviewRequired: tasks.filter(
      (t) => t.review_summary.status === "requested"
    ).length,
  };

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
      <StatCard
        label="Completed"
        value={stats.completed}
        icon={CheckCircle2}
        variant="success"
      />
      <StatCard
        label="Executing"
        value={stats.executing}
        icon={Clock}
        variant="info"
      />
      <StatCard
        label="Blocked"
        value={stats.blocked}
        icon={AlertTriangle}
        variant="warning"
      />
      <StatCard
        label="Failed"
        value={stats.failed}
        icon={XCircle}
        variant="destructive"
      />
      <StatCard
        label="Review Required"
        value={stats.reviewRequired}
        icon={ShieldAlert}
        variant="warning"
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
  className?: string;
}

function StatCard({
  label,
  value,
  icon: Icon,
  variant,
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
