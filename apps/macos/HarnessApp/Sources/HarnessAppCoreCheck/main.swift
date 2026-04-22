import Foundation
import HarnessAppCore

@main
struct HarnessAppCoreCheck {
    static func main() throws {
        try checksRunningSummaryFromTaskListAndQueue()
        try checksStoppedRuntimeSummary()
        print("HarnessAppCoreCheck passed")
    }

    private static func checksRunningSummaryFromTaskListAndQueue() throws {
        let runtime = RuntimeStatusPayload(
            status: "running",
            apiBaseURL: "http://127.0.0.1:8765",
            error: nil,
            paths: ["log_dir": "/tmp/harness-logs"]
        )
        let tasks = try decode(
            TaskListPayload.self,
            """
            {
              "tasks": [
                {
                  "task_id": "active-1",
                  "title": "Active",
                  "current_status": "assigned",
                  "review_summary": {"status": "none"},
                  "verification_summary": {"requires_review": false},
                  "failure_summary": {"state": "clear"},
                  "execution_summary": {"failure_state": "clear", "retry_eligible": false}
                },
                {
                  "task_id": "review-1",
                  "title": "Review",
                  "current_status": "in_review",
                  "review_summary": {"status": "requested"},
                  "verification_summary": {"requires_review": true},
                  "failure_summary": {"state": "review_required"},
                  "execution_summary": {"failure_state": "review_required", "retry_eligible": false}
                },
                {
                  "task_id": "retry-1",
                  "title": "Retry",
                  "current_status": "blocked",
                  "review_summary": {"status": "none"},
                  "verification_summary": {"requires_review": false},
                  "failure_summary": {"state": "retryable"},
                  "execution_summary": {"failure_state": "retryable", "retry_eligible": true}
                },
                {
                  "task_id": "done-1",
                  "title": "Done",
                  "current_status": "completed",
                  "review_summary": {"status": "none"},
                  "verification_summary": {"requires_review": false},
                  "failure_summary": {"state": "clear"},
                  "execution_summary": {"failure_state": "clear", "retry_eligible": false}
                }
              ]
            }
            """
        )
        let queue = try decode(
            SupervisionQueuePayload.self,
            """
            {
              "queue": [
                {"task_id": "review-1", "attention_type": "review_required", "stale": false},
                {"task_id": "stale-1", "attention_type": "stale_active_task", "stale": true}
              ]
            }
            """
        )
        let snapshot = HarnessMenuSummaryBuilder.build(
            runtimeStatus: runtime,
            tasks: tasks,
            queue: queue,
            now: Date(timeIntervalSince1970: 100)
        )

        try require(snapshot.runtimeState == .running, "runtime state")
        try require(snapshot.activeTaskCount == 3, "active count")
        try require(snapshot.reviewNeededCount == 1, "review count")
        try require(snapshot.repairNeededCount == 2, "attention count")
        try require(snapshot.menuTitle == "Harness 1 review", "menu title")
        try require(snapshot.logDirectory == "/tmp/harness-logs", "log directory")
    }

    private static func checksStoppedRuntimeSummary() throws {
        let runtime = RuntimeStatusPayload(
            status: "stopped",
            apiBaseURL: "http://127.0.0.1:8765",
            error: nil,
            paths: ["log_dir": "/tmp/harness-logs"]
        )
        let snapshot = HarnessMenuSummaryBuilder.build(
            runtimeStatus: runtime,
            tasks: nil,
            queue: nil,
            now: Date(timeIntervalSince1970: 100)
        )

        try require(snapshot.runtimeState == .stopped, "stopped state")
        try require(snapshot.activeTaskCount == 0, "stopped active count")
        try require(snapshot.reviewNeededCount == 0, "stopped review count")
        try require(snapshot.repairNeededCount == 0, "stopped attention count")
        try require(snapshot.menuTitle == "Harness Stopped", "stopped menu title")
    }

    private static func decode<T: Decodable>(_ type: T.Type, _ json: String) throws -> T {
        try JSONDecoder().decode(type, from: Data(json.utf8))
    }

    private static func require(_ condition: Bool, _ message: String) throws {
        if !condition {
            throw CheckError.failed(message)
        }
    }
}

enum CheckError: Error, CustomStringConvertible {
    case failed(String)

    var description: String {
        switch self {
        case .failed(let message):
            return "Check failed: \(message)"
        }
    }
}
