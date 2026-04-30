# macOS Dashboard Window

The macOS dashboard window provides the full Harness inspection surface inside the native app.
It is opened from the menu bar and embeds the same local dashboard served by the app-managed Harness runtime.

## Boundary

The dashboard window does not read SQLite and does not rebuild dashboard truth in Swift.
It loads the canonical local dashboard over HTTP from the local runtime.

The app shell uses:

- `python3 -m modules.local_runtime --json status`
- `python3 -m modules.local_runtime --json open --print-url`
- the local dashboard routes under `/dashboard/`

The embedded web view is a narrow `NSViewRepresentable` wrapper around `WKWebView`.
SwiftUI owns window state, selected route, fallback controls, and runtime preparation.
WebKit owns only page rendering and navigation.

## Routes

The window exposes the current dashboard routes as first-class toolbar choices:

- `Tasks`: `/dashboard/tasks/`
- `Verification`: `/dashboard/verification/`
- `Reconciliation`: `/dashboard/reconciliation/`
- `Reviews`: `/dashboard/reviews/`
- `Execution`: `/dashboard/execution/`

These are the same routes used by the packaged local dashboard.
The app must not introduce a separate route model that contradicts the dashboard.

## Runtime Behavior

Opening the dashboard starts the local runtime when it is not already running.
If runtime setup or startup fails, the window shows an actionable unavailable state instead of a blank web view.

Closing the dashboard window does not stop Harness.
Runtime lifecycle remains controlled by explicit Start, Stop, and Restart actions in the menu bar.

## Debugging Fallback

The dashboard toolbar includes:

- `Refresh`
- `Copy URL`
- `Open in Browser`

Those controls are for debugging route, asset, or backend availability issues.
They do not replace the embedded dashboard as the normal app path.
