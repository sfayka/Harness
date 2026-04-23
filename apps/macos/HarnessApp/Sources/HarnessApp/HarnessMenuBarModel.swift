import AppKit
import Foundation
import HarnessAppCore

@MainActor
final class HarnessMenuBarModel: ObservableObject {
    @Published private(set) var snapshot: HarnessMenuSnapshot = .initial
    @Published private(set) var isBusy = false
    @Published private(set) var lastDoctorMessage: String?
    @Published private(set) var dashboardURL: URL?
    @Published private(set) var dashboardMessage = "Open the dashboard to inspect full Harness progress."
    @Published private(set) var isPreparingDashboard = false
    @Published private(set) var selectedDashboardRoute: DashboardRoute = .tasks
    @Published private(set) var setupStatus: GuidedSetupStatusPayload?
    @Published private(set) var setupMessage = "Setup has not been checked yet."
    @Published private(set) var isCheckingSetup = false

    private var runtime: HarnessRuntimeCommand
    private let apiClient: HarnessAPIClient
    private let notificationScheduler: HarnessNotificationScheduler
    private var pollingTask: Task<Void, Never>?
    private var attentionNotificationsEnabled: Bool

    init(
        runtime: HarnessRuntimeCommand = HarnessRuntimeCommand(),
        apiClient: HarnessAPIClient = HarnessAPIClient(),
        notificationScheduler: HarnessNotificationScheduler? = nil,
        attentionNotificationsEnabled: Bool = UserDefaults.standard.object(forKey: AppPreferenceKeys.attentionNotificationsEnabled) as? Bool ?? true
    ) {
        self.runtime = runtime
        self.apiClient = apiClient
        self.notificationScheduler = notificationScheduler ?? HarnessNotificationScheduler()
        self.attentionNotificationsEnabled = attentionNotificationsEnabled
    }

    deinit {
        pollingTask?.cancel()
    }

    func startPolling() {
        guard pollingTask == nil else {
            return
        }
        pollingTask = Task {
            while !Task.isCancelled {
                await refresh()
                try? await Task.sleep(for: .seconds(10))
            }
        }
    }

    func refresh() async {
        do {
            let runtimeStatus = try await runtime.runtimeStatus()
            var tasks: TaskListPayload?
            var queue: SupervisionQueuePayload?
            if runtimeStatus.status == "running", let apiBaseURL = runtimeStatus.apiBaseURL {
                async let fetchedTasks = try? apiClient.fetchTasks(apiBaseURL: apiBaseURL)
                async let fetchedQueue = try? apiClient.fetchSupervisionQueue(apiBaseURL: apiBaseURL)
                tasks = await fetchedTasks
                queue = await fetchedQueue
            }
            snapshot = HarnessMenuSummaryBuilder.build(
                runtimeStatus: runtimeStatus,
                tasks: tasks,
                queue: queue
            )
            await publishAttentionNotifications(tasks: tasks, queue: queue, setupStatus: setupStatus)
        } catch {
            snapshot = HarnessMenuSummaryBuilder.errorSnapshot(error.localizedDescription)
        }
    }

    func updateAppEnvironment(_ environment: [String: String]) {
        runtime = runtime.withEnvironment(environment)
    }

    func setAttentionNotificationsEnabled(_ enabled: Bool) {
        attentionNotificationsEnabled = enabled
    }

    func selectDashboardRoute(_ route: DashboardRoute) {
        selectedDashboardRoute = route
    }

    func refreshSetupStatus(workflows: [String] = []) async {
        guard !isCheckingSetup else {
            return
        }
        isCheckingSetup = true
        setupMessage = "Checking setup..."
        do {
            let status = try await runtime.guidedSetupStatus(workflows: workflows)
            setupStatus = status
            setupMessage = status.onboardingComplete
                ? "Core local setup is ready."
                : "Setup needs attention before onboarding can finish."
        } catch {
            setupStatus = nil
            setupMessage = "Setup could not be checked: \(error.localizedDescription)"
        }
        await publishAttentionNotifications(tasks: nil, queue: nil, setupStatus: setupStatus)
        isCheckingSetup = false
    }

    func initializeAndValidateRuntime() async {
        await runControlAction("Initializing Harness...") {
            _ = try await runtime.initializeRuntime()
            setupStatus = try await runtime.guidedSetupStatus()
            setupMessage = setupStatus?.onboardingComplete == true
                ? "Core local setup is ready."
                : "Runtime initialized. Review remaining setup items."
        }
    }

    func saveSecretAndValidate(name: String, value: String) async {
        await runControlAction("Saving setup secret...") {
            _ = try await runtime.setSecret(name: name, value: value)
            setupStatus = try await runtime.guidedSetupStatus()
            setupMessage = "Saved \(name) and refreshed setup validation."
        }
    }

    func startRuntime() async {
        await runControlAction("Starting Harness...") {
            let result = try await runtime.startRuntime()
            setupStatus = try await runtime.guidedSetupStatus()
            setupMessage = result.message ?? "Runtime started."
        }
    }

    func stopRuntime() async {
        await runControlAction("Stopping Harness...") {
            let result = try await runtime.stopRuntime()
            setupMessage = result.message ?? "Runtime stopped."
        }
    }

    func restartRuntime() async {
        await runControlAction("Restarting Harness...") {
            let result = try await runtime.restartRuntime()
            setupStatus = try await runtime.guidedSetupStatus()
            setupMessage = result.message ?? "Runtime restarted."
        }
    }

    func recoverRuntime() async {
        await runControlAction("Recovering Harness...") {
            let result = try await runtime.recoverRuntime()
            setupStatus = try await runtime.guidedSetupStatus()
            setupMessage = result.message ?? "Runtime recovered."
        }
    }

    func startRuntimeAfterLogin() async {
        await runControlAction("Starting Harness after login...") {
            let result = try await runtime.startRuntime()
            setupStatus = try await runtime.guidedSetupStatus()
            setupMessage = result.message ?? "Runtime started after login."
        }
    }

    func runDoctor() async {
        await runControlAction("Running doctor...") {
            let result = try await runtime.doctorSummary()
            let passCount = result.summary?["pass"] ?? 0
            let warnCount = result.summary?["warn"] ?? 0
            let failCount = result.summary?["fail"] ?? 0
            lastDoctorMessage = "Doctor \(result.status): \(passCount) pass, \(warnCount) warn, \(failCount) fail"
            setupStatus = try await runtime.guidedSetupStatus()
            setupMessage = "Doctor \(result.status): \(passCount) pass, \(warnCount) warn, \(failCount) fail"
        }
    }

    func prepareDashboard() async {
        guard !isPreparingDashboard else {
            return
        }
        isPreparingDashboard = true
        dashboardMessage = "Preparing the local dashboard..."
        do {
            let status = try await runtime.runtimeStatus()
            if status.status != "running" {
                dashboardMessage = "Starting local Harness runtime..."
                _ = try await runtime.startRuntime()
                try? await Task.sleep(for: .seconds(1))
            }
            dashboardURL = try await runtime.dashboardURL()
            dashboardMessage = "Dashboard is connected to the local Harness runtime."
            await refresh()
        } catch {
            dashboardURL = nil
            dashboardMessage = "Dashboard is unavailable: \(error.localizedDescription)"
        }
        isPreparingDashboard = false
    }

    func openDashboardInBrowser(routeURL: URL?) {
        if let routeURL {
            NSWorkspace.shared.open(routeURL)
        } else if let dashboardURL {
            NSWorkspace.shared.open(dashboardURL)
        }
    }

    func copyDashboardURL(_ routeURL: URL?) {
        let value = routeURL?.absoluteString ?? dashboardURL?.absoluteString
        guard let value else {
            return
        }
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(value, forType: .string)
    }

    func openLogs() {
        let logPath = snapshot.logDirectory ?? defaultLogDirectory()
        NSWorkspace.shared.open(URL(fileURLWithPath: logPath, isDirectory: true))
    }

    private func runControlAction(
        _ progressMessage: String,
        operation: () async throws -> Void
    ) async {
        guard !isBusy else {
            return
        }
        isBusy = true
        lastDoctorMessage = nil
        snapshot = HarnessMenuSnapshot(
            runtimeState: snapshot.runtimeState,
            activeTaskCount: snapshot.activeTaskCount,
            reviewNeededCount: snapshot.reviewNeededCount,
            repairNeededCount: snapshot.repairNeededCount,
            apiBaseURL: snapshot.apiBaseURL,
            logDirectory: snapshot.logDirectory,
            message: progressMessage
        )
        do {
            try await operation()
            await refresh()
        } catch {
            snapshot = HarnessMenuSummaryBuilder.errorSnapshot(error.localizedDescription)
            setupMessage = error.localizedDescription
        }
        isBusy = false
    }

    private func defaultLogDirectory() -> String {
        let home = FileManager.default.homeDirectoryForCurrentUser
        return home
            .appendingPathComponent("Library")
            .appendingPathComponent("Logs")
            .appendingPathComponent("Harness")
            .path
    }

    private func publishAttentionNotifications(
        tasks: TaskListPayload?,
        queue: SupervisionQueuePayload?,
        setupStatus: GuidedSetupStatusPayload?
    ) async {
        let candidates = HarnessAttentionNotificationPlanner.plan(
            tasks: tasks,
            queue: queue,
            setupStatus: setupStatus,
            deliveredNotificationIDs: notificationScheduler.deliveredNotificationIDs()
        )
        await notificationScheduler.deliver(
            candidates,
            notificationsEnabled: attentionNotificationsEnabled
        )
    }
}
