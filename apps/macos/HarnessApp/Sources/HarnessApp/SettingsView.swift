import HarnessAppCore
import SwiftUI

struct SettingsView: View {
    @ObservedObject var model: HarnessMenuBarModel
    @AppStorage(AppPreferenceKeys.workspaceFolders) private var storedWorkspaceFolders = ""
    @State private var launchAtLogin: LaunchAtLoginState = .unknown
    @State private var notificationPermission: NotificationPermissionState = .unknown
    @State private var platformMessage: String?
    @State private var isUpdatingLaunchAtLogin = false

    var body: some View {
        Form {
            Section("Runtime") {
                LabeledContent("State", value: model.snapshot.runtimeState.displayName)
                LabeledContent("API", value: model.snapshot.apiBaseURL ?? "Not running")
                LabeledContent("Logs", value: model.snapshot.logDirectory ?? defaultLogDirectory)
                HStack {
                    Button("Start") {
                        Task { await model.startRuntime() }
                    }
                    Button("Stop") {
                        Task { await model.stopRuntime() }
                    }
                    Button("Restart") {
                        Task { await model.restartRuntime() }
                    }
                    Button("Recover") {
                        Task { await model.recoverRuntime() }
                    }
                }
                .disabled(model.isBusy)
            }

            Section("Launch at Login") {
                LabeledContent("State", value: launchAtLogin.displayName)
                Text("When enabled, macOS launches the Harness app after login and the app starts the local runtime if onboarding has been completed.")
                    .foregroundStyle(.secondary)

                HStack {
                    Button(launchAtLogin == .enabled ? "Disable" : "Enable") {
                        Task { await setLaunchAtLogin(enabled: launchAtLogin != .enabled) }
                    }
                    Button("Refresh") {
                        Task { await refreshPlatformState() }
                    }
                }
                .disabled(isUpdatingLaunchAtLogin)

                if let platformMessage {
                    Text(platformMessage)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            Section("Operation") {
                Text("The menu bar reads local runtime status and task counts through the Harness CLI and HTTP API. It does not read SQLite directly. Launch at Login starts the app; the app supervises the backend as an app-managed child process.")
                    .foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .padding()
        .frame(width: 620)
        .task {
            await refreshPlatformState()
        }
    }

    private var defaultLogDirectory: String {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library")
            .appendingPathComponent("Logs")
            .appendingPathComponent("Harness")
            .path
    }

    @MainActor
    private func setLaunchAtLogin(enabled: Bool) async {
        isUpdatingLaunchAtLogin = true
        let result = MacOSSetupState.setLaunchAtLogin(enabled: enabled)
        launchAtLogin = result.state
        if let message = result.message {
            platformMessage = "Launch at Login could not be updated: \(message)"
        } else if launchAtLogin == .requiresApproval {
            platformMessage = "macOS needs approval in System Settings before Launch at Login is active."
        } else {
            platformMessage = "Launch at Login is \(launchAtLogin.displayName.lowercased())."
        }
        await applySetupEnvironment()
        await model.refreshSetupStatus()
        isUpdatingLaunchAtLogin = false
    }

    @MainActor
    private func refreshPlatformState() async {
        launchAtLogin = MacOSSetupState.launchAtLoginState()
        notificationPermission = await MacOSSetupState.notificationPermissionState()
        await applySetupEnvironment()
    }

    @MainActor
    private func applySetupEnvironment() async {
        let environment = AppSetupEnvironment(
            notificationPermission: notificationPermission,
            launchAtLogin: launchAtLogin,
            workspaceFolders: decodeWorkspaceFolders(storedWorkspaceFolders)
        )
        model.updateAppEnvironment(environment.dictionary)
    }
}
