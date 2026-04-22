# Harness macOS App

This is the native macOS shell for local Harness operation.
The first slice is a menu-bar controller with runtime controls and summary counts.

## Targets

- `HarnessApp`: SwiftUI/AppKit menu-bar app.
- `HarnessAppCore`: testable runtime/API parsing and summary logic.
- `HarnessAppCoreCheck`: lightweight validation executable for environments where SwiftPM test frameworks are unavailable.

## Validate

```bash
swift build
swift run HarnessAppCoreCheck
```

The repo-level launch path is:

```bash
./script/build_and_run.sh --verify
```

The app reads Harness through the local CLI and HTTP API contract. It must not read SQLite directly.
