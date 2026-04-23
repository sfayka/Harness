# macOS Packaging

Issue #328 is the line between a developer bundle and a distributable local Harness app.
The goal is not "make Swift build." The goal is "ship a normal macOS app that does not depend on a repo checkout, Python install, Node install, or Docker."

This document is macOS-specific on purpose. The cross-platform guardrails that keep this package work from polluting Harness core live in [linux-portability-contract.md](linux-portability-contract.md).

## Package Shape

The packaged bundle should contain:

- the native `HarnessApp` macOS binary
- a bundled `harness` runtime executable built from `modules/local_runtime.py`
- all Python runtime dependencies needed by the local runtime contract
- bundled contract resources such as `schemas/task_envelope.schema.json`
- prebuilt static dashboard assets

The packaged app must not depend on `HarnessRepoRoot`.
That key is only for the developer bundle path staged by `script/build_and_run.sh`.

## Runtime Resources

The app bundle resource layout is:

```text
Harness.app/
  Contents/
    MacOS/HarnessApp
    Resources/
      HarnessRuntime/
        harness
        _internal/...
      Dashboard/
        index.html
        dashboard-manifest.json
        ...
```

`HarnessRuntimeCommand` should prefer this bundle-owned runtime executable and bundle-owned dashboard asset directory when they exist.
Repo-root developer mode remains the fallback.

## Build Flow

The release build entrypoint is:

```bash
./script/package_macos_app.sh
```

The script:

1. builds `dist/local-dashboard` with `pnpm build:dashboard:local`
2. creates a packaging virtualenv
3. installs `requirements-packaging.txt`
4. freezes `modules/local_runtime.py` into a bundled `harness` executable with PyInstaller
5. builds the Swift app in release mode
6. stages `Harness.app`
7. signs the bundle ad hoc by default, or with `MACOS_CODESIGN_IDENTITY` when provided
8. smoke-tests the bundled runtime with `init`, `doctor`, `start`, `status`, and `stop`
9. creates `dist/macos-release/Harness.dmg`

This is intentionally a build-machine workflow, not an end-user workflow.
The build machine may need Python, `pnpm`, and Xcode tools.
The installed app must not.

The packaging smoke test uses `HARNESS_PACKAGE_VERIFY_PORT`, defaulting to `18765`, so it can run while a developer's normal local Harness app already owns `127.0.0.1:8765`.

## Signing And Notarization

For internal validation, ad-hoc signing is acceptable.
For external distribution, use:

- `MACOS_CODESIGN_IDENTITY` for Developer ID Application signing
- `MACOS_NOTARY_PROFILE` for `xcrun notarytool` submission

When a notary profile is present, the package script submits the generated DMG, waits for completion, and staples the result.

## Installer Flow

The v1 distribution artifact is a DMG containing `Harness.app`.
A `.pkg` installer is unnecessary in this slice because Harness does not install a privileged helper, LaunchDaemon, or system-wide service.

Users drag `Harness.app` into Applications and launch it.
The app then creates its own runtime state under:

- `~/Library/Application Support/Harness/`
- `~/Library/Logs/Harness/`

## Reset And Uninstall

Removing the app bundle is not the same as removing local state.

To fully remove local Harness state:

1. Quit Harness.
2. Disable Launch at Login from Settings if it was enabled.
3. Remove `~/Library/Application Support/Harness/`.
4. Remove `~/Library/Logs/Harness/`.
5. Delete Keychain entries stored under `com.knoxanalytics.harness.local-runtime` when a full credential reset is required.

This should be documented in user-facing install docs before external release.

## Validation

At minimum, packaging changes should validate:

```bash
swift build
swift run HarnessAppCoreCheck
python3 -m unittest tests.test_local_runtime tests.test_local_setup -v
pnpm build
pnpm build:dashboard:local
./script/package_macos_app.sh
```

If signing or notarization wiring changes, also verify the produced app with the relevant macOS distribution tools before claiming external-release readiness.
