import Foundation
import ServiceManagement
import UserNotifications

enum NotificationPermissionState: String {
    case authorized
    case denied
    case notDetermined
    case unknown

    var environmentValue: String {
        switch self {
        case .authorized:
            return "authorized"
        case .denied:
            return "denied"
        case .notDetermined:
            return "not_determined"
        case .unknown:
            return "unknown"
        }
    }

    var displayName: String {
        switch self {
        case .authorized:
            return "Authorized"
        case .denied:
            return "Denied"
        case .notDetermined:
            return "Not Asked"
        case .unknown:
            return "Unknown"
        }
    }
}
enum LaunchAtLoginState: String {
    case enabled
    case disabled
    case requiresApproval
    case unavailable
    case unknown

    var environmentValue: String {
        switch self {
        case .enabled:
            return "enabled"
        case .disabled, .requiresApproval, .unavailable:
            return "disabled"
        case .unknown:
            return "unknown"
        }
    }

    var displayName: String {
        switch self {
        case .enabled:
            return "Enabled"
        case .disabled:
            return "Disabled"
        case .requiresApproval:
            return "Needs Approval"
        case .unavailable:
            return "Unavailable"
        case .unknown:
            return "Unknown"
        }
    }
}

struct AppSetupEnvironment {
    let notificationPermission: NotificationPermissionState
    let launchAtLogin: LaunchAtLoginState
    let workspaceFolders: [String]

    var dictionary: [String: String] {
        var values: [String: String] = [
            "HARNESS_NOTIFICATION_PERMISSION": notificationPermission.environmentValue,
            "HARNESS_LAUNCH_AT_LOGIN": launchAtLogin.environmentValue
        ]
        if !workspaceFolders.isEmpty {
            values["HARNESS_WORKSPACE_FOLDERS"] = workspaceFolders.joined(separator: ":")
        }
        return values
    }
}

enum MacOSSetupState {
    static func notificationPermissionState() async -> NotificationPermissionState {
        let settings = await UNUserNotificationCenter.current().notificationSettings()
        switch settings.authorizationStatus {
        case .authorized, .provisional, .ephemeral:
            return .authorized
        case .denied:
            return .denied
        case .notDetermined:
            return .notDetermined
        @unknown default:
            return .unknown
        }
    }

    static func requestNotificationPermission() async -> NotificationPermissionState {
        do {
            let granted = try await UNUserNotificationCenter.current().requestAuthorization(
                options: [.alert, .sound, .badge]
            )
            if granted {
                return await notificationPermissionState()
            }
            return .denied
        } catch {
            return await notificationPermissionState()
        }
    }

    @MainActor
    static func launchAtLoginState() -> LaunchAtLoginState {
        switch SMAppService.mainApp.status {
        case .enabled:
            return .enabled
        case .notRegistered:
            return .disabled
        case .requiresApproval:
            return .requiresApproval
        case .notFound:
            return .unavailable
        @unknown default:
            return .unknown
        }
    }

    @MainActor
    static func setLaunchAtLogin(enabled: Bool) -> (state: LaunchAtLoginState, message: String?) {
        do {
            if enabled {
                try SMAppService.mainApp.register()
            } else {
                try SMAppService.mainApp.unregister()
            }
            return (launchAtLoginState(), nil)
        } catch {
            return (launchAtLoginState(), error.localizedDescription)
        }
    }
}
