# Documentation Readiness Checklist

Use this checklist before calling Harness local-app documentation release-ready.

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

## Still Required Before Official Release

- [ ] Run the gated live reset smoke with real GitHub and Linear dry-run targets.
- [ ] Verify a Developer ID signed and notarized DMG, not only the ad-hoc internal package.
- [ ] Perform one fresh first-run walkthrough from a clean macOS user state.
- [ ] Capture any final onboarding screenshots after the first-run app UI is complete.
- [ ] Re-run every reader-facing command after the final app UI and installer flow land.
