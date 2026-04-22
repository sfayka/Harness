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
    @Published private(set) var setupStatus: GuidedSetupStatusPayload?
    @Published private(set) var setupMessage = "Setup has not been checked yet."
    @Published private(set) var isCheckingSetup = false

    private var runtime: HarnessRuntimeCommand
    private let apiClient: HarnessAPIClient
    private var pollingTask: Task<Void, Never>?

    init(
        runtime: HarnessRuntimeCommand = HarnessRuntimeCommand(),
        apiClient: HarnessAPIClient = HarnessAPIClient()
    ) {
        self.runtime = runtime
        self.apiClient = apiClient
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
        } catch {
            snapshot = HarnessMenuSummaryBuilder.errorSnapshot(error.localizedDescription)
        }
    }

    func updateAppEnvironment(_ environment: [String: String]) {
        runtime = runtime.withEnvironment(environment)
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
            try await runtime.startRuntime()
            setupStatus = try await runtime.guidedSetupStatus()
            setupMessage = setupStatus?.onboardingComplete == true
                ? "Core local setup is ready."
                : "Runtime started. Review remaining setup items."
        }
    }

    func stopRuntime() async {
        await runControlAction("Stopping Harness...") {
            _ = try await runtime.stopRuntime()
        }
    }

    func restartRuntime() async {
        await runControlAction("Restarting Harness...") {
            try await runtime.restartRuntime()
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
                try await runtime.startRuntime()
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
}
