# Reader-Facing Command Verification

Date: 2026-04-27

## Purpose

Re-run the commands shown in the reader-facing Harness docs after the macOS first-run UI, packaged dashboard, and installer flow landed.

The live reset smoke command is not rerun in this pass because it creates real GitHub and Linear dry-run artifacts. That gate is tracked separately in `live-reset-smoke-2026-04-23.md`.

## Environment Notes

Some commands had to run outside the Codex sandbox because they bind loopback ports or because Turbopack starts worker processes that the sandbox blocks.

Swift and package builds used the installed macOS 15 SDK:

```bash
SDKROOT=/Library/Developer/CommandLineTools/SDKs/MacOSX15.sdk
CLANG_MODULE_CACHE_PATH=/tmp/harness-clang-module-cache
```

Reason: this host's selected CommandLineTools macOS 26 SDK is mismatched with the selected Swift compiler. That is a host toolchain issue, not a Harness runtime issue.

The worktree still contains unrelated untracked duplicate `* 2` files. For Swift/package validation, the duplicate Swift source was temporarily moved out and restored so SwiftPM saw the tracked source set.

## Passed Commands

Backend and reset validation:

```bash
python3 -m unittest tests.test_fastapi_backend tests.test_reset_dryrun tests.test_autonomous_dryrun tests.test_unattended_dryruns -v
python3 -m unittest discover -s tests
python3 -m modules.reset_dryrun success
python3 -m modules.reset_dryrun review
```

Results:

- fast backend/reset/autonomous/unattended suite: `25` tests passed
- full backend suite: `842` tests passed, `17` skipped
- reset success: final verdict `verified_done`
- reset review: final verdict `needs_review`

Frontend validation:

```bash
pnpm lint
pnpm build
pnpm build:dashboard:local
```

Results:

- lint passed
- Next.js production build passed
- local dashboard static asset build passed and wrote `dist/local-dashboard`

Local runtime lifecycle, using isolated temp data/log paths and a non-default port:

```bash
export HARNESS_APP_DATA_DIR=/tmp/harness-reader-runtime-assets.9JIWFV/data
export HARNESS_APP_LOG_DIR=/tmp/harness-reader-runtime-assets.9JIWFV/logs
export HARNESS_DASHBOARD_ASSETS_DIR="$PWD/dist/local-dashboard"
python3 -m modules.local_runtime --json init --port 18771
python3 -m modules.local_runtime --json start --port 18771
python3 -m modules.local_runtime --json status
python3 -m modules.local_runtime --json doctor
python3 -m modules.local_runtime --json recover
python3 -m modules.local_runtime --json stop
```

Results:

- runtime initialized local SQLite state
- runtime started and reported `status: running`
- health reported `status: ok`
- doctor reported `fail: 0`
- dashboard check passed when `HARNESS_DASHBOARD_ASSETS_DIR` pointed at `dist/local-dashboard`
- recover restarted the runtime cleanly
- stop shut the runtime down

Health endpoint:

```bash
python3 -m uvicorn backend.server:app --host 127.0.0.1 --port 8000
curl -sS http://127.0.0.1:8000/health
```

Result:

```json
{"status":"ok","store_backend":"sqlite","database_configured":true,"database_host":null,"database_schema_ready":true}
```

macOS package command:

```bash
HARNESS_PACKAGE_VERIFY_PORT=18773 ./script/package_macos_app.sh
```

Result:

- built packaged dashboard assets
- froze the bundled `harness` runtime
- built the Swift app in release mode
- staged `dist/macos-release/Harness.app`
- ad-hoc signed and verified the app bundle
- smoke-tested the bundled runtime
- created `dist/macos-release/Harness.dmg`

The first package attempt exposed a real packaging bug: `codesign` rejected the staged app because `com.apple.FinderInfo` was attached to `Harness.app`. The package script now strips signing-forbidden extended attributes before signing.

## Guardrail Commands

Official-release strict mode still fails correctly on this machine because no Developer ID Application identity is installed:

```bash
HARNESS_REQUIRE_NOTARIZATION=1 ./script/package_macos_app.sh
```

Result:

```text
HARNESS_REQUIRE_NOTARIZATION=1 requires MACOS_CODESIGN_IDENTITY.
```

With a fake identity:

```bash
MACOS_CODESIGN_IDENTITY='Developer ID Application: Example' \
MACOS_NOTARY_PROFILE=harness-notary \
HARNESS_REQUIRE_NOTARIZATION=1 ./script/package_macos_app.sh
```

Result:

```text
codesign identity not found in the active keychain: Developer ID Application: Example
```

## Remaining Blocker

Reader-facing commands are current and verified, except for the separately gated live smoke that creates external artifacts. The only release-blocking item left is external macOS distribution proof: install a real Developer ID Application certificate, configure the notarytool profile, then run:

```bash
export MACOS_CODESIGN_IDENTITY="Developer ID Application: ..."
export MACOS_NOTARY_PROFILE="harness-notary"
HARNESS_REQUIRE_NOTARIZATION=1 ./script/package_macos_app.sh
```
