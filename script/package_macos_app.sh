#!/usr/bin/env bash
set -euo pipefail

APP_NAME="HarnessApp"
BUNDLE_ID="com.knoxanalytics.harness.local"
MIN_SYSTEM_VERSION="14.0"
DEFAULT_VERSION="0.1.0"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$ROOT_DIR/apps/macos/HarnessApp"
BUILD_DIR="$ROOT_DIR/.build/macos-package"
DIST_DIR="$ROOT_DIR/dist/macos-release"
APP_BUNDLE="$DIST_DIR/Harness.app"
APP_CONTENTS="$APP_BUNDLE/Contents"
APP_MACOS="$APP_CONTENTS/MacOS"
APP_RESOURCES="$APP_CONTENTS/Resources"
APP_BINARY="$APP_MACOS/$APP_NAME"
INFO_PLIST="$APP_CONTENTS/Info.plist"
RUNTIME_BUILD_DIR="$BUILD_DIR/runtime"
RUNTIME_DIST_DIR="$RUNTIME_BUILD_DIR/dist"
RUNTIME_WORK_DIR="$RUNTIME_BUILD_DIR/work"
RUNTIME_SPEC_DIR="$RUNTIME_BUILD_DIR/spec"
RUNTIME_STAGING_DIR="$APP_RESOURCES/HarnessRuntime"
RUNTIME_BINARY="$RUNTIME_STAGING_DIR/harness"
DASHBOARD_OUTPUT_DIR="$ROOT_DIR/dist/local-dashboard"
DASHBOARD_STAGING_DIR="$APP_RESOURCES/Dashboard"
DMG_PATH="$DIST_DIR/Harness.dmg"
VERIFY_DATA_DIR="$BUILD_DIR/verify-data"
VERIFY_LOG_DIR="$BUILD_DIR/verify-logs"
VERIFY_PORT="${HARNESS_PACKAGE_VERIFY_PORT:-18765}"
PACKAGING_VENV="$BUILD_DIR/venv"

APP_VERSION="${HARNESS_RELEASE_VERSION:-$DEFAULT_VERSION}"
BUILD_VERSION="${HARNESS_BUILD_VERSION:-$(git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)}"
CODESIGN_IDENTITY="${MACOS_CODESIGN_IDENTITY:-}"
NOTARY_PROFILE="${MACOS_NOTARY_PROFILE:-}"
REQUIRE_NOTARIZATION="${HARNESS_REQUIRE_NOTARIZATION:-0}"

require_tool() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "missing required tool: $1" >&2
    exit 2
  }
}

truthy() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

codesign_identity_available() {
  local identity="$1"
  security find-identity -v -p codesigning | grep -F "$identity" >/dev/null 2>&1
}

validate_distribution_prerequisites() {
  if [[ -n "$NOTARY_PROFILE" && -z "$CODESIGN_IDENTITY" ]]; then
    echo "MACOS_NOTARY_PROFILE requires MACOS_CODESIGN_IDENTITY; notarization must use a Developer ID signed app." >&2
    exit 2
  fi

  if truthy "$REQUIRE_NOTARIZATION"; then
    if [[ -z "$CODESIGN_IDENTITY" ]]; then
      echo "HARNESS_REQUIRE_NOTARIZATION=1 requires MACOS_CODESIGN_IDENTITY." >&2
      exit 2
    fi
    if [[ -z "$NOTARY_PROFILE" ]]; then
      echo "HARNESS_REQUIRE_NOTARIZATION=1 requires MACOS_NOTARY_PROFILE." >&2
      exit 2
    fi
  fi

  if [[ -n "$CODESIGN_IDENTITY" ]] && ! codesign_identity_available "$CODESIGN_IDENTITY"; then
    echo "codesign identity not found in the active keychain: $CODESIGN_IDENTITY" >&2
    echo "Install the Developer ID Application certificate or choose an identity from: security find-identity -v -p codesigning" >&2
    exit 2
  fi
}

require_tool python3
require_tool pnpm
require_tool swift
require_tool hdiutil
require_tool codesign
require_tool xattr
require_tool security
require_tool xcrun

validate_distribution_prerequisites

rm -rf "$BUILD_DIR" "$DIST_DIR"
mkdir -p "$BUILD_DIR" "$DIST_DIR" "$APP_MACOS" "$APP_RESOURCES"

echo "Building packaged dashboard assets..."
(cd "$ROOT_DIR" && pnpm build:dashboard:local)

echo "Preparing packaging virtualenv..."
python3 -m venv "$PACKAGING_VENV"
"$PACKAGING_VENV/bin/python" -m pip install --upgrade pip
"$PACKAGING_VENV/bin/pip" install -r "$ROOT_DIR/requirements-packaging.txt"

echo "Building bundled Harness runtime..."
"$PACKAGING_VENV/bin/pyinstaller" \
  --noconfirm \
  --clean \
  --onedir \
  --name harness \
  --distpath "$RUNTIME_DIST_DIR" \
  --workpath "$RUNTIME_WORK_DIR" \
  --specpath "$RUNTIME_SPEC_DIR" \
  --add-data "$ROOT_DIR/schemas:schemas" \
  --hidden-import backend.server \
  "$ROOT_DIR/modules/local_runtime.py"

if [[ ! -x "$RUNTIME_DIST_DIR/harness/harness" ]]; then
  echo "bundled Harness runtime was not created" >&2
  exit 1
fi

echo "Building macOS app binary..."
(cd "$APP_DIR" && swift build -c release)
SWIFT_BIN="$(cd "$APP_DIR" && swift build -c release --show-bin-path)/$APP_NAME"
if [[ ! -x "$SWIFT_BIN" ]]; then
  echo "Swift app binary not found at $SWIFT_BIN" >&2
  exit 1
fi

echo "Staging app bundle..."
mkdir -p "$RUNTIME_STAGING_DIR" "$DASHBOARD_STAGING_DIR"
cp "$SWIFT_BIN" "$APP_BINARY"
chmod +x "$APP_BINARY"
cp -R "$RUNTIME_DIST_DIR/harness/." "$RUNTIME_STAGING_DIR/"
cp -R "$DASHBOARD_OUTPUT_DIR/." "$DASHBOARD_STAGING_DIR/"

cat >"$INFO_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>en</string>
  <key>CFBundleExecutable</key>
  <string>$APP_NAME</string>
  <key>CFBundleIdentifier</key>
  <string>$BUNDLE_ID</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>Harness</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>$APP_VERSION</string>
  <key>CFBundleVersion</key>
  <string>$BUILD_VERSION</string>
  <key>LSMinimumSystemVersion</key>
  <string>$MIN_SYSTEM_VERSION</string>
  <key>NSPrincipalClass</key>
  <string>NSApplication</string>
  <key>NSAppTransportSecurity</key>
  <dict>
    <key>NSAllowsLocalNetworking</key>
    <true/>
  </dict>
  <key>HarnessRuntimeExecutable</key>
  <string>Contents/Resources/HarnessRuntime/harness</string>
  <key>HarnessDashboardAssetsDir</key>
  <string>Contents/Resources/Dashboard</string>
</dict>
</plist>
PLIST

echo "Signing app bundle..."
xattr -cr "$APP_BUNDLE"
if [[ -n "$CODESIGN_IDENTITY" ]]; then
  codesign --force --deep --options runtime --sign "$CODESIGN_IDENTITY" "$APP_BUNDLE"
else
  codesign --force --deep --sign - "$APP_BUNDLE"
fi
codesign --verify --deep --strict --verbose=2 "$APP_BUNDLE"

echo "Verifying bundled runtime..."
mkdir -p "$VERIFY_DATA_DIR" "$VERIFY_LOG_DIR"
export HARNESS_DASHBOARD_ASSETS_DIR="$DASHBOARD_STAGING_DIR"
"$RUNTIME_BINARY" --data-dir "$VERIFY_DATA_DIR" --log-dir "$VERIFY_LOG_DIR" --json init --port "$VERIFY_PORT" >/dev/null
"$RUNTIME_BINARY" --data-dir "$VERIFY_DATA_DIR" --log-dir "$VERIFY_LOG_DIR" --json doctor >/dev/null
"$RUNTIME_BINARY" --data-dir "$VERIFY_DATA_DIR" --log-dir "$VERIFY_LOG_DIR" --json start --port "$VERIFY_PORT" --timeout 10 >/dev/null
"$RUNTIME_BINARY" --data-dir "$VERIFY_DATA_DIR" --log-dir "$VERIFY_LOG_DIR" --json status >/dev/null
"$RUNTIME_BINARY" --data-dir "$VERIFY_DATA_DIR" --log-dir "$VERIFY_LOG_DIR" --json stop --timeout 5 >/dev/null

echo "Creating DMG..."
hdiutil create -volname "Harness" -srcfolder "$APP_BUNDLE" -ov -format UDZO "$DMG_PATH" >/dev/null

if [[ -n "$NOTARY_PROFILE" ]]; then
  echo "Submitting DMG for notarization..."
  xcrun notarytool submit "$DMG_PATH" --keychain-profile "$NOTARY_PROFILE" --wait
  xcrun stapler staple "$APP_BUNDLE"
  xcrun stapler staple "$DMG_PATH"
fi

echo "Packaged app: $APP_BUNDLE"
echo "Packaged disk image: $DMG_PATH"
