import AppKit
import HarnessAppCore
import SwiftUI

struct OnboardingWindowView: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openWindow) private var openWindow
    @ObservedObject var model: HarnessMenuBarModel

    @AppStorage(AppPreferenceKeys.onboardingCompleted) private var onboardingCompleted = false
    @AppStorage(AppPreferenceKeys.workspaceFolders) private var storedWorkspaceFolders = ""

    @State private var selectedStep: OnboardingStep? = .welcome
    @State private var didLoad = false
    @State private var notificationPermission: NotificationPermissionState = .unknown
    @State private var launchAtLogin: LaunchAtLoginState = .unknown
    @State private var platformMessage: String?
    @State private var isUpdatingPlatform = false
    @State private var githubToken = ""
    @State private var linearToken = ""
    @State private var callbackToken = ""

    var body: some View {
        NavigationSplitView {
            List(selection: $selectedStep) {
                ForEach(OnboardingStep.allCases) { step in
                    Label(step.title, systemImage: step.systemImage)
                        .tag(step as OnboardingStep?)
                }
            }
            .listStyle(.sidebar)
            .navigationTitle("Setup")
        } detail: {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    setupHeader
                    detailView
                }
                .padding(24)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .safeAreaInset(edge: .bottom) {
                footer
            }
        }
        .task {
            guard !didLoad else {
                return
            }
            didLoad = true
            await refreshPlatformStateAndSetup()
        }
    }

    private var workspaceFolders: [String] {
        decodeWorkspaceFolders(storedWorkspaceFolders)
    }

    private var setupHeader: some View {
        HStack(alignment: .top, spacing: 14) {
            Image(systemName: "shield.checkered")
                .font(.system(size: 34, weight: .semibold))
                .foregroundStyle(.blue)
                .frame(width: 44, height: 44)

            VStack(alignment: .leading, spacing: 6) {
                Text("Harness Setup Assistant")
                    .font(.largeTitle.weight(.semibold))
                Text("Set up local Harness without terminal commands. Core setup stays local: app-managed config, SQLite task truth, local logs, and the embedded dashboard.")
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Spacer()

            if let setupStatus = model.setupStatus {
                SetupStatusBadge(status: setupStatus.status, requiredBlockers: setupStatus.requiredBlockers.count)
            }
        }
    }

    @ViewBuilder
    private var detailView: some View {
        switch selectedStep ?? .welcome {
        case .welcome:
            welcomeStep
        case .runtime:
            runtimeStep
        case .permissions:
            permissionsStep
        case .folders:
            foldersStep
        case .integrations:
            integrationsStep
        case .doctor:
            doctorStep
        case .dashboard:
            dashboardStep
        }
    }

    private var welcomeStep: some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionIntro(
                title: "What Harness Does",
                text: "Harness is the local control plane that checks whether AI-assisted work is actually complete, evidence-backed, reconciled with external systems, and safe to accept."
            )
            GroupBox {
                VStack(alignment: .leading, spacing: 12) {
                    FactRow(
                        title: "Runs locally",
                        text: "The app initializes local config, SQLite storage, and logs under app-managed folders."
                    )
                    FactRow(
                        title: "Keeps truth out of the UI",
                        text: "The dashboard and menu bar read canonical Harness APIs. They do not read SQLite directly."
                    )
                    FactRow(
                        title: "Integrations are optional",
                        text: "GitHub, Linear, and an ingress/executor bridge can be connected later. Core onboarding only requires the local runtime."
                    )
                }
                .padding(4)
            }
        }
    }

    private var runtimeStep: some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionIntro(
                title: "Local Runtime And SQLite",
                text: "Initialize the local runtime before using Harness. This creates app-managed config, logs, and the SQLite database."
            )

            if let item = model.setupStatus?.item(id: "local_runtime") {
                SetupItemCard(item: item, hidesTerminalNextActions: true)
            }

            HStack(spacing: 10) {
                Button("Initialize & Validate") {
                    Task { await initializeRuntime() }
                }
                .buttonStyle(.borderedProminent)

                Button("Start Harness") {
                    Task { await startRuntime() }
                }

                Button("Check Again") {
                    Task { await validateCurrentSetup() }
                }
            }
            .disabled(model.isBusy || model.isCheckingSetup)
        }
    }

    private var permissionsStep: some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionIntro(
                title: "Mac Permissions",
                text: "These are optional but recommended. Harness can run without them, but they make the app behave like reliable local infrastructure."
            )

            GroupBox {
                VStack(alignment: .leading, spacing: 14) {
                    PermissionRow(
                        title: "Launch at Login",
                        value: launchAtLogin.displayName,
                        description: "Start Harness when you sign in so supervision and the menu-bar summary are ready without opening a terminal."
                    ) {
                        HStack {
                            Button(launchAtLogin == .enabled ? "Disable" : "Enable") {
                                Task { await configureLaunchAtLogin(enabled: launchAtLogin != .enabled) }
                            }
                            Button("Refresh") {
                                Task { await refreshPlatformStateAndSetup() }
                            }
                        }
                    }

                    Divider()

                    PermissionRow(
                        title: "Notifications",
                        value: notificationPermission.displayName,
                        description: "Allow Harness to alert you when a task needs review or another attention event is detected."
                    ) {
                        HStack {
                            Button("Request Permission") {
                                Task { await requestNotifications() }
                            }
                            Button("Refresh") {
                                Task { await refreshPlatformStateAndSetup() }
                            }
                        }
                    }

                    if let platformMessage {
                        Text(platformMessage)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                .padding(4)
            }
            .disabled(isUpdatingPlatform)

            if let item = model.setupStatus?.item(id: "local_runtime") {
                SetupCheckList(checks: item.validation.checks.filter { check in
                    check.code == "notification_permission" || check.code == "launch_at_login"
                })
            }
        }
    }

    private var foldersStep: some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionIntro(
                title: "Workspace Folders",
                text: "Folder access is optional. Add only the local repos or artifact folders Harness should inspect for workflows that need local evidence."
            )

            GroupBox {
                VStack(alignment: .leading, spacing: 12) {
                    if workspaceFolders.isEmpty {
                        Text("No workspace folders selected. That is fine until a workflow needs local repo or artifact inspection.")
                            .foregroundStyle(.secondary)
                    } else {
                        ForEach(workspaceFolders, id: \.self) { folder in
                            HStack {
                                Image(systemName: "folder")
                                    .foregroundStyle(.secondary)
                                Text(folder)
                                    .lineLimit(1)
                                    .truncationMode(.middle)
                                Spacer()
                                Button("Remove") {
                                    removeWorkspaceFolder(folder)
                                }
                            }
                        }
                    }

                    HStack {
                        Button("Choose Folders") {
                            chooseWorkspaceFolders()
                        }
                        Button("Validate Folders") {
                            Task { await validateCurrentSetup() }
                        }
                    }
                }
                .padding(4)
            }

            if let item = model.setupStatus?.item(id: "local_runtime") {
                SetupCheckList(checks: item.validation.checks.filter { $0.code == "workspace_folders" })
            }
        }
    }

    private var integrationsStep: some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionIntro(
                title: "Optional Integrations",
                text: "You can finish onboarding without these. Connect them when you want Harness to verify GitHub artifacts, reconcile Linear work, or dispatch repair/executor work through a desktop-agent bridge."
            )

            if let github = model.setupStatus?.item(id: "github") {
                CredentialEntryCard(
                    item: github,
                    secretName: "github_token",
                    value: $githubToken,
                    isBusy: model.isBusy
                ) {
                    let token = githubToken
                    githubToken = ""
                    Task { await saveSecret(name: "github_token", value: token) }
                }
            }

            if let linear = model.setupStatus?.item(id: "linear") {
                CredentialEntryCard(
                    item: linear,
                    secretName: "linear_api_key",
                    value: $linearToken,
                    isBusy: model.isBusy
                ) {
                    let token = linearToken
                    linearToken = ""
                    Task { await saveSecret(name: "linear_api_key", value: token) }
                }
            }

            if let ingress = model.setupStatus?.item(id: "ingress_executor") {
                SetupItemCard(item: ingress, hidesTerminalNextActions: true)
                CredentialEntryCard(
                    item: ingress,
                    secretName: "repair_callback_bearer_token",
                    value: $callbackToken,
                    isBusy: model.isBusy,
                    note: "Only needed when your selected desktop-agent bridge uses bearer-protected callbacks."
                ) {
                    let token = callbackToken
                    callbackToken = ""
                    Task { await saveSecret(name: "repair_callback_bearer_token", value: token) }
                }
            }
        }
    }

    private var doctorStep: some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionIntro(
                title: "Doctor Check",
                text: "Run doctor before finishing setup. It validates app folders, SQLite, dashboard/API readiness, permissions, selected folders, and optional integration state."
            )

            HStack {
                Button("Run Doctor") {
                    Task { await runDoctor() }
                }
                .buttonStyle(.borderedProminent)

                Button("Refresh Setup") {
                    Task { await validateCurrentSetup() }
                }
            }
            .disabled(model.isBusy || model.isCheckingSetup)

            if let message = model.lastDoctorMessage {
                Text(message)
                    .font(.headline)
            }

            if let summary = model.setupStatus?.doctorSummary {
                HStack(spacing: 10) {
                    SummaryPill(title: "Pass", value: summary["pass"] ?? 0, color: .green)
                    SummaryPill(title: "Warn", value: summary["warn"] ?? 0, color: .orange)
                    SummaryPill(title: "Fail", value: summary["fail"] ?? 0, color: .red)
                }
            }

            if let setupStatus = model.setupStatus {
                ForEach(setupStatus.items) { item in
                    SetupItemCard(item: item, hidesTerminalNextActions: true)
                }
            }
        }
    }

    private var dashboardStep: some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionIntro(
                title: "Open Dashboard",
                text: "The dashboard is the full inspection surface. Opening it starts the local runtime if needed and loads the canonical local dashboard routes inside the app."
            )

            GroupBox {
                VStack(alignment: .leading, spacing: 12) {
                    Text(model.setupStatus?.onboardingComplete == true ? "Core setup is ready." : "Core setup still needs attention.")
                        .font(.headline)
                    Text(model.setupMessage)
                        .foregroundStyle(.secondary)
                    HStack {
                        Button("Open Dashboard") {
                            finishAndOpenDashboard()
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(model.setupStatus?.onboardingComplete != true)

                        Button("Check Setup") {
                            Task { await validateCurrentSetup() }
                        }
                    }
                }
                .padding(4)
            }
        }
    }

    private var footer: some View {
        HStack {
            Text(model.isCheckingSetup || model.isBusy ? "Working..." : model.setupMessage)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(2)
            Spacer()
            Button("Skip Optional Items") {
                selectedStep = .dashboard
            }
            Button("Finish & Open Dashboard") {
                finishAndOpenDashboard()
            }
            .buttonStyle(.borderedProminent)
            .disabled(model.setupStatus?.onboardingComplete != true)
        }
        .padding(12)
        .background(.regularMaterial)
    }

    @MainActor
    private func initializeRuntime() async {
        applyEnvironment()
        await model.initializeAndValidateRuntime()
    }

    @MainActor
    private func startRuntime() async {
        applyEnvironment()
        await model.startRuntime()
        await model.refreshSetupStatus()
    }

    @MainActor
    private func runDoctor() async {
        applyEnvironment()
        await model.runDoctor()
    }

    @MainActor
    private func validateCurrentSetup() async {
        applyEnvironment()
        await model.refreshSetupStatus()
    }

    @MainActor
    private func saveSecret(name: String, value: String) async {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            return
        }
        applyEnvironment()
        await model.saveSecretAndValidate(name: name, value: trimmed)
    }

    @MainActor
    private func requestNotifications() async {
        isUpdatingPlatform = true
        notificationPermission = await MacOSSetupState.requestNotificationPermission()
        platformMessage = notificationPermission == .authorized
            ? "Notifications are authorized."
            : "Notifications are optional. Harness can run without them."
        applyEnvironment()
        await model.refreshSetupStatus()
        isUpdatingPlatform = false
    }

    @MainActor
    private func configureLaunchAtLogin(enabled: Bool) async {
        isUpdatingPlatform = true
        let result = MacOSSetupState.setLaunchAtLogin(enabled: enabled)
        launchAtLogin = result.state
        if let message = result.message {
            platformMessage = "Launch at Login could not be updated: \(message)"
        } else if launchAtLogin == .requiresApproval {
            platformMessage = "macOS needs approval in System Settings before Launch at Login is active."
        } else {
            platformMessage = "Launch at Login is \(launchAtLogin.displayName.lowercased())."
        }
        applyEnvironment()
        await model.refreshSetupStatus()
        isUpdatingPlatform = false
    }

    @MainActor
    private func refreshPlatformStateAndSetup() async {
        isUpdatingPlatform = true
        notificationPermission = await MacOSSetupState.notificationPermissionState()
        launchAtLogin = MacOSSetupState.launchAtLoginState()
        applyEnvironment()
        await model.refreshSetupStatus()
        isUpdatingPlatform = false
    }

    @MainActor
    private func applyEnvironment() {
        let environment = AppSetupEnvironment(
            notificationPermission: notificationPermission,
            launchAtLogin: launchAtLogin,
            workspaceFolders: workspaceFolders
        )
        model.updateAppEnvironment(environment.dictionary)
    }

    @MainActor
    private func chooseWorkspaceFolders() {
        let panel = NSOpenPanel()
        panel.title = "Choose Harness Workspace Folders"
        panel.message = "Select only the repos or artifact folders Harness should be allowed to inspect."
        panel.prompt = "Choose"
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = true
        panel.canCreateDirectories = false

        if panel.runModal() == .OK {
            let merged = Array(Set(workspaceFolders + panel.urls.map(\.path))).sorted()
            storedWorkspaceFolders = encodeWorkspaceFolders(merged)
            applyEnvironment()
            Task { await model.refreshSetupStatus() }
        }
    }

    @MainActor
    private func removeWorkspaceFolder(_ folder: String) {
        storedWorkspaceFolders = encodeWorkspaceFolders(workspaceFolders.filter { $0 != folder })
        applyEnvironment()
        Task { await model.refreshSetupStatus() }
    }

    @MainActor
    private func finishAndOpenDashboard() {
        onboardingCompleted = true
        openWindow(id: "dashboard")
        Task { await model.prepareDashboard() }
        dismiss()
    }
}
