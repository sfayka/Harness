import Foundation
import HarnessAppCore

@main
struct HarnessAppCoreCheck {
    static func main() throws {
        try checksRunningSummaryFromTaskListAndQueue()
        try checksStoppedRuntimeSummary()
        try checksDashboardRoutes()
        try checksGuidedSetupPayloadDecoding()
        try checksRuntimeControlPayloadDecoding()
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

    private static func checksDashboardRoutes() throws {
        let baseURL = URL(string: "http://127.0.0.1:8765/dashboard?stale=true#old")!

        try require(
            baseURL.dashboardRoute(.tasks).absoluteString == "http://127.0.0.1:8765/dashboard/tasks/",
            "tasks dashboard route"
        )
        try require(
            baseURL.dashboardRoute(.verification).absoluteString == "http://127.0.0.1:8765/dashboard/verification/",
            "verification dashboard route"
        )
        try require(
            baseURL.dashboardRoute(.reconciliation).absoluteString == "http://127.0.0.1:8765/dashboard/reconciliation/",
            "reconciliation dashboard route"
        )
        try require(
            baseURL.dashboardRoute(.reviews).absoluteString == "http://127.0.0.1:8765/dashboard/reviews/",
            "reviews dashboard route"
        )
    }

    private static func checksGuidedSetupPayloadDecoding() throws {
        let payload = try decode(
            GuidedSetupStatusPayload.self,
            """
            {
              "status": "ready",
              "onboarding_complete": true,
              "runtime_ready": true,
              "selected_workflows": [],
              "available_workflows": [
                {
                  "id": "github-proof",
                  "label": "GitHub artifact verification",
                  "description": "Require GitHub proof.",
                  "required_items": ["github"]
                }
              ],
              "required_blockers": [],
              "optional_incomplete": ["github"],
              "optional_attention": [],
              "doctor_summary": {"pass": 5, "warn": 3, "fail": 0},
              "items": [
                {
                  "id": "local_runtime",
                  "title": "Local Harness runtime",
                  "category": "core",
                  "required": true,
                  "status": "complete",
                  "blocks_onboarding": false,
                  "purpose": "Runs Harness locally.",
                  "what_user_needs": ["Writable folders."],
                  "how_harness_validates": "Harness checks setup.",
                  "next_action": "No setup action is required.",
                  "doctor_check_codes": ["config"],
                  "secret_names": [],
                  "compatible_clients": [],
                  "setup_actions": [],
                  "notes": [],
                  "validation": {
                    "status": "pass",
                    "checks": [
                      {
                        "code": "config",
                        "status": "pass",
                        "message": "Config is ready.",
                        "impact": "Harness can start.",
                        "next_action": "No action needed."
                      }
                    ],
                    "missing_check_codes": []
                  }
                }
              ]
            }
            """
        )

        try require(payload.onboardingComplete, "onboarding complete")
        try require(payload.runtimeReady, "runtime ready")
        try require(payload.availableWorkflows.first?.requiredItems == ["github"], "workflow required items")
        try require(payload.item(id: "local_runtime")?.isComplete == true, "setup item complete")
        try require(payload.item(id: "github") == nil, "missing item lookup")
        try require(payload.doctorSummary?["pass"] == 5, "doctor summary")
    }

    private static func checksRuntimeControlPayloadDecoding() throws {
        let payload = try decode(
            RuntimeControlPayload.self,
            """
            {
              "status": "running",
              "message": "Harness runtime started.",
              "next_action": "No action needed.",
              "api_base_url": "http://127.0.0.1:8765",
              "pid": 4242,
              "recovered": true
            }
            """
        )

        try require(payload.status == "running", "runtime control status")
        try require(payload.message == "Harness runtime started.", "runtime control message")
        try require(payload.nextAction == "No action needed.", "runtime control next action")
        try require(payload.apiBaseURL == "http://127.0.0.1:8765", "runtime control api")
        try require(payload.pid == 4242, "runtime control pid")
        try require(payload.recovered == true, "runtime control recovered")
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
