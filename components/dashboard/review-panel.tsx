import type { ReviewSummary } from "@/lib/types";
import { getSeverityClasses } from "@/lib/outcome-severity";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { StatusBadge } from "@/components/ui/status-badge";
import { formatDateTime } from "@/lib/utils";
import {
  UserCheck,
  AlertCircle,
  CheckCircle2,
  XCircle,
  Clock,
  User,
} from "lucide-react";

interface ReviewPanelProps {
  review: ReviewSummary;
}

export function ReviewPanel({ review }: ReviewPanelProps) {
  if (review.status === "none" && review.request_count === 0) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <UserCheck className="h-4 w-4 text-muted-foreground" />
              Manual Review
            </CardTitle>
            <StatusBadge status="none" variant="review" />
          </div>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            No manual review has been requested for this task.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <UserCheck className="h-4 w-4 text-muted-foreground" />
            Manual Review
          </CardTitle>
          <StatusBadge status={review.status} variant="review" />
        </div>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          {/* Summary */}
          <div className="flex items-center gap-4 text-sm">
            <div className="flex items-center gap-1.5">
              <AlertCircle className="h-4 w-4 text-muted-foreground" />
              <span className="text-muted-foreground">
                {review.request_count} request{review.request_count !== 1 ? "s" : ""}
              </span>
            </div>
            <div className="flex items-center gap-1.5">
              <CheckCircle2 className="h-4 w-4 text-muted-foreground" />
              <span className="text-muted-foreground">
                {review.decision_count} decision{review.decision_count !== 1 ? "s" : ""}
              </span>
            </div>
          </div>

          {/* Latest Request */}
          {review.latest_request && (
            <div className={`rounded-md border p-3 ${getSeverityClasses("warning").border}`}>
              <div className="flex items-center gap-2 mb-2">
                <AlertCircle className={`h-4 w-4 ${getSeverityClasses("warning").text}`} />
                <span className="text-sm font-medium text-foreground">
                  Review Requested
                </span>
              </div>
              <p className="text-sm text-foreground mb-2">
                {review.latest_request.reason}
              </p>
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>By: {review.latest_request.requested_by}</span>
                <span>{formatDateTime(review.latest_request.requested_at)}</span>
              </div>
            </div>
          )}

          {/* Latest Decision */}
          {review.latest_decision && (
            <div
              className={`rounded-md border p-3 ${
                review.latest_decision.outcome === "approved"
                  ? getSeverityClasses("success").border
                  : review.latest_decision.outcome === "rejected"
                    ? getSeverityClasses("failure").border
                    : getSeverityClasses("neutral").border
              }`}
            >
              <div className="flex items-center gap-2 mb-2">
                {review.latest_decision.outcome === "approved" ? (
                  <CheckCircle2 className={`h-4 w-4 ${getSeverityClasses("success").text}`} />
                ) : review.latest_decision.outcome === "rejected" ? (
                  <XCircle className={`h-4 w-4 ${getSeverityClasses("failure").text}`} />
                ) : (
                  <Clock className="h-4 w-4 text-muted-foreground" />
                )}
                <span className="text-sm font-medium text-foreground capitalize">
                  {review.latest_decision.outcome}
                </span>
              </div>
              {review.latest_decision.notes && (
                <p className="text-sm text-foreground mb-2">
                  {review.latest_decision.notes}
                </p>
              )}
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <div className="flex items-center gap-1">
                  <User className="h-3 w-3" />
                  <span>{review.latest_decision.reviewer.reviewer_name}</span>
                  <span className="text-muted-foreground/60">
                    ({review.latest_decision.reviewer.reviewer_type})
                  </span>
                </div>
                <span>{formatDateTime(review.latest_decision.reviewed_at)}</span>
              </div>
            </div>
          )}

          {/* History (collapsed) */}
          {(review.requests.length > 1 || review.decisions.length > 1) && (
            <div className="pt-2 border-t border-border">
              <p className="text-xs text-muted-foreground">
                Full history: {review.requests.length} request(s),{" "}
                {review.decisions.length} decision(s)
              </p>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
