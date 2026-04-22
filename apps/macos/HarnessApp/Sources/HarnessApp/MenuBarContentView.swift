import AppKit
import HarnessAppCore
import SwiftUI

struct MenuBarContentView: View {
    @Environment(\.openWindow) private var openWindow
    @ObservedObject var model: HarnessMenuBarModel

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            StatusHeader(snapshot: model.snapshot)

            Divider()

            StatusCountRow(title: "Active", value: model.snapshot.activeTaskCount)
            StatusCountRow(title: "Review", value: model.snapshot.reviewNeededCount)
            StatusCountRow(title: "Attention", value: model.snapshot.repairNeededCount)

            if let doctorMessage = model.lastDoctorMessage {
                Divider()
                Text(doctorMessage)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Divider()

            Button("Open Dashboard") {
                openWindow(id: "dashboard")
                Task { await model.prepareDashboard() }
            }
            Button("Setup Assistant") {
                openWindow(id: "onboarding")
                Task { await model.refreshSetupStatus() }
            }
            Button("Refresh Status") {
                Task { await model.refresh() }
            }
            Button("Run Doctor") {
                Task { await model.runDoctor() }
            }

            Divider()

            Button("Start") {
                Task { await model.startRuntime() }
            }
            Button("Stop") {
                Task { await model.stopRuntime() }
            }
            Button("Restart") {
                Task { await model.restartRuntime() }
            }
            Button("Recover Runtime") {
                Task { await model.recoverRuntime() }
            }

            Divider()

            Button("Open Logs") {
                model.openLogs()
            }
            SettingsLink {
                Text("Settings")
            }
            Button("Quit") {
                NSApplication.shared.terminate(nil)
            }
        }
        .frame(minWidth: 240)
        .disabled(model.isBusy)
    }
}

private struct StatusHeader: View {
    let snapshot: HarnessMenuSnapshot

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Label(snapshot.runtimeState.displayName, systemImage: snapshot.runtimeState.systemImage)
                .font(.headline)
            Text(snapshot.message)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(2)
            if let apiBaseURL = snapshot.apiBaseURL {
                Text(apiBaseURL)
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
                    .lineLimit(1)
            }
        }
    }
}

private struct StatusCountRow: View {
    let title: String
    let value: Int

    var body: some View {
        HStack {
            Text(title)
            Spacer()
            Text(value, format: .number)
                .font(.system(.body, design: .monospaced))
                .foregroundStyle(value == 0 ? .secondary : .primary)
        }
    }
}
