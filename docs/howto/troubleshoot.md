# Troubleshoot Harness

Troubleshooting should start with observable state: health response, runtime status, logs, configured paths, and the canonical task/read-model endpoints.

## Backend Starts But `/reset/*` Fails

Check:

- `HARNESS_STORE_BACKEND`
- `DATABASE_URL` or `POSTGRES_URL` for hosted mode
- reset service startup logs
- whether the reset temp store fallback is writable in local/dev mode

Hosted `/reset/*` should fail explicitly if reset storage cannot initialize. It should not take down `/backend/health` or the canonical task API during import.

## Dashboard Loads But Shows No Real Data

Check:

- `HARNESS_API_BASE_URL`
- backend reachability
- whether the hosted dashboard is using the same-project `/backend` route
- browser network errors against `/api/harness` or same-origin local API routes

The dashboard should report backend errors honestly. It should not silently switch to fake live data.

## Local App Runtime Will Not Start

Run:

```bash
python3 -m modules.local_runtime --json doctor
python3 -m modules.local_runtime --json status
python3 -m modules.local_runtime --json recover
```

Check:

- `~/Library/Application Support/Harness/config.json`
- `~/Library/Application Support/Harness/runtime/harness.pid`
- `~/Library/Logs/Harness/harness.log`
- whether another process owns `127.0.0.1:8765`

If the PID file is stale, `recover` should clear it. If another process owns the port, Harness should report `port_conflict` with a concrete next action.

## Reset Verifier Cannot Dispatch Repair

Check:

- `OPENCLAW_BASE_URL`
- `OPENCLAW_REPAIR_ENDPOINT`
- `OPENCLAW_REPAIR_BEARER_TOKEN`
- `OPENCLAW_CONFIG_PATH`
- `OPENCLAW_STATE_DIR`

For hosted runtime, the repair receiver must be remote-reachable. Local loopback receiver URLs are only valid when Harness and the receiver are on the same machine.

## Completion Claim Is Not Accepted

Check:

- repository identity
- branch identity
- commit SHA
- PR URL or PR number
- changed-file proof
- whether the proof belongs to the current run
- whether a manual review gate is active

Harness treats worker-reported success as advisory. If evidence is missing, stale, contradictory, or tied to the wrong run, the correct behavior is to block, retry, reconcile, or require review.

## Packaged App Opens But macOS Blocks It

Internal validation packages may be ad-hoc signed. External distribution requires:

```bash
export MACOS_CODESIGN_IDENTITY="Developer ID Application: ..."
export MACOS_NOTARY_PROFILE="harness-notary"
HARNESS_REQUIRE_NOTARIZATION=1 ./script/package_macos_app.sh
```

Then verify signing and notarization before publishing the DMG.

If the command fails before building with `codesign identity not found`, inspect the available identities:

```bash
security find-identity -v -p codesigning
```

Official distribution needs a valid `Developer ID Application` certificate installed in the active keychain. An ad-hoc package is acceptable for internal validation, but it is not an official release artifact.
