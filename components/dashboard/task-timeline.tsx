import type { TimelineEvent } from "@/lib/types";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { formatDateTime } from "@/lib/utils";
import {
  History,
  Plus,
  ArrowRight,
  Package,
  ClipboardCheck,
  AlertCircle,
  CheckCircle2,
} from "lucide-react";

interface TaskTimelineProps {
  events: TimelineEvent[];
}

export function TaskTimeline({ events }: TaskTimelineProps) {
  if (events.length === 0) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2">
            <History className="h-4 w-4 text-muted-foreground" />
            Timeline
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">No events recorded yet.</p>
        </CardContent>
      </Card>
    );
  }

  // Sort events chronologically (oldest first for display)
  const sortedEvents = [...events].sort(
    (a, b) => new Date(a.occurred_at).getTime() - new Date(b.occurred_at).getTime()
  );

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2">
          <History className="h-4 w-4 text-muted-foreground" />
          Timeline
          <span className="text-xs font-normal text-muted-foreground">
            ({events.length} events)
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="relative">
          {/* Timeline line */}
          <div className="absolute left-[11px] top-2 bottom-2 w-px bg-border" />

          {/* Events */}
          <div className="space-y-4">
            {sortedEvents.map((event) => (
              <TimelineEventItem key={event.event_id} event={event} />
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function TimelineEventItem({ event }: { event: TimelineEvent }) {
  const config = getEventConfig(event.event_type);
  const pullRequestNumber =
    typeof event.details.pull_request_number === "number"
      ? event.details.pull_request_number
      : null;
  const commitSha =
    typeof event.details.commit_sha === "string"
      ? event.details.commit_sha
      : null;
  const reviewOutcome =
    typeof event.details.outcome === "string" ? event.details.outcome : null;
  const requiresReview = event.details.requires_review === true;

  return (
    <div className="relative flex gap-3 pl-1">
      {/* Icon */}
      <div
        className={`relative z-10 flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${config.bgColor} ${config.iconColor}`}
      >
        <config.icon className="h-3 w-3" />
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0 pt-0.5">
        <div className="flex items-baseline justify-between gap-2">
          <p className="text-sm font-medium text-foreground">{event.summary}</p>
          <span className="text-xs text-muted-foreground whitespace-nowrap">
            {formatDateTime(event.occurred_at)}
          </span>
        </div>
        <div className="flex items-center gap-2 mt-0.5">
          <span className="text-xs text-muted-foreground">
            Source: {event.source}
          </span>
        </div>

        {/* Details based on event type */}
        {event.event_type === "status_transition" && event.details && (
          <div className="mt-1.5 inline-flex items-center gap-1.5 text-xs">
            <span className="px-1.5 py-0.5 rounded bg-muted font-mono">
              {String(event.details.from_status)}
            </span>
            <ArrowRight className="h-3 w-3 text-muted-foreground" />
            <span className="px-1.5 py-0.5 rounded bg-muted font-mono">
              {String(event.details.to_status)}
            </span>
          </div>
        )}

        {event.event_type === "artifact_captured" && event.details && (
          <div className="mt-1.5 text-xs text-muted-foreground">
            Type: {String(event.details.type)}
            {pullRequestNumber !== null && (
              <span className="ml-2">PR #{String(pullRequestNumber)}</span>
            )}
            {commitSha && (
              <span className="ml-2 font-mono">{commitSha}</span>
            )}
          </div>
        )}

        {event.event_type === "evaluation_recorded" && event.details && (
          <div className="mt-1.5 text-xs">
            <span className="text-muted-foreground">Action: </span>
            <span className="font-mono">{String(event.details.action)}</span>
            {requiresReview && (
              <span className="ml-2 text-warning">Review Required</span>
            )}
          </div>
        )}

        {event.event_type === "review_requested" && event.details && (
          <div className="mt-1.5 p-2 rounded bg-warning/10 border border-warning/20">
            <p className="text-xs text-foreground">
              {String(event.details.reason)}
            </p>
          </div>
        )}

        {event.event_type === "review_decided" && event.details && (
          <div className="mt-1.5 text-xs">
            <span className="text-muted-foreground">Outcome: </span>
            <span
              className={`font-medium ${
                reviewOutcome === "approved"
                  ? "text-success"
                  : reviewOutcome === "rejected"
                    ? "text-destructive"
                    : "text-muted-foreground"
              }`}
            >
              {String(reviewOutcome)}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

function getEventConfig(eventType: TimelineEvent["event_type"]) {
  switch (eventType) {
    case "task_created":
      return {
        icon: Plus,
        bgColor: "bg-info/20",
        iconColor: "text-info",
      };
    case "status_transition":
      return {
        icon: ArrowRight,
        bgColor: "bg-muted",
        iconColor: "text-muted-foreground",
      };
    case "artifact_captured":
      return {
        icon: Package,
        bgColor: "bg-success/20",
        iconColor: "text-success",
      };
    case "evaluation_recorded":
      return {
        icon: ClipboardCheck,
        bgColor: "bg-info/20",
        iconColor: "text-info",
      };
    case "review_requested":
      return {
        icon: AlertCircle,
        bgColor: "bg-warning/20",
        iconColor: "text-warning",
      };
    case "review_decided":
      return {
        icon: CheckCircle2,
        bgColor: "bg-success/20",
        iconColor: "text-success",
      };
    default:
      return {
        icon: History,
        bgColor: "bg-muted",
        iconColor: "text-muted-foreground",
      };
  }
}
