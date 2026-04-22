import Foundation

public struct HarnessAPIClient: Sendable {
    private let session: URLSession
    private let decoder: JSONDecoder

    public init(session: URLSession = .shared, decoder: JSONDecoder = JSONDecoder()) {
        self.session = session
        self.decoder = decoder
    }

    public func fetchTasks(apiBaseURL: String) async throws -> TaskListPayload {
        try await fetch(TaskListPayload.self, apiBaseURL: apiBaseURL, path: "/tasks")
    }

    public func fetchSupervisionQueue(apiBaseURL: String) async throws -> SupervisionQueuePayload {
        try await fetch(SupervisionQueuePayload.self, apiBaseURL: apiBaseURL, path: "/supervision/queue")
    }

    private func fetch<T: Decodable>(
        _ type: T.Type,
        apiBaseURL: String,
        path: String
    ) async throws -> T {
        guard let baseURL = URL(string: apiBaseURL) else {
            throw HarnessAPIError.invalidBaseURL(apiBaseURL)
        }
        let url = baseURL.appending(path: path)
        let (data, response) = try await session.data(from: url)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw HarnessAPIError.invalidResponse
        }
        guard (200..<300).contains(httpResponse.statusCode) else {
            throw HarnessAPIError.httpStatus(httpResponse.statusCode)
        }
        return try decoder.decode(type, from: data)
    }
}

public enum HarnessAPIError: Error, LocalizedError, Equatable {
    case invalidBaseURL(String)
    case invalidResponse
    case httpStatus(Int)

    public var errorDescription: String? {
        switch self {
        case .invalidBaseURL(let value):
            return "Invalid Harness API URL: \(value)"
        case .invalidResponse:
            return "Harness API returned a non-HTTP response."
        case .httpStatus(let statusCode):
            return "Harness API returned HTTP \(statusCode)."
        }
    }
}
