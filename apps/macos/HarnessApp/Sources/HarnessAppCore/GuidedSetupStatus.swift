import Foundation

public struct GuidedSetupStatusPayload: Decodable, Equatable, Sendable {
    public let status: String
    public let onboardingComplete: Bool
    public let runtimeReady: Bool
    public let selectedWorkflows: [GuidedSetupWorkflow]
    public let availableWorkflows: [GuidedSetupWorkflow]
    public let requiredBlockers: [String]
    public let optionalIncomplete: [String]
    public let optionalAttention: [String]
    public let items: [GuidedSetupItem]
    public let doctorSummary: [String: Int]?

    enum CodingKeys: String, CodingKey {
        case status
        case onboardingComplete = "onboarding_complete"
        case runtimeReady = "runtime_ready"
        case selectedWorkflows = "selected_workflows"
        case availableWorkflows = "available_workflows"
        case requiredBlockers = "required_blockers"
        case optionalIncomplete = "optional_incomplete"
        case optionalAttention = "optional_attention"
        case items
        case doctorSummary = "doctor_summary"
    }

    public func item(id: String) -> GuidedSetupItem? {
        items.first { $0.id == id }
    }
}

public struct GuidedSetupWorkflow: Decodable, Equatable, Sendable, Identifiable {
    public let id: String
    public let label: String
    public let description: String
    public let requiredItems: [String]

    enum CodingKeys: String, CodingKey {
        case id
        case label
        case description
        case requiredItems = "required_items"
    }
}

public struct GuidedSetupItem: Decodable, Equatable, Sendable, Identifiable {
    public let id: String
    public let title: String
    public let category: String
    public let required: Bool
    public let status: String
    public let blocksOnboarding: Bool
    public let purpose: String
    public let whatUserNeeds: [String]
    public let howHarnessValidates: String
    public let nextAction: String
    public let doctorCheckCodes: [String]
    public let secretNames: [String]
    public let compatibleClients: [String]
    public let setupActions: [GuidedSetupAction]
    public let notes: [String]
    public let validation: GuidedSetupValidation

    enum CodingKeys: String, CodingKey {
        case id
        case title
        case category
        case required
        case status
        case blocksOnboarding = "blocks_onboarding"
        case purpose
        case whatUserNeeds = "what_user_needs"
        case howHarnessValidates = "how_harness_validates"
        case nextAction = "next_action"
        case doctorCheckCodes = "doctor_check_codes"
        case secretNames = "secret_names"
        case compatibleClients = "compatible_clients"
        case setupActions = "setup_actions"
        case notes
        case validation
    }

    public var isComplete: Bool {
        status == "complete"
    }

    public var isBlocked: Bool {
        status == "blocked"
    }
}

public struct GuidedSetupAction: Decodable, Equatable, Sendable, Identifiable {
    public let kind: String
    public let label: String
    public let description: String
    public let command: String?
    public let secretName: String?
    public let storesSecret: Bool

    public var id: String {
        [kind, label, secretName ?? ""].joined(separator: ":")
    }

    enum CodingKeys: String, CodingKey {
        case kind
        case label
        case description
        case command
        case secretName = "secret_name"
        case storesSecret = "stores_secret"
    }
}

public struct GuidedSetupValidation: Decodable, Equatable, Sendable {
    public let status: String
    public let checks: [GuidedSetupCheck]
    public let missingCheckCodes: [String]

    enum CodingKeys: String, CodingKey {
        case status
        case checks
        case missingCheckCodes = "missing_check_codes"
    }
}

public struct GuidedSetupCheck: Decodable, Equatable, Sendable, Identifiable {
    public let code: String
    public let status: String
    public let message: String
    public let impact: String
    public let nextAction: String

    public var id: String {
        code
    }

    enum CodingKeys: String, CodingKey {
        case code
        case status
        case message
        case impact
        case nextAction = "next_action"
    }
}
