import Foundation

public enum DashboardRoute: String, CaseIterable, Identifiable, Sendable {
    case tasks
    case verification
    case reconciliation
    case reviews
    case execution

    public var id: String { rawValue }

    public var title: String {
        switch self {
        case .tasks:
            return "Tasks"
        case .verification:
            return "Verification"
        case .reconciliation:
            return "Reconciliation"
        case .reviews:
            return "Reviews"
        case .execution:
            return "Execution"
        }
    }

    public var path: String {
        switch self {
        case .tasks:
            return "/dashboard/tasks/"
        case .verification:
            return "/dashboard/verification/"
        case .reconciliation:
            return "/dashboard/reconciliation/"
        case .reviews:
            return "/dashboard/reviews/"
        case .execution:
            return "/dashboard/execution/"
        }
    }
}

public extension URL {
    func dashboardRoute(_ route: DashboardRoute) -> URL {
        guard var components = URLComponents(url: self, resolvingAgainstBaseURL: false) else {
            return self
        }
        components.path = route.path
        components.query = nil
        components.fragment = nil
        return components.url ?? self
    }
}
