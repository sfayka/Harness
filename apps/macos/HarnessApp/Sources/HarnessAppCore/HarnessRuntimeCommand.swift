import Foundation

public struct HarnessRuntimeCommand: Sendable {
    public let repoRoot: URL
    public let pythonExecutable: String

    public init(
        repoRoot: URL = HarnessRuntimeCommand.defaultRepoRoot(),
        pythonExecutable: String = ProcessInfo.processInfo.environment["HARNESS_PYTHON"] ?? "python3"
    ) {
        self.repoRoot = repoRoot
        self.pythonExecutable = pythonExecutable
    }

    public static func defaultRepoRoot() -> URL {
        if let configured = ProcessInfo.processInfo.environment["HARNESS_REPO_ROOT"], !configured.isEmpty {
            return URL(fileURLWithPath: configured)
        }
        if let bundled = Bundle.main.object(forInfoDictionaryKey: "HarnessRepoRoot") as? String, !bundled.isEmpty {
            return URL(fileURLWithPath: bundled)
        }
        let bundleURL = Bundle.main.bundleURL
        if bundleURL.pathExtension == "app" {
            return bundleURL
                .deletingLastPathComponent()
                .deletingLastPathComponent()
                .deletingLastPathComponent()
        }
        return URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
    }

    public func runtimeStatus() async throws -> RuntimeStatusPayload {
        let result = try await runJSONCommand(["status"], allowNonZeroExit: true)
        return try JSONDecoder().decode(RuntimeStatusPayload.self, from: Data(result.stdout.utf8))
    }

    @discardableResult
    public func initializeRuntime() async throws -> CommandResult {
        try await runJSONCommand(["init"], allowNonZeroExit: false)
    }

    public func startRuntime() async throws {
        _ = try await initializeRuntime()
        try await Task.detached(priority: .userInitiated) {
            let process = Process()
            process.currentDirectoryURL = repoRoot
            process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
            process.arguments = [pythonExecutable, "-m", "modules.local_runtime", "serve"]
            try process.run()
        }.value
    }

    @discardableResult
    public func stopRuntime() async throws -> CommandResult {
        try await runJSONCommand(["stop"], allowNonZeroExit: false)
    }

    public func restartRuntime() async throws {
        _ = try? await stopRuntime()
        try await startRuntime()
    }

    public func dashboardURL() async throws -> URL {
        let result = try await runJSONCommand(["open", "--print-url"], allowNonZeroExit: false)
        let payload = try JSONDecoder().decode(OpenPayload.self, from: Data(result.stdout.utf8))
        guard let url = URL(string: payload.url) else {
            throw HarnessRuntimeCommandError.invalidURL(payload.url)
        }
        return url
    }

    public func doctorSummary() async throws -> DoctorSummary {
        let result = try await runJSONCommand(["doctor"], allowNonZeroExit: true)
        return try JSONDecoder().decode(DoctorSummary.self, from: Data(result.stdout.utf8))
    }

    public func runJSONCommand(
        _ args: [String],
        allowNonZeroExit: Bool
    ) async throws -> CommandResult {
        try await Task.detached(priority: .userInitiated) {
            try runProcess(
                repoRoot: repoRoot,
                pythonExecutable: pythonExecutable,
                args: ["-m", "modules.local_runtime", "--json"] + args,
                allowNonZeroExit: allowNonZeroExit
            )
        }.value
    }
}

public struct CommandResult: Equatable, Sendable {
    public let exitCode: Int32
    public let stdout: String
    public let stderr: String
}

public struct DoctorSummary: Decodable, Equatable, Sendable {
    public let status: String
    public let summary: [String: Int]?
}

private struct OpenPayload: Decodable {
    let url: String
}

public enum HarnessRuntimeCommandError: Error, LocalizedError, Equatable {
    case launchFailed(String)
    case commandFailed(exitCode: Int32, stderr: String)
    case invalidURL(String)

    public var errorDescription: String? {
        switch self {
        case .launchFailed(let message):
            return message
        case .commandFailed(let exitCode, let stderr):
            return "Harness runtime command failed with exit \(exitCode): \(stderr)"
        case .invalidURL(let value):
            return "Harness returned an invalid dashboard URL: \(value)"
        }
    }
}

private func runProcess(
    repoRoot: URL,
    pythonExecutable: String,
    args: [String],
    allowNonZeroExit: Bool
) throws -> CommandResult {
    let process = Process()
    let stdoutPipe = Pipe()
    let stderrPipe = Pipe()
    process.currentDirectoryURL = repoRoot
    process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
    process.arguments = [pythonExecutable] + args
    process.standardOutput = stdoutPipe
    process.standardError = stderrPipe
    do {
        try process.run()
    } catch {
        throw HarnessRuntimeCommandError.launchFailed(error.localizedDescription)
    }
    process.waitUntilExit()

    let stdout = String(data: stdoutPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
    let stderr = String(data: stderrPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
    let result = CommandResult(exitCode: process.terminationStatus, stdout: stdout, stderr: stderr)
    if !allowNonZeroExit && process.terminationStatus != 0 {
        throw HarnessRuntimeCommandError.commandFailed(exitCode: process.terminationStatus, stderr: stderr)
    }
    return result
}
