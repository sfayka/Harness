import AppKit
import HarnessAppCore
import SwiftUI

struct HarnessMenuBarLabel: View {
    @Environment(\.openWindow) private var openWindow
    @ObservedObject var model: HarnessMenuBarModel
    @AppStorage(AppPreferenceKeys.onboardingCompleted) private var onboardingCompleted = false
    @AppStorage(AppPreferenceKeys.workspaceFolders) private var storedWorkspaceFolders = ""
    @AppStorage(AppPreferenceKeys.attentionNotificationsEnabled) private var attentionNotificationsEnabled = true
    @State private var didRunLaunchTask = false

    var body: some View {
        Label(model.snapshot.menuTitle, systemImage: model.snapshot.runtimeState.systemImage)
            .task {
                guard !didRunLaunchTask else {
                    return
                }
                didRunLaunchTask = true
                model.setAttentionNotificationsEnabled(attentionNotificationsEnabled)
                model.startPolling()
                let launchState = MacOSSetupState.launchAtLoginState()
                let notificationState = await MacOSSetupState.notificationPermissionState()
                model.updateAppEnvironment(
                    AppSetupEnvironment(
                        notificationPermission: notificationState,
                        launchAtLogin: launchState,
                        workspaceFolders: decodeWorkspaceFolders(storedWorkspaceFolders)
                    ).dictionary
                )
                if onboardingCompleted {
                    if launchState == .enabled {
                        await model.startRuntimeAfterLogin()
                    } else {
                        await model.refreshSetupStatus()
                    }
                } else {
                    await model.refreshSetupStatus()
                }
                if !onboardingCompleted {
                    openWindow(id: "onboarding")
                    NSApp.activate(ignoringOtherApps: true)
                }
                if let pendingUserInfo = HarnessNotificationDestinationBroker.shared.takePendingUserInfo() {
                    openNotificationDestination(userInfo: pendingUserInfo)
                }
            }
            .onChange(of: attentionNotificationsEnabled) { _, enabled in
                model.setAttentionNotificationsEnabled(enabled)
            }
            .onReceive(NotificationCenter.default.publisher(for: .harnessNotificationDestinationRequested)) { notification in
                HarnessNotificationDestinationBroker.shared.clearPendingUserInfo()
                openNotificationDestination(userInfo: notification.userInfo ?? [:])
            }
    }

    private func openNotificationDestination(userInfo: [AnyHashable: Any]) {
        let destinationKind = userInfo[HarnessNotificationUserInfoKey.destinationKind] as? String
        if destinationKind == HarnessNotificationDestinationKind.setupAssistant.rawValue {
            openWindow(id: "onboarding")
            NSApp.activate(ignoringOtherApps: true)
            Task { await model.refreshSetupStatus() }
            return
        }

        let routeValue = userInfo[HarnessNotificationUserInfoKey.dashboardRoute] as? String
        let route = routeValue.flatMap(DashboardRoute.init(rawValue:)) ?? .tasks
        model.selectDashboardRoute(route)
        openWindow(id: "dashboard")
        NSApp.activate(ignoringOtherApps: true)
        Task { await model.prepareDashboard() }
    }
}
