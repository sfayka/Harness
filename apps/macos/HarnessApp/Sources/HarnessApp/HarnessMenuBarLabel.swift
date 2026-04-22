import AppKit
import SwiftUI

struct HarnessMenuBarLabel: View {
    @Environment(\.openWindow) private var openWindow
    @ObservedObject var model: HarnessMenuBarModel
    @AppStorage(AppPreferenceKeys.onboardingCompleted) private var onboardingCompleted = false
    @AppStorage(AppPreferenceKeys.workspaceFolders) private var storedWorkspaceFolders = ""
    @State private var didRunLaunchTask = false

    var body: some View {
        Label(model.snapshot.menuTitle, systemImage: model.snapshot.runtimeState.systemImage)
            .task {
                guard !didRunLaunchTask else {
                    return
                }
                didRunLaunchTask = true
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
            }
    }
}
