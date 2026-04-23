import Foundation

public enum HarnessBundleResources {
    public static let runtimeExecutableEnvironmentKey = "HARNESS_RUNTIME_EXECUTABLE"
    public static let dashboardAssetsEnvironmentKey = "HARNESS_DASHBOARD_ASSETS_DIR"

    public static func runtimeExecutableURL(
        environment: [String: String] = ProcessInfo.processInfo.environment,
        infoDictionary: [String: Any] = Bundle.main.infoDictionary ?? [:],
        bundleURL: URL = Bundle.main.bundleURL,
        resourceURL: URL? = Bundle.main.resourceURL
    ) -> URL? {
        if let configured = clean(environment[runtimeExecutableEnvironmentKey]) {
            let url = URL(fileURLWithPath: configured)
            return FileManager.default.isExecutableFile(atPath: url.path) ? url : nil
        }
        if let configured = clean(infoDictionary["HarnessRuntimeExecutable"] as? String) {
            let url = resolveBundlePath(configured, bundleURL: bundleURL, resourceURL: resourceURL)
            return FileManager.default.isExecutableFile(atPath: url.path) ? url : nil
        }
        guard let resourceURL else {
            return nil
        }
        let defaultURL = resourceURL
            .appendingPathComponent("HarnessRuntime", isDirectory: true)
            .appendingPathComponent("harness", isDirectory: false)
        return FileManager.default.isExecutableFile(atPath: defaultURL.path) ? defaultURL : nil
    }

    public static func dashboardAssetsURL(
        environment: [String: String] = ProcessInfo.processInfo.environment,
        infoDictionary: [String: Any] = Bundle.main.infoDictionary ?? [:],
        bundleURL: URL = Bundle.main.bundleURL,
        resourceURL: URL? = Bundle.main.resourceURL
    ) -> URL? {
        if let configured = clean(environment[dashboardAssetsEnvironmentKey]) {
            let url = URL(fileURLWithPath: configured, isDirectory: true)
            return FileManager.default.fileExists(atPath: url.appendingPathComponent("index.html").path) ? url : nil
        }
        if let configured = clean(infoDictionary["HarnessDashboardAssetsDir"] as? String) {
            let url = resolveBundlePath(configured, bundleURL: bundleURL, resourceURL: resourceURL)
            return FileManager.default.fileExists(atPath: url.appendingPathComponent("index.html").path) ? url : nil
        }
        guard let resourceURL else {
            return nil
        }
        let defaultURL = resourceURL.appendingPathComponent("Dashboard", isDirectory: true)
        return FileManager.default.fileExists(atPath: defaultURL.appendingPathComponent("index.html").path)
            ? defaultURL
            : nil
    }

    private static func resolveBundlePath(_ path: String, bundleURL: URL, resourceURL: URL?) -> URL {
        if path.hasPrefix("/") {
            return URL(fileURLWithPath: path)
        }
        if path.hasPrefix("Contents/") {
            return bundleURL.appendingPathComponent(path, isDirectory: false)
        }
        if let resourceURL {
            return resourceURL.appendingPathComponent(path, isDirectory: false)
        }
        return bundleURL.appendingPathComponent(path, isDirectory: false)
    }

    private static func clean(_ value: String?) -> String? {
        guard let value else {
            return nil
        }
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }
}
