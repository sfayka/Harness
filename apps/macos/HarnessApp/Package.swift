// swift-tools-version: 5.9

import PackageDescription

let package = Package(
    name: "HarnessApp",
    platforms: [
        .macOS(.v14)
    ],
    products: [
        .executable(name: "HarnessApp", targets: ["HarnessApp"]),
        .executable(name: "HarnessAppCoreCheck", targets: ["HarnessAppCoreCheck"]),
        .library(name: "HarnessAppCore", targets: ["HarnessAppCore"])
    ],
    targets: [
        .target(
            name: "HarnessAppCore",
            path: "Sources/HarnessAppCore"
        ),
        .executableTarget(
            name: "HarnessApp",
            dependencies: ["HarnessAppCore"],
            path: "Sources/HarnessApp"
        ),
        .executableTarget(
            name: "HarnessAppCoreCheck",
            dependencies: ["HarnessAppCore"],
            path: "Sources/HarnessAppCoreCheck"
        )
    ]
)
