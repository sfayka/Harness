import Foundation

public enum HarnessRuntimeState: String, Equatable, Sendable {
    case running
    case stopped
    case degraded
    case setupRequired
    case error

    public var displayName: String {
        switch self {
        case .running:
            return "Running"
        case .stopped:
            return "Stopped"
        case .degraded:
            return "Degraded"
        case .setupRequired:
            return "Setup"
        case .error:
            return "Error"
        }
    }

    public var systemImage: String {
        switch self {
        case .running:
            return "checkmark.circle.fill"
        case .stopped:
            return "pause.circle"
        case .degraded:
            return "exclamationmark.triangle.fill"
        case .setupRequired:
            return "wrench.and.screwdriver.fill"
        case .error:
            return "xmark.octagon.fill"
        }
    }
}

public struct RuntimeStatusPayload: Decodable, Equatable, Sendable {
    public let status: String
    public let apiBaseURL: String?
    public let error: String?
    public let paths: [String: String]?

    public init(
        status: String,
        apiBaseURL: String?,
        error: String?,
        paths: [String: String]?
    ) {
        self.status = status
        self.apiBaseURL = apiBaseURL
        self.error = error
        self.paths = paths
    }

    enum CodingKeys: String, CodingKey {
        case status
        case apiBaseURL = "api_base_url"
        case error
        case paths
    }
}

public struct TaskListPayload: Decodable, Equatable, Sendable {
    public let tasks: [TaskListItem]
}

public struct TaskListItem: Decodable, Equatable, Sendable {
    public let taskID: String
    public let title: String?
    public let currentStatus: String
    public let reviewSummary: ReviewSummary?
    public let verificationSummary: VerificationSummary?
    public let failureSummary: FailureSummary?
    public let executionSummary: ExecutionSummary?

    enum CodingKeys: String, CodingKey {
        case taskID = "task_id"
        case title
        case currentStatus = "current_status"
        case reviewSummary = "review_summary"
        case verificationSummary = "verification_summary"
        case failureSummary = "failure_summary"
        case executionSummary = "execution_summary"
    }
}

public struct ReviewSummary: Decodable, Equatable, Sendable {
    public let status: String?
}

public struct VerificationSummary: Decodable, Equatable, Sendable {
    public let requiresReview: Bool?

    enum CodingKeys: String, CodingKey {
        case requiresReview = "requires_review"
    }
}

public struct FailureSummary: Decodable, Equatable, Sendable {
    public let state: String?
    public let failureType: String?

    enum CodingKeys: String, CodingKey {
        case state
        case failureType = "failure_type"
    }
}

public struct ExecutionSummary: Decodable, Equatable, Sendable {
    public let failureState: String?
    public let retryEligible: Bool?

    enum CodingKeys: String, CodingKey {
        case failureState = "failure_state"
        case retryEligible = "retry_eligible"
    }
}

public struct SupervisionQueuePayload: Decodable, Equatable, Sendable {
    public let queue: [SupervisionQueueEntry]
}

public struct SupervisionQueueEntry: Decodable, Equatable, Sendable {
    public let taskID: String
    public let title: String?
    public let attentionType: String
    public let suggestedAction: String?
    public let reason: String?
    public let stale: Bool?

    enum CodingKeys: String, CodingKey {
        case taskID = "task_id"
        case title
        case attentionType = "attention_type"
        case suggestedAction = "suggested_action"
        case reason
        case stale
    }
}

public struct HarnessMenuSnapshot: Equatable, Sendable {
    public let runtimeState: HarnessRuntimeState
    public let activeTaskCount: Int
    public let reviewNeededCount: Int
    public let repairNeededCount: Int
    public let apiBaseURL: String?
    public let logDirectory: String?
    public let message: String
    public let updatedAt: Date

    public init(
        runtimeState: HarnessRuntimeState,
        activeTaskCount: Int,
        reviewNeededCount: Int,
        repairNeededCount: Int,
        apiBaseURL: String?,
        logDirectory: String?,
        message: String,
        updatedAt: Date = Date()
    ) {
        self.runtimeState = runtimeState
        self.activeTaskCount = activeTaskCount
        self.reviewNeededCount = reviewNeededCount
        self.repairNeededCount = repairNeededCount
        self.apiBaseURL = apiBaseURL
        self.logDirectory = logDirectory
        self.message = message
        self.updatedAt = updatedAt
    }

    public static let initial = HarnessMenuSnapshot(
        runtimeState: .stopped,
        activeTaskCount: 0,
        reviewNeededCount: 0,
        repairNeededCount: 0,
        apiBaseURL: nil,
        logDirectory: nil,
        message: "Checking Harness..."
    )

    public var menuTitle: String {
        if reviewNeededCount > 0 {
            return "Harness \(reviewNeededCount) review"
        }
        if repairNeededCount > 0 {
            return "Harness \(repairNeededCount) attention"
        }
        if activeTaskCount > 0 {
            return "Harness \(activeTaskCount) active"
        }
        return "Harness \(runtimeState.displayName)"
    }
}

public enum HarnessMenuSummaryBuilder {
    private static let terminalStatuses: Set<String> = ["completed", "canceled", "failed"]
    private static let attentionStates: Set<String> = ["retryable", "terminal", "failed"]
    private static let repairAttentionTypes: Set<String> = [
        "clarification_required",
        "github_sync_required",
        "invalid_execution_attempt",
        "retryable_failure",
        "stale_active_task"
    ]

    public static func build(
        runtimeStatus: RuntimeStatusPayload,
        tasks: TaskListPayload?,
        queue: SupervisionQueuePayload?,
        now: Date = Date()
    ) -> HarnessMenuSnapshot {
        let runtimeState = state(from: runtimeStatus.status)
        let taskItems = tasks?.tasks ?? []
        let activeCount = taskItems.filter { !terminalStatuses.contains($0.currentStatus) }.count
        let reviewTaskIDs = Set(
            taskItems
                .filter { item in
                    item.currentStatus == "in_review"
                        || item.reviewSummary?.status == "requested"
                        || item.verificationSummary?.requiresReview == true
                }
                .map(\.taskID)
        )
        var repairTaskIDs = Set(
            taskItems
                .filter { item in
                    let failureState = item.failureSummary?.state ?? item.executionSummary?.failureState ?? "clear"
                    return attentionStates.contains(failureState)
                        || item.executionSummary?.retryEligible == true
                        || item.currentStatus == "failed"
                }
                .map(\.taskID)
        )
        for entry in queue?.queue ?? [] where repairAttentionTypes.contains(entry.attentionType) {
            repairTaskIDs.insert(entry.taskID)
        }
        repairTaskIDs.subtract(reviewTaskIDs)

        return HarnessMenuSnapshot(
            runtimeState: runtimeState,
            activeTaskCount: activeCount,
            reviewNeededCount: reviewTaskIDs.count,
            repairNeededCount: repairTaskIDs.count,
            apiBaseURL: runtimeStatus.apiBaseURL,
            logDirectory: runtimeStatus.paths?["log_dir"],
            message: message(runtimeState: runtimeState, runtimeStatus: runtimeStatus),
            updatedAt: now
        )
    }

    public static func errorSnapshot(_ message: String, now: Date = Date()) -> HarnessMenuSnapshot {
        HarnessMenuSnapshot(
            runtimeState: .error,
            activeTaskCount: 0,
            reviewNeededCount: 0,
            repairNeededCount: 0,
            apiBaseURL: nil,
            logDirectory: nil,
            message: message,
            updatedAt: now
        )
    }

    private static func state(from status: String) -> HarnessRuntimeState {
        switch status {
        case "running":
            return .running
        case "stopped", "uninitialized":
            return .stopped
        case "degraded":
            return .degraded
        case "missing_required_secrets", "setup_required":
            return .setupRequired
        default:
            return .error
        }
    }

    private static func message(
        runtimeState: HarnessRuntimeState,
        runtimeStatus: RuntimeStatusPayload
    ) -> String {
        if let error = runtimeStatus.error, !error.isEmpty {
            return error
        }
        switch runtimeState {
        case .running:
            return "Local runtime is healthy."
        case .stopped:
            return "Local runtime is stopped."
        case .degraded:
            return "Local runtime responded with degraded health."
        case .setupRequired:
            return "Setup is required before this workflow can run."
        case .error:
            return "Harness status could not be read."
        }
    }
}
