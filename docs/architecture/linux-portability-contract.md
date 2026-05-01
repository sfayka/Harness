# Linux Portability Contract

This document is now historical guardrail context. Harness is no longer pursuing a native macOS shell first; the supported surface is CLI + API + web dashboard.

Harness is not allowed to make the backend, SQLite store, dashboard, or CLI contract depend on Swift, AppKit, Keychain-only semantics, or `.app`-bundle assumptions.

## Platform-Neutral Surfaces

These pieces must remain reusable for a future Linux package:

- Python runtime and backend entrypoints in `modules/local_runtime.py` and `backend.server`
- SQLite schema, migrations, and store semantics
- local CLI/process contract exposed as `harness ...`
- runtime-managed config model and XDG-compatible data/log paths
- static dashboard bundle and same-origin API behavior
- doctor/setup data model and integration semantics

If one of these changes in a platform packaging branch, the change needs to be justified as a portable runtime change, not a shell convenience.

## Replaceable Boundaries

These are allowed to be platform-specific, but only behind explicit boundaries:

| Concern | macOS v1 | Linux later |
| --- | --- | --- |
| Secret provider | Keychain / `security` | Secret Service / libsecret, or encrypted local fallback |
| Auto-start | `SMAppService` Launch at Login | `systemd --user` service or desktop autostart |
| Notifications | `UserNotifications` | freedesktop notifications |
| Package format | `.app` + `.dmg` | AppImage, deb, rpm, or tarball |
| Folder selection | AppKit / Finder picker | XDG portal or toolkit-native picker |

The backend and CLI should consume the same abstract outputs from these boundaries regardless of platform:

- secret names and env mapping
- runtime lifecycle commands
- onboarding/setup item status
- dashboard URL and API base URL

## Current Guardrails

As of the macOS packaging slice:

- the runtime contract is Python, not Swift
- runtime-managed paths already support macOS and Linux defaults
- the bundled dashboard is static and backend-served, not tied to a macOS web runtime
- contract schema loading works from a repo checkout or bundled runtime
- secret-provider selection is platform-aware in Python instead of hard-coding `macos-keychain`

That means a future Linux shell can reuse the same backend, SQLite store, dashboard assets, and CLI contract even though the native shell implementation is deferred.

## What Must Not Happen

- Do not move task truth, SQLite writes, or policy enforcement into Swift-only code.
- Do not make the CLI depend on `.app` bundle layout.
- Do not rename Harness secret names just because the underlying OS provider changes.
- Do not make doctor/setup payloads require macOS-only concepts to be considered valid.
- Do not let packaging scripts become the runtime contract.

## Deferred Linux Decisions

These remain explicitly deferred:

- which Linux package format ships first
- which desktop toolkit hosts the Linux dashboard window
- whether the first Linux auto-start path is `systemd --user`, desktop autostart, or both
- whether the first Linux secret provider is libsecret-only or includes an encrypted local fallback

Those are implementation decisions for a later issue. This contract only locks the boundaries they are allowed to replace.
