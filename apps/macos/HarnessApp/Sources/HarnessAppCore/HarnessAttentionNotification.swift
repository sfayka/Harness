import Foundation

public enum HarnessAttentionNotificationKind: String, Equatable, Sendable {
    case manualReviewRequired
    case repairDispatchFailed
    case executorStalled
    case budgetThresholdCrossed
    case credentialDisconnected
}

public enum HarnessAttentionNotificationDestination: Equatable, Sendable {
    case dashboard(DashboardRoute)
    case setupAssistant
}

public struct HarnessAttentionNotification: Equatable, Identifiable, Sendable {
    public let id: String
    public let kind: HarnessAttentionNotificationKind
    public let title: String
    public let body: String
    public let destination: HarnessAttentionNotificationDestination
}

public enum HarnessAttentionNotificationPlanner {
    public static func plan(
        tasks: TaskListPayload?,
        queue: SupervisionQueuePayload?,
        setupStatus: GuidedSetupStatusPayload?,
        deliveredNotificationIDs: Set<String>
    ) -> [HarnessAttentionNotification] {
        var candidates: [HarnessAttentionNotification] = []
        let taskTitles = Dictionary(
            uniqueKeysWithValues: (tasks?.tasks ?? []).map { item in
                (item.taskID, clean(item.title) ?? item.taskID)
            }
        )

        for entry in queue?.queue ?? [] {
            guard let candidate = notificationCandidate(for: entry, taskTitles: taskTitles) else {
                continue
            }
            candidates.append(candidate)
        }

        candidates.append(contentsOf: credentialCandidates(from: setupStatus))

        return candidates.filter { !deliveredNotificationIDs.contains($0.id) }
    }

    private static func notificationCandidate(
        for entry: SupervisionQueueEntry,
        taskTitles: [String: String]
    ) -> HarnessAttentionNotification? {
        let taskID = entry.taskID
        let attentionType = entry.attentionType
        let displayTitle = clean(entry.title) ?? taskTitles[taskID] ?? taskID
        let id = "task:\(taskID):\(attentionType)"

        switch attentionType {
        case "review_required":
            if describesRepairDispatchFailure(entry) {
                return HarnessAttentionNotification(
                    id: id,
                    kind: .repairDispatchFailed,
                    title: "Harness repair dispatch failed",
                    body: "\(displayTitle) needs repair bridge attention.",
                    destination: .dashboard(.tasks)
                )
            }
            return HarnessAttentionNotification(
                id: id,
                kind: .manualReviewRequired,
                title: "Harness needs review",
                body: "\(displayTitle) is waiting for an explicit review decision.",
                destination: .dashboard(.reviews)
            )
        case "repair_dispatch_failed":
            return HarnessAttentionNotification(
                id: id,
                kind: .repairDispatchFailed,
                title: "Harness repair dispatch failed",
                body: "\(displayTitle) needs repair bridge attention.",
                destination: .dashboard(.tasks)
            )
        case "stale_active_task":
            return HarnessAttentionNotification(
                id: id,
                kind: .executorStalled,
                title: "Harness executor appears stalled",
                body: "\(displayTitle) has no recent canonical activity.",
                destination: .dashboard(.tasks)
            )
        case "budget_threshold_crossed":
            return HarnessAttentionNotification(
                id: id,
                kind: .budgetThresholdCrossed,
                title: "Harness budget threshold crossed",
                body: "\(displayTitle) crossed a configured execution budget threshold.",
                destination: .dashboard(.reviews)
            )
        case "credential_expired", "credential_disconnected", "integration_credential_disconnected":
            return HarnessAttentionNotification(
                id: id,
                kind: .credentialDisconnected,
                title: "Harness integration needs attention",
                body: "\(displayTitle) needs to be reconnected before dependent workflows can run.",
                destination: .setupAssistant
            )
        default:
            return nil
        }
    }

    private static func credentialCandidates(
        from setupStatus: GuidedSetupStatusPayload?
    ) -> [HarnessAttentionNotification] {
        guard let setupStatus, setupStatus.runtimeReady else {
            return []
        }
        let attentionItemIDs = Set(setupStatus.optionalAttention + setupStatus.requiredBlockers)
        return setupStatus.items.compactMap { item -> HarnessAttentionNotification? in
            guard attentionItemIDs.contains(item.id), item.category == "integration", !item.secretNames.isEmpty else {
                return nil
            }
            return HarnessAttentionNotification(
                id: "setup:\(item.id):credential_attention",
                kind: .credentialDisconnected,
                title: "Harness integration needs attention",
                body: "\(item.title) needs to be reconnected before dependent workflows can run.",
                destination: .setupAssistant
            )
        }
    }

    private static func clean(_ value: String?) -> String? {
        guard let value else {
            return nil
        }
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }

    private static func describesRepairDispatchFailure(_ entry: SupervisionQueueEntry) -> Bool {
        let text = [entry.title, entry.reason, entry.suggestedAction]
            .compactMap { $0?.lowercased() }
            .joined(separator: " ")
        return text.contains("repair dispatch")
            || text.contains("dispatch repair")
            || text.contains("repair bridge")
    }
}
