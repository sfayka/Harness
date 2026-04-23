import HarnessAppCore
import SwiftUI
import UserNotifications

struct SettingsView: View {
    @ObservedObject var model: HarnessMenuBarModel
    @AppStorage(AppPreferenceKeys.workspaceFolders) private var storedWorkspaceFolders = ""
    @AppStorage(AppPreferenceKeys.attentionNotificationsEnabled) private var attentionNotificationsEnabled = true
    @State private var launchAtLogin: LaunchAtLoginState = .unknown
    @State private var notificationPermission: NotificationPermissionState = .unknown
    @State private var platformMessage: String?
    @State private var isUpdatingLaunchAtLogin = false
    @State private var isUpdatingNotifications = false

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

            Section("Notifications") {
                Toggle("Attention Notifications", isOn: $attentionNotificationsEnabled)
                LabeledContent("macOS Permission", value: notificationPermission.displayName)
                Text("When enabled and authorized by macOS, Harness sends local notifications for manual review, stalled executor, repair-dispatch, budget, and integration credential attention events.")
                    .foregroundStyle(.secondary)

                HStack {
                    Button("Request Permission") {
                        Task { await requestNotifications() }
                    }
                    Button("Refresh") {
                        Task { await refreshPlatformState() }
                    }
                }
                .disabled(isUpdatingNotifications)
            }

            Section("Operation") {
                Text("The menu bar reads local runtime status and task counts through the Harness CLI and HTTP API. It does not read SQLite directly. Launch at Login starts the app; the app supervises the backend as an app-managed child process. Notifications are derived from canonical Harness attention/setup surfaces, not direct database polling.")
                    .foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .padding()
        .frame(width: 620)
        .task {
            await refreshPlatformState()
        }
        .onChange(of: attentionNotificationsEnabled) { _, enabled in
            model.setAttentionNotificationsEnabled(enabled)
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
    private func requestNotifications() async {
        isUpdatingNotifications = true
        notificationPermission = await MacOSSetupState.requestNotificationPermission()
        attentionNotificationsEnabled = notificationPermission == .authorized
        model.setAttentionNotificationsEnabled(attentionNotificationsEnabled)
        platformMessage = notificationPermission == .authorized
            ? "Notifications are authorized."
            : "Notifications are optional. Harness can run without them."
        await applySetupEnvironment()
        await model.refreshSetupStatus()
        isUpdatingNotifications = false
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
