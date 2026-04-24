# macOS Notarization Readiness

Date: 2026-04-24

## Purpose

Check whether this machine can complete the remaining official-release gate: a Developer ID signed and notarized `Harness.dmg`.

## Current Result

This machine is not ready to produce the official distribution artifact.

```bash
security find-identity -v -p codesigning
```

Result:

```text
0 valid identities found
```

Without a valid `Developer ID Application` identity in the active keychain, `codesign` cannot produce the signature Apple expects for notarization.

## Release Guardrail Added

The packaging script now supports strict official-release mode:

```bash
export MACOS_CODESIGN_IDENTITY="Developer ID Application: ..."
export MACOS_NOTARY_PROFILE="harness-notary"
HARNESS_REQUIRE_NOTARIZATION=1 ./script/package_macos_app.sh
```

With `HARNESS_REQUIRE_NOTARIZATION=1`, the script fails before build work starts if either release prerequisite is missing:

- `MACOS_CODESIGN_IDENTITY`
- `MACOS_NOTARY_PROFILE`

If `MACOS_CODESIGN_IDENTITY` is set but not visible in `security find-identity -v -p codesigning`, the script fails with an operator-readable message.

## Needed To Complete The Gate

1. Install the Apple Developer ID Application certificate into the active keychain.
2. Configure a notarytool keychain profile, for example `harness-notary`.
3. Run the strict package command above.
4. Confirm the script submits the DMG, waits for notarization, staples the app and DMG, and leaves `dist/macos-release/Harness.dmg` ready for external distribution.

## Boundary

The existing ad-hoc package remains valid for internal validation. It is not an official release artifact and must not be treated as equivalent to a Developer ID signed and notarized DMG.
