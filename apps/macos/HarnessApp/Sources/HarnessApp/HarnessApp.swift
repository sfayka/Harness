import AppKit
import SwiftUI
import UserNotifications

final class HarnessAppDelegate: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        UNUserNotificationCenter.current().delegate = self
    }

    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification
    ) async -> UNNotificationPresentationOptions {
        [.banner, .sound]
    }

    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse
    ) async {
        await MainActor.run {
            HarnessNotificationDestinationBroker.shared.request(
                userInfo: response.notification.request.content.userInfo
            )
        }
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
            HarnessMenuBarLabel(model: model)
        }
        .menuBarExtraStyle(.menu)

        Window("Harness Setup", id: "onboarding") {
            OnboardingWindowView(model: model)
        }
        .defaultSize(width: 1040, height: 720)

        Window("Harness Dashboard", id: "dashboard") {
            DashboardWindowView(model: model)
        }
        .defaultSize(width: 1180, height: 820)

        Settings {
            SettingsView(model: model)
        }
    }
}
