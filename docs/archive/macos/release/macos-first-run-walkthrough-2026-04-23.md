# macOS First-Run Walkthrough Proof

Date: 2026-04-23

## Purpose

Prove that the macOS app can be launched from a clean first-run state, reach local runtime readiness, and open the embedded dashboard against local SQLite-backed Harness state.

## Isolation

This walkthrough intentionally avoided the normal app identity and default runtime paths.

- Bundle ID: `com.knoxanalytics.harness.local.first-run-proof.20260423b`
- Data root: `/tmp/harness-first-run.TSNhle/data`
- Log root: `/tmp/harness-first-run.TSNhle/logs`
- Runtime port: `18767`
- Dashboard assets: `dist/local-dashboard`

## Commands Run

Swift validation required the installed macOS 15 SDK because the selected CommandLineTools macOS 26 SDK is not compatible with the selected Swift compiler on this machine.

```bash
env SDKROOT=/Library/Developer/CommandLineTools/SDKs/MacOSX15.sdk \
  CLANG_MODULE_CACHE_PATH=/tmp/harness-clang-module-cache \
  swift build

env SDKROOT=/Library/Developer/CommandLineTools/SDKs/MacOSX15.sdk \
  CLANG_MODULE_CACHE_PATH=/tmp/harness-clang-module-cache \
  swift run HarnessAppCoreCheck
```

The local app launch path was run with an isolated app identity and runtime:

```bash
SDKROOT=/Library/Developer/CommandLineTools/SDKs/MacOSX15.sdk \
CLANG_MODULE_CACHE_PATH=/tmp/harness-clang-module-cache \
HARNESS_DEV_BUNDLE_ID=com.knoxanalytics.harness.local.first-run-proof.20260423b \
HARNESS_APP_DATA_DIR=/tmp/harness-first-run.TSNhle/data \
HARNESS_APP_LOG_DIR=/tmp/harness-first-run.TSNhle/logs \
HARNESS_RUNTIME_PORT=18767 \
./script/build_and_run.sh --verify
```

Runtime readiness was verified against the same isolated data and log paths:

```bash
HARNESS_APP_DATA_DIR=/tmp/harness-first-run.TSNhle/data \
HARNESS_APP_LOG_DIR=/tmp/harness-first-run.TSNhle/logs \
HARNESS_DASHBOARD_ASSETS_DIR=$PWD/dist/local-dashboard \
python3 -m modules.local_runtime --json status
```

The status response showed:

- `status: running`
- `api_base_url: http://127.0.0.1:18767`
- `health.status: ok`
- `store_backend: sqlite`
- `database_schema_ready: true`

## Screenshots

The current how-to screenshots were captured from this walkthrough:

- `docs/howto/images/macos-onboarding-welcome.png`
- `docs/howto/images/macos-onboarding-ready.png`
- `docs/howto/images/macos-dashboard-tasks.png`

## Result

The first-run setup assistant moved from `1 blocker` to `Ready`, and the embedded dashboard loaded the real local dashboard UI at `127.0.0.1:18767/dashboard/tasks/`.

The first attempt exposed a real dev-launch gap: the runtime was healthy, but the embedded dashboard returned `{"detail":"Not Found"}` because the dev `.app` did not receive a dashboard assets directory. `script/build_and_run.sh` now passes `dist/local-dashboard/` automatically when it exists.

## Remaining Release Gate

This proves the local first-run path. It does not prove external distribution. Official release still needs a Developer ID signed and notarized DMG walkthrough.
