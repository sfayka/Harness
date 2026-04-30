#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-run}"
APP_NAME="HarnessApp"
BUNDLE_ID="${HARNESS_DEV_BUNDLE_ID:-com.knoxanalytics.harness.local}"
MIN_SYSTEM_VERSION="14.0"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$ROOT_DIR/apps/macos/HarnessApp"
DIST_DIR="$ROOT_DIR/dist/macos"
DEFAULT_DASHBOARD_ASSETS_DIR="$ROOT_DIR/dist/local-dashboard"
APP_BUNDLE="$DIST_DIR/$APP_NAME.app"
APP_CONTENTS="$APP_BUNDLE/Contents"
APP_MACOS="$APP_CONTENTS/MacOS"
APP_BINARY="$APP_MACOS/$APP_NAME"
INFO_PLIST="$APP_CONTENTS/Info.plist"

if [[ "${HARNESS_ENABLE_DEPRECATED_MACOS_APP:-}" != "1" ]]; then
  cat >&2 <<'EOF'
The native macOS app is deprecated and is no longer a supported Harness surface.
Use the CLI/runtime contract and web dashboard instead.

To run this legacy script intentionally, set:
  HARNESS_ENABLE_DEPRECATED_MACOS_APP=1
EOF
  exit 2
fi

pkill -x "$APP_NAME" >/dev/null 2>&1 || true

cd "$APP_DIR"
swift build
BUILD_BINARY="$(swift build --show-bin-path)/$APP_NAME"

rm -rf "$APP_BUNDLE"
mkdir -p "$APP_MACOS"
cp "$BUILD_BINARY" "$APP_BINARY"
chmod +x "$APP_BINARY"

cat >"$INFO_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key>
  <string>$APP_NAME</string>
  <key>CFBundleIdentifier</key>
  <string>$BUNDLE_ID</string>
  <key>CFBundleName</key>
  <string>Harness</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>LSMinimumSystemVersion</key>
  <string>$MIN_SYSTEM_VERSION</string>
  <key>NSPrincipalClass</key>
  <string>NSApplication</string>
  <key>NSAppTransportSecurity</key>
  <dict>
    <key>NSAllowsLocalNetworking</key>
    <true/>
  </dict>
  <key>HarnessRepoRoot</key>
  <string>$ROOT_DIR</string>
</dict>
</plist>
PLIST

open_app() {
  local open_args=("-n")
  local dashboard_assets_dir="${HARNESS_DASHBOARD_ASSETS_DIR:-}"
  if [[ -z "$dashboard_assets_dir" && -f "$DEFAULT_DASHBOARD_ASSETS_DIR/index.html" ]]; then
    dashboard_assets_dir="$DEFAULT_DASHBOARD_ASSETS_DIR"
  fi

  open_args+=("--env" "HARNESS_REPO_ROOT=${HARNESS_REPO_ROOT:-$ROOT_DIR}")
  if [[ -n "$dashboard_assets_dir" ]]; then
    open_args+=("--env" "HARNESS_DASHBOARD_ASSETS_DIR=$dashboard_assets_dir")
  fi
  for key in \
    HARNESS_APP_DATA_DIR \
    HARNESS_APP_LOG_DIR \
    HARNESS_RUNTIME_HOST \
    HARNESS_RUNTIME_PORT \
    HARNESS_RUNTIME_EXECUTABLE
  do
    if [[ -n "${!key:-}" ]]; then
      open_args+=("--env" "$key=${!key}")
    fi
  done
  /usr/bin/open "${open_args[@]}" "$APP_BUNDLE"
}

case "$MODE" in
  run)
    open_app
    ;;
  --debug|debug)
    HARNESS_REPO_ROOT="$ROOT_DIR" lldb -- "$APP_BINARY"
    ;;
  --logs|logs)
    open_app
    /usr/bin/log stream --info --style compact --predicate "process == \"$APP_NAME\""
    ;;
  --telemetry|telemetry)
    open_app
    /usr/bin/log stream --info --style compact --predicate "subsystem == \"$BUNDLE_ID\""
    ;;
  --verify|verify)
    open_app
    sleep 1
    pgrep -x "$APP_NAME" >/dev/null
    ;;
  *)
    echo "usage: $0 [run|--debug|--logs|--telemetry|--verify]" >&2
    exit 2
    ;;
esac
