import HarnessAppCore
import SwiftUI

struct SettingsView: View {
    @ObservedObject var model: HarnessMenuBarModel

    var body: some View {
        Form {
            Section("Runtime") {
                LabeledContent("State", value: model.snapshot.runtimeState.displayName)
                LabeledContent("API", value: model.snapshot.apiBaseURL ?? "Not running")
                LabeledContent("Logs", value: model.snapshot.logDirectory ?? defaultLogDirectory)
            }

            Section("Operation") {
                Text("The menu bar reads local runtime status and task counts through the Harness CLI and HTTP API. It does not read SQLite directly.")
                    .foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .padding()
        .frame(width: 520)
    }

    private var defaultLogDirectory: String {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library")
            .appendingPathComponent("Logs")
            .appendingPathComponent("Harness")
            .path
    }
}
