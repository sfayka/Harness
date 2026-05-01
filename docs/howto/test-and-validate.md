# Test And Validate Proofline

Validation should prove three things: the service starts, the dashboard reads live Proofline APIs through the current Harness compatibility routes, and completion claims are accepted only when evidence is good enough.

Command examples intentionally keep the Harness compatibility namespace until tested Proofline aliases exist. Do not rename `HARNESS_*` variables, runtime module paths, or stored evidence fields locally.

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

A future packaged CLI should expose the same contract as a compatibility `harness ...` command and, later, a tested Proofline alias. The native macOS app package is deprecated and is not part of the normal validation path.

## Deterministic Reset Proofs

```bash
python3 -m modules.reset_dryrun success
python3 -m modules.reset_dryrun review
```

The success path should verify a claimed completion. The review path should exhaust the retry path and land in explicit review instead of pretending the task completed.

## Execution Substrate Dry Runs

```bash
python3 -m modules.execution_substrate_dryrun event-stream
python3 -m modules.execution_substrate_dryrun intent-consumer
python3 -m modules.execution_substrate_dryrun handoff
```

These commands exercise the Symphony-compatible execution substrate boundary locally. They write JSON summaries, use disposable stores, and do not start Symphony or touch live Linear/GitHub work. The `handoff` command renders the payload Proofline would hand to a Symphony-compatible runner through the disabled transport boundary while keeping `transport_status=disabled`, `dispatch_enabled=false`, `live_dispatch_enabled=false`, and `safe_to_execute_live=false`.

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
