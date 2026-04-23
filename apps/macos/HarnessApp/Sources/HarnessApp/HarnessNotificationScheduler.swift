import Foundation
import HarnessAppCore
import UserNotifications

enum HarnessNotificationUserInfoKey {
    static let destinationKind = "destination_kind"
    static let dashboardRoute = "dashboard_route"
    static let notificationID = "notification_id"
}

enum HarnessNotificationDestinationKind: String {
    case dashboard
    case setupAssistant = "setup_assistant"
}

extension Notification.Name {
    static let harnessNotificationDestinationRequested = Notification.Name(
        "com.knoxanalytics.harness.notification.destinationRequested"
    )
}

@MainActor
final class HarnessNotificationDestinationBroker {
    static let shared = HarnessNotificationDestinationBroker()

    private var pendingUserInfo: [AnyHashable: Any]?

    private init() {}

    func request(userInfo: [AnyHashable: Any]) {
        pendingUserInfo = userInfo
        NotificationCenter.default.post(
            name: .harnessNotificationDestinationRequested,
            object: nil,
            userInfo: userInfo
        )
    }

    func takePendingUserInfo() -> [AnyHashable: Any]? {
        let userInfo = pendingUserInfo
        pendingUserInfo = nil
        return userInfo
    }

    func clearPendingUserInfo() {
        pendingUserInfo = nil
    }
}

@MainActor
final class HarnessNotificationScheduler {
    private let center: UNUserNotificationCenter
    private let defaults: UserDefaults

    init(
        center: UNUserNotificationCenter = .current(),
        defaults: UserDefaults = .standard
    ) {
        self.center = center
        self.defaults = defaults
    }

    func deliveredNotificationIDs() -> Set<String> {
        Set(defaults.stringArray(forKey: AppPreferenceKeys.deliveredNotificationIDs) ?? [])
    }

    func deliver(
        _ candidates: [HarnessAttentionNotification],
        notificationsEnabled: Bool
    ) async {
        guard notificationsEnabled, !candidates.isEmpty else {
            return
        }
        let settings = await center.notificationSettings()
        guard settings.authorizationStatus.allowsHarnessDelivery else {
            return
        }

        var deliveredIDs = deliveredNotificationIDs()
        for candidate in candidates where !deliveredIDs.contains(candidate.id) {
            do {
                try await center.add(request(for: candidate))
                deliveredIDs.insert(candidate.id)
            } catch {
                continue
            }
        }
        storeDeliveredNotificationIDs(deliveredIDs)
    }

    private func request(for candidate: HarnessAttentionNotification) -> UNNotificationRequest {
        let content = UNMutableNotificationContent()
        content.title = candidate.title
        content.body = candidate.body
        content.sound = .default
        content.userInfo = userInfo(for: candidate)
        return UNNotificationRequest(identifier: candidate.id, content: content, trigger: nil)
    }

    private func userInfo(for candidate: HarnessAttentionNotification) -> [String: String] {
        var userInfo = [
            HarnessNotificationUserInfoKey.notificationID: candidate.id
        ]
        switch candidate.destination {
        case .dashboard(let route):
            userInfo[HarnessNotificationUserInfoKey.destinationKind] = HarnessNotificationDestinationKind.dashboard.rawValue
            userInfo[HarnessNotificationUserInfoKey.dashboardRoute] = route.rawValue
        case .setupAssistant:
            userInfo[HarnessNotificationUserInfoKey.destinationKind] = HarnessNotificationDestinationKind.setupAssistant.rawValue
        }
        return userInfo
    }

    private func storeDeliveredNotificationIDs(_ ids: Set<String>) {
        let capped = Array(ids.sorted().suffix(500))
        defaults.set(capped, forKey: AppPreferenceKeys.deliveredNotificationIDs)
    }
}

private extension UNAuthorizationStatus {
    var allowsHarnessDelivery: Bool {
        switch self {
        case .authorized, .provisional, .ephemeral:
            return true
        case .notDetermined, .denied:
            return false
        @unknown default:
            return false
        }
    }
}
