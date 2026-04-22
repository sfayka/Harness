import AppKit
import SwiftUI

struct HarnessMenuBarLabel: View {
    @Environment(\.openWindow) private var openWindow
    @ObservedObject var model: HarnessMenuBarModel
    @AppStorage(AppPreferenceKeys.onboardingCompleted) private var onboardingCompleted = false
    @State private var didRunLaunchTask = false

    var body: some View {
        Label(model.snapshot.menuTitle, systemImage: model.snapshot.runtimeState.systemImage)
            .task {
                guard !didRunLaunchTask else {
                    return
                }
                didRunLaunchTask = true
                model.startPolling()
                await model.refreshSetupStatus()
                if !onboardingCompleted {
                    openWindow(id: "onboarding")
                    NSApp.activate(ignoringOtherApps: true)
                }
            }
    }
}
