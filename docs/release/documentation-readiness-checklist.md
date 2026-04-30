# Documentation Readiness Checklist

This checklist captured the older local-app documentation release pass. The native macOS app is now deprecated; use this file as historical evidence, not as the active release checklist.

Current documentation readiness should prove the CLI/runtime contract, backend API, web dashboard, deterministic dry runs, and hosted/local verification paths. Developer ID signing, notarization, DMG production, Launch at Login, and native first-run onboarding are no longer release blockers.

## Verified In This Pass

- [x] Route names in the how-to docs match the current backend.
- [x] Environment variable names in the how-to docs match the current code paths.
- [x] Screenshots were captured from the current local product state.
- [x] Every screenshot is referenced from at least one how-to doc.
- [x] Local quickstart reaches a healthy backend.
- [x] The packaged macOS app build produces `Harness.app` and `Harness.dmg`.
- [x] The packaged runtime smoke test passes inside `script/package_macos_app.sh`.
- [x] Test guide covers deterministic dry runs and the gated live smoke.
- [x] Setup docs explain current `OPENCLAW_*` variables without making Harness architecturally dependent on OpenClaw.
- [x] README points readers to the how-to docs before deeper architecture references.
- [x] Fresh macOS first-run walkthrough reaches local SQLite-backed dashboard readiness. See [macos-first-run-walkthrough-2026-04-23.md](macos-first-run-walkthrough-2026-04-23.md).
- [x] Final onboarding screenshots are captured and referenced from the local quickstart.

## Historical macOS Release Items

- [x] Run the gated live reset smoke with real GitHub and Linear dry-run targets. See [live-reset-smoke-2026-04-23.md](live-reset-smoke-2026-04-23.md).
- [ ] Verify a Developer ID signed and notarized DMG, not only the ad-hoc internal package. Deprecated with the native macOS app pivot; no longer required for the supported Harness path.
  Current local blocker: `security find-identity -v -p codesigning` reports `0 valid identities found`, so this machine cannot produce a Developer ID signed DMG yet. See [macos-notarization-readiness-2026-04-24.md](macos-notarization-readiness-2026-04-24.md).
- [x] Re-run every reader-facing command after the final app UI and installer flow land. See [reader-command-verification-2026-04-27.md](reader-command-verification-2026-04-27.md).
