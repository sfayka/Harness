import HarnessAppCore
import SwiftUI

enum OnboardingStep: String, CaseIterable, Identifiable, Hashable {
    case welcome
    case runtime
    case permissions
    case folders
    case integrations
    case doctor
    case dashboard

    var id: String { rawValue }

    var title: String {
        switch self {
        case .welcome:
            return "Welcome"
        case .runtime:
            return "Runtime"
        case .permissions:
            return "Permissions"
        case .folders:
            return "Folders"
        case .integrations:
            return "Integrations"
        case .doctor:
            return "Doctor"
        case .dashboard:
            return "Dashboard"
        }
    }

    var systemImage: String {
        switch self {
        case .welcome:
            return "hand.wave"
        case .runtime:
            return "internaldrive"
        case .permissions:
            return "checkmark.shield"
        case .folders:
            return "folder"
        case .integrations:
            return "point.3.connected.trianglepath.dotted"
        case .doctor:
            return "stethoscope"
        case .dashboard:
            return "rectangle.3.group"
        }
    }
}

struct SectionIntro: View {
    let title: String
    let text: String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.title2.weight(.semibold))
            Text(text)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}

struct FactRow: View {
    let title: String
    let text: String

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title)
                .font(.headline)
            Text(text)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}

struct PermissionRow<Actions: View>: View {
    let title: String
    let value: String
    let description: String
    @ViewBuilder let actions: Actions

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text(title)
                        .font(.headline)
                    Text(value)
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 3)
                        .background(.quaternary, in: Capsule())
                }
                Text(description)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer()
            actions
        }
    }
}

struct SetupStatusBadge: View {
    let status: String
    let requiredBlockers: Int

    var body: some View {
        Label(title, systemImage: image)
            .font(.caption.weight(.semibold))
            .foregroundStyle(color)
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(color.opacity(0.12), in: Capsule())
    }

    private var title: String {
        if status == "ready" {
            return "Ready"
        }
        return "\(requiredBlockers) blocker\(requiredBlockers == 1 ? "" : "s")"
    }

    private var image: String {
        status == "ready" ? "checkmark.circle.fill" : "exclamationmark.triangle.fill"
    }

    private var color: Color {
        status == "ready" ? .green : .orange
    }
}

struct SetupItemCard: View {
    let item: GuidedSetupItem
    let hidesTerminalNextActions: Bool

    var body: some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 10) {
                HStack(alignment: .firstTextBaseline) {
                    Text(item.title)
                        .font(.headline)
                    Spacer()
                    ItemStatusBadge(item: item)
                }
                Text(item.purpose)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)

                if !displayNextAction.isEmpty {
                    Text(displayNextAction)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                if !item.compatibleClients.isEmpty {
                    Text("Compatible clients: \(item.compatibleClients.joined(separator: ", "))")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .padding(4)
        }
    }

    private var displayNextAction: String {
        if hidesTerminalNextActions && item.nextAction.contains("`") {
            switch item.id {
            case "local_runtime":
                return "Use the buttons in this setup assistant to initialize and validate the local runtime."
            case "github":
                return "Optional. Connect GitHub here or later when artifact verification is needed."
            case "linear":
                return "Optional. Connect Linear here or later when coordination sync is needed."
            case "ingress_executor":
                return "Optional. Connect a desktop-agent bridge later when repair dispatch is needed."
            default:
                return ""
            }
        }
        return item.nextAction
    }
}

struct CredentialEntryCard: View {
    let item: GuidedSetupItem
    let secretName: String
    @Binding var value: String
    let isBusy: Bool
    var note: String?
    let onSave: () -> Void

    var body: some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(item.title)
                            .font(.headline)
                        Text(note ?? "Paste the token here. Harness stores it through the app-managed secret provider and never displays it again.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    ItemStatusBadge(item: item)
                }

                HStack {
                    SecureField(secretName, text: $value)
                        .textFieldStyle(.roundedBorder)
                    Button("Save & Validate") {
                        onSave()
                    }
                    .disabled(isBusy || value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
            .padding(4)
        }
    }
}

struct SetupCheckList: View {
    let checks: [GuidedSetupCheck]

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(checks) { check in
                HStack(alignment: .top, spacing: 8) {
                    Image(systemName: image(for: check.status))
                        .foregroundStyle(color(for: check.status))
                    VStack(alignment: .leading, spacing: 2) {
                        Text(check.message)
                        Text(check.impact)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
    }

    private func image(for status: String) -> String {
        switch status {
        case "pass":
            return "checkmark.circle.fill"
        case "fail":
            return "xmark.octagon.fill"
        default:
            return "exclamationmark.triangle.fill"
        }
    }

    private func color(for status: String) -> Color {
        switch status {
        case "pass":
            return .green
        case "fail":
            return .red
        default:
            return .orange
        }
    }
}

struct ItemStatusBadge: View {
    let item: GuidedSetupItem

    var body: some View {
        Label(title, systemImage: image)
            .font(.caption.weight(.semibold))
            .foregroundStyle(color)
    }

    private var title: String {
        switch item.status {
        case "complete":
            return "Complete"
        case "blocked":
            return item.required ? "Blocked" : "Attention"
        default:
            return item.required ? "Required" : "Optional"
        }
    }

    private var image: String {
        switch item.status {
        case "complete":
            return "checkmark.circle.fill"
        case "blocked":
            return "xmark.octagon.fill"
        default:
            return "circle.dashed"
        }
    }

    private var color: Color {
        switch item.status {
        case "complete":
            return .green
        case "blocked":
            return .red
        default:
            return .secondary
        }
    }
}

struct SummaryPill: View {
    let title: String
    let value: Int
    let color: Color

    var body: some View {
        HStack(spacing: 6) {
            Text(title)
            Text(value, format: .number)
                .font(.system(.body, design: .monospaced).weight(.semibold))
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(color.opacity(0.12), in: Capsule())
        .foregroundStyle(color)
    }
}

func encodeWorkspaceFolders(_ folders: [String]) -> String {
    folders.joined(separator: "\n")
}

func decodeWorkspaceFolders(_ rawValue: String) -> [String] {
    rawValue
        .split(whereSeparator: \.isNewline)
        .map { String($0).trimmingCharacters(in: .whitespacesAndNewlines) }
        .filter { !$0.isEmpty }
}
