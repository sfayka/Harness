# Test And Validate Harness

Validation should prove three things: the service starts, the dashboard reads live Harness APIs, and completion claims are accepted only when evidence is good enough.

## Fast Local Baseline

```bash
python3 -m unittest tests.test_fastapi_backend tests.test_reset_dryrun tests.test_autonomous_dryrun tests.test_unattended_dryruns -v
pnpm lint
pnpm build
```

## Full Backend Suite

```bash
python3 -m unittest discover -s tests
```

## Local App Runtime

From a checkout:

```bash
pnpm build:dashboard:local
export HARNESS_DASHBOARD_ASSETS_DIR="$PWD/dist/local-dashboard"
python3 -m modules.local_runtime --json init
python3 -m modules.local_runtime --json start
python3 -m modules.local_runtime --json status
python3 -m modules.local_runtime --json doctor
python3 -m modules.local_runtime --json recover
python3 -m modules.local_runtime --json stop
```

The dashboard asset export matters for checkout validation. Without it, the runtime can still be healthy, but `doctor` will warn that the embedded dashboard cannot render packaged UI assets.

A packaged build should expose the same contract as `harness ...`.

## Packaged macOS App

```bash
./script/package_macos_app.sh
```

The script builds dashboard assets, freezes the Python runtime, signs the bundle, smoke-tests the bundled runtime, and writes `dist/macos-release/Harness.dmg`.
The package smoke test defaults to port `18765` so it can run even when the normal local app already owns `127.0.0.1:8765`; override it with `HARNESS_PACKAGE_VERIFY_PORT` if needed.

## Deterministic Reset Proofs

```bash
python3 -m modules.reset_dryrun success
python3 -m modules.reset_dryrun review
```

The success path should verify a claimed completion. The review path should exhaust the retry path and land in explicit review instead of pretending the task completed.

## Local Live Smoke

Only run this when the repo has live `GITHUB_TOKEN` and `LINEAR_API_KEY` access configured:

```bash
HARNESS_RUN_LIVE_RESET_TESTS=1 python3 -m unittest tests.test_reset_live_smoke -v
```

This creates real throwaway Linear and GitHub artifacts in the configured dry-run targets.

## What Counts As Proof

- healthy `/health` response
- live dashboard reading canonical APIs
- deterministic dry-run verdicts
- live Linear issue identifiers for live smoke
- live GitHub branch, commit, and PR artifacts for live smoke
- canonical read-model, timeline, or reset contract state that matches external artifacts
