# Troubleshoot Proofline

Troubleshooting should start with observable state: health response, runtime status, logs, configured paths, and the canonical task/read-model endpoints.

During the staged rename, some runtime identifiers still say Harness. Treat `HARNESS_*` variables, `/api/harness` compatibility routes, local data paths, and stored evidence fields as compatibility surfaces, not stale instructions. New dashboard traffic should use `/api/proofline`, and checkout runtime commands should use `modules.proofline_runtime`.

## Backend Starts But `/reset/*` Fails

Check:

- `PROOFLINE_STORE_BACKEND`
- `HARNESS_STORE_BACKEND`
- `DATABASE_URL` or `POSTGRES_URL` for hosted mode
- reset service startup logs
- whether the reset temp store fallback is writable in local/dev mode

Hosted `/reset/*` should fail explicitly if reset storage cannot initialize. It should not take down `/backend/health` or the canonical task API during import.

## Dashboard Loads But Shows No Real Data

Check:

- `PROOFLINE_API_BASE_URL`
- `HARNESS_API_BASE_URL`
- backend reachability
- whether the hosted dashboard is using the same-project `/backend` route
- browser network errors against `/api/proofline`, `/api/harness`, or same-origin local API routes

The dashboard should report backend errors honestly. It should not silently switch to fake live data.

## Local Runtime Will Not Start

Run:

```bash
python3 -m modules.proofline_runtime --json doctor
python3 -m modules.proofline_runtime --json status
python3 -m modules.proofline_runtime --json recover
```

Check:

- `~/Library/Application Support/Harness/config.json`
- `~/Library/Application Support/Harness/runtime/harness.pid`
- `~/Library/Logs/Harness/harness.log`
- whether another process owns `127.0.0.1:8765`

If the PID file is stale, `recover` should clear it. If another process owns the port, Proofline should report `port_conflict` with a concrete next action.

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

Proofline treats worker-reported success as advisory. If evidence is missing, stale, contradictory, or tied to the wrong run, the correct behavior is to block, retry, reconcile, or require review.

## Native macOS App Issues

The native macOS app is deprecated and is not the supported operator path. Prefer `python3 -m modules.proofline_runtime ...` plus the web dashboard for local operation. Do not spend debugging time on signing, notarization, Launch at Login, or notification problems unless a task explicitly reopens the native app decision.
