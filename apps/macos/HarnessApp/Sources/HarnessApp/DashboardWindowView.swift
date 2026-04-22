import HarnessAppCore
import SwiftUI

struct DashboardWindowView: View {
    @ObservedObject var model: HarnessMenuBarModel
    @State private var selectedRoute: DashboardRoute = .tasks

    var body: some View {
        VStack(spacing: 0) {
            DashboardToolbar(
                selectedRoute: $selectedRoute,
                routeURL: routeURL,
                model: model
            )

            Divider()

            if model.isPreparingDashboard {
                DashboardUnavailableView(
                    title: "Preparing Dashboard",
                    message: model.dashboardMessage,
                    actionTitle: nil,
                    action: nil
                )
            } else if let routeURL {
                DashboardWebView(url: routeURL)
            } else {
                DashboardUnavailableView(
                    title: "Dashboard Unavailable",
                    message: model.dashboardMessage,
                    actionTitle: "Start Harness",
                    action: {
                        Task { await model.prepareDashboard() }
                    }
                )
            }
        }
        .frame(minWidth: 880, minHeight: 620)
        .task {
            await model.prepareDashboard()
        }
    }

    private var routeURL: URL? {
        model.dashboardURL?.dashboardRoute(selectedRoute)
    }
}

private struct DashboardToolbar: View {
    @Binding var selectedRoute: DashboardRoute
    let routeURL: URL?
    @ObservedObject var model: HarnessMenuBarModel

    var body: some View {
        HStack(spacing: 12) {
            Picker("Dashboard Route", selection: $selectedRoute) {
                ForEach(DashboardRoute.allCases) { route in
                    Text(route.title).tag(route)
                }
            }
            .pickerStyle(.segmented)
            .frame(maxWidth: 520)

            Spacer()

            Button("Refresh") {
                Task { await model.prepareDashboard() }
            }

            Button("Copy URL") {
                model.copyDashboardURL(routeURL)
            }
            .disabled(routeURL == nil)

            Button("Open in Browser") {
                model.openDashboardInBrowser(routeURL: routeURL)
            }
            .disabled(routeURL == nil)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .background(.bar)
    }
}

private struct DashboardUnavailableView: View {
    let title: String
    let message: String
    let actionTitle: String?
    let action: (() -> Void)?

    var body: some View {
        ContentUnavailableView {
            Label(title, systemImage: "rectangle.connected.to.line.below")
        } description: {
            Text(message)
        } actions: {
            if let actionTitle, let action {
                Button(actionTitle, action: action)
            }
        }
    }
}
