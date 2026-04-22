import Foundation

public struct HarnessRuntimeCommand: Sendable {
    public let repoRoot: URL
    public let pythonExecutable: String
    public let environment: [String: String]

    public init(
        repoRoot: URL = HarnessRuntimeCommand.defaultRepoRoot(),
        pythonExecutable: String = ProcessInfo.processInfo.environment["HARNESS_PYTHON"] ?? "python3",
        environment: [String: String] = [:]
    ) {
        self.repoRoot = repoRoot
        self.pythonExecutable = pythonExecutable
        self.environment = environment
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

    public func withEnvironment(_ environment: [String: String]) -> HarnessRuntimeCommand {
        HarnessRuntimeCommand(
            repoRoot: repoRoot,
            pythonExecutable: pythonExecutable,
            environment: environment
        )
    }

    @discardableResult
    public func initializeRuntime() async throws -> CommandResult {
        try await runJSONCommand(["init"], allowNonZeroExit: false)
    }

    public func startRuntime() async throws -> RuntimeControlPayload {
        let result = try await runJSONCommand(["start"], allowNonZeroExit: false)
        return try JSONDecoder().decode(RuntimeControlPayload.self, from: Data(result.stdout.utf8))
    }

    @discardableResult
    public func stopRuntime() async throws -> RuntimeControlPayload {
        let result = try await runJSONCommand(["stop"], allowNonZeroExit: false)
        return try JSONDecoder().decode(RuntimeControlPayload.self, from: Data(result.stdout.utf8))
    }

    public func restartRuntime() async throws -> RuntimeControlPayload {
        _ = try? await stopRuntime()
        return try await startRuntime()
    }

    public func recoverRuntime() async throws -> RuntimeControlPayload {
        let result = try await runJSONCommand(["recover"], allowNonZeroExit: false)
        return try JSONDecoder().decode(RuntimeControlPayload.self, from: Data(result.stdout.utf8))
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

    @discardableResult
    public func setSecret(name: String, value: String) async throws -> CommandResult {
        try await runJSONCommand(
            ["secrets", "set", name, "--value-stdin"],
            allowNonZeroExit: false,
            stdin: value
        )
    }

    public func guidedSetupStatus(workflows: [String] = []) async throws -> GuidedSetupStatusPayload {
        let workflowArgs = workflows.flatMap { ["--workflow", $0] }
        let result = try await runJSONCommand(["setup", "status"] + workflowArgs, allowNonZeroExit: true)
        return try JSONDecoder().decode(GuidedSetupStatusPayload.self, from: Data(result.stdout.utf8))
    }

    public func runJSONCommand(
        _ args: [String],
        allowNonZeroExit: Bool,
        stdin: String? = nil
    ) async throws -> CommandResult {
        try await Task.detached(priority: .userInitiated) {
            try runProcess(
                repoRoot: repoRoot,
                pythonExecutable: pythonExecutable,
                args: ["-m", "modules.local_runtime", "--json"] + args,
                environment: environment,
                stdin: stdin,
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

public struct RuntimeControlPayload: Decodable, Equatable, Sendable {
    public let status: String
    public let message: String?
    public let nextAction: String?
    public let apiBaseURL: String?
    public let pid: Int?
    public let recovered: Bool?
    public let error: String?

    enum CodingKeys: String, CodingKey {
        case status
        case message
        case nextAction = "next_action"
        case apiBaseURL = "api_base_url"
        case pid
        case recovered
        case error
    }
}

private struct OpenPayload: Decodable {
    let url: String
}

public enum HarnessRuntimeCommandError: Error, LocalizedError, Equatable {
    case launchFailed(String)
    case commandFailed(exitCode: Int32, message: String)
    case invalidURL(String)

    public var errorDescription: String? {
        switch self {
        case .launchFailed(let message):
            return message
        case .commandFailed(let exitCode, let message):
            return "Harness runtime command failed with exit \(exitCode): \(message)"
        case .invalidURL(let value):
            return "Harness returned an invalid dashboard URL: \(value)"
        }
    }
}

private func runProcess(
    repoRoot: URL,
    pythonExecutable: String,
    args: [String],
    environment: [String: String],
    stdin: String?,
    allowNonZeroExit: Bool
) throws -> CommandResult {
    let process = Process()
    let stdoutPipe = Pipe()
    let stderrPipe = Pipe()
    let stdinPipe = stdin == nil ? nil : Pipe()
    process.currentDirectoryURL = repoRoot
    process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
    process.arguments = [pythonExecutable] + args
    process.environment = mergedProcessEnvironment(environment)
    process.standardOutput = stdoutPipe
    process.standardError = stderrPipe
    if let stdinPipe {
        process.standardInput = stdinPipe
    }
    do {
        try process.run()
        if let stdin, let stdinPipe {
            let data = Data(stdin.utf8)
            stdinPipe.fileHandleForWriting.write(data)
            stdinPipe.fileHandleForWriting.closeFile()
        }
    } catch {
        throw HarnessRuntimeCommandError.launchFailed(error.localizedDescription)
    }
    process.waitUntilExit()

    let stdout = String(data: stdoutPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
    let stderr = String(data: stderrPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
    let result = CommandResult(exitCode: process.terminationStatus, stdout: stdout, stderr: stderr)
    if !allowNonZeroExit && process.terminationStatus != 0 {
        throw HarnessRuntimeCommandError.commandFailed(
            exitCode: process.terminationStatus,
            message: commandFailureMessage(stdout: stdout, stderr: stderr)
        )
    }
    return result
}

private func mergedProcessEnvironment(_ environment: [String: String]) -> [String: String] {
    ProcessInfo.processInfo.environment.merging(environment) { _, appValue in appValue }
}

private func commandFailureMessage(stdout: String, stderr: String) -> String {
    if let data = stdout.data(using: .utf8),
       let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
        let message = payload["message"] as? String ?? payload["error"] as? String
        let nextAction = payload["next_action"] as? String
        if let message, let nextAction {
            return "\(message) \(nextAction)"
        }
        if let message {
            return message
        }
    }
    let trimmedStderr = stderr.trimmingCharacters(in: .whitespacesAndNewlines)
    if !trimmedStderr.isEmpty {
        return trimmedStderr
    }
    let trimmedStdout = stdout.trimmingCharacters(in: .whitespacesAndNewlines)
    return trimmedStdout.isEmpty ? "No error output was returned." : trimmedStdout
}
