import AppKit
import SwiftUI

final class HarnessAppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
    }
}

@main
struct HarnessApp: App {
    @NSApplicationDelegateAdaptor(HarnessAppDelegate.self) private var appDelegate
    @StateObject private var model = HarnessMenuBarModel()

    var body: some Scene {
        MenuBarExtra {
            MenuBarContentView(model: model)
        } label: {
            Label(model.snapshot.menuTitle, systemImage: model.snapshot.runtimeState.systemImage)
                .task {
                    model.startPolling()
                }
        }
        .menuBarExtraStyle(.menu)

        Settings {
            SettingsView(model: model)
        }
    }
}
