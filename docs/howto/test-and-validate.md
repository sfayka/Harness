# Test And Validate Proofline

Validation should prove three things: the service starts, the dashboard reads live Proofline APIs through the current Harness compatibility routes, and completion claims are accepted only when evidence is good enough.

Command examples use tested Proofline runtime and storage aliases where they exist. Keep `HARNESS_*` compatibility variables, route aliases, local data paths, and stored evidence fields working until the rename migration guide explicitly retires them.

## Validation Tiers

Use synthetic data for normal development. Synthetic tests are the default because they are deterministic, fast, and safe to run repeatedly while Proofline's contracts are still changing.

Use real Linear and GitHub data only for gated integration validation. Those checks prove that the local contracts still match the real operator systems, but they can create or update external artifacts and should not be part of every edit/test loop.

The current tiers are:

- Tier 0: static checks, unit tests, frontend tests, and deterministic synthetic dry runs.
- Tier 1: local API/dashboard smoke using disposable local storage.
- Tier 2: read-only real-system checks against the configured Linear/GitHub dry-run targets.
- Tier 3: gated live smoke that creates throwaway Linear/GitHub artifacts.
- Tier 4: production workflow validation against a named real project after Sean explicitly approves the target and blast radius.

Do not skip from Tier 0 to Tier 3 just because credentials exist. The point is to keep the edit loop synthetic and make live-system testing deliberate.

## Fast Local Baseline

```bash
python3 -m unittest tests.test_fastapi_backend tests.test_reset_dryrun tests.test_autonomous_dryrun tests.test_unattended_dryruns -v
pnpm lint
pnpm build
```

## Synthetic Validation Runner

For a single non-live validation command, run:

```bash
python3 scripts/proofline_validate.py
```

That command runs the backend suite, deterministic execution-substrate dry runs, reset dry runs, and frontend tests/lint/build. It intentionally does not run live Linear/GitHub mutation smoke.

To inspect the plan without running it:

```bash
python3 scripts/proofline_validate.py --list
```

To include backend coverage in the same ladder after installing `requirements-dev.txt`:

```bash
python3 scripts/proofline_validate.py --coverage
```

## Full Backend Suite

```bash
python3 -m unittest discover -s tests
```

## Backend Coverage

Install developer test dependencies before measuring coverage:

```bash
python3 -m pip install -r requirements-dev.txt
```

Then run:

```bash
python3 -m coverage run -m unittest discover -s tests
python3 -m coverage report -m
```

Coverage should be used as a regression signal, not as permission to weaken acceptance-layer tests. New control-plane, evaluator, contract, reconciliation, ingress, read-model, and dashboard API behavior should add targeted tests even when the aggregate percentage looks healthy.

## Local App Runtime

From a checkout:

```bash
pnpm build:dashboard:local
export PROOFLINE_DASHBOARD_ASSETS_DIR="$PWD/dist/local-dashboard"
python3 -m modules.proofline_runtime --json init
python3 -m modules.proofline_runtime --json start
python3 -m modules.proofline_runtime --json status
python3 -m modules.proofline_runtime --json doctor
python3 -m modules.proofline_runtime --json recover
python3 -m modules.proofline_runtime --json stop
```

The dashboard asset export matters for checkout validation. Without it, the runtime can still be healthy, but `doctor` will warn that the embedded dashboard cannot render packaged UI assets.

A future packaged CLI should expose this same contract as `proofline ...` and may keep `harness ...` as a compatibility alias. The native macOS app package is deprecated and is not part of the normal validation path.

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

These commands exercise the Symphony-compatible execution substrate boundary locally. They write JSON summaries, use disposable stores, and do not start Symphony or touch live Linear/GitHub work. The summaries include `completion_validation_summary`; the legacy `accepted_completion` field is derived from that Proofline verdict, not from runner status. The `handoff` command renders the payload Proofline would hand to a Symphony-compatible runner through the disabled transport boundary while keeping `transport_status=disabled`, `dispatch_enabled=false`, `live_dispatch_enabled=false`, and `safe_to_execute_live=false`.

## Real Linear/GitHub Validation Plan

Proofline's live integration target should remain the dry-run pair unless a release note says otherwise:

- Linear project: `HARNESS-DRYRUN`
- GitHub repository: `sfayka/HARNESS-DRYRUN`
- Base branch: `main`

Read-only checks may be run whenever the tools are authenticated:

```bash
gh auth status
gh repo view sfayka/HARNESS-DRYRUN --json nameWithOwner,defaultBranchRef,url,isPrivate
```

For Linear, use the configured Linear connector or UI to confirm the `HARNESS-DRYRUN` project exists before running mutation smoke. A passing read-only check should identify the project URL, confirm it is not archived, and identify at least one previous live-smoke issue when issue history is available.

Run the repo-owned preflight before any mutation smoke:

```bash
python3 scripts/proofline_live_preflight.py
python3 scripts/proofline_live_preflight.py --json
```

This command is read-only. It checks the live-smoke flag, GitHub/Linear credential presence through env vars or runtime-managed secrets, approved dry-run targets, and the GitHub repository read-only path. It does not create Linear issues, GitHub branches, commits, or PRs.

Only run the mutation smoke when all of these are true:

- `python3 -m unittest discover -s tests` passes.
- `pnpm test:frontend`, `pnpm lint`, and `pnpm build` pass when frontend code changed.
- `python3 scripts/proofline_live_preflight.py` reports `ready`.
- `python3 -m modules.proofline_runtime --json setup status --workflow github-proof --workflow linear-sync` reports GitHub and Linear ready, or equivalent env vars are intentionally exported for that shell. The live smoke loads runtime-managed secrets before creating clients, so the CLI secret path is valid for this test.
- The target Linear project is `HARNESS-DRYRUN`.
- The target GitHub repository is `sfayka/HARNESS-DRYRUN`.
- The run is expected to create throwaway Linear issues, branches, commits, and PRs.
- No live Symphony dispatch is enabled unless the specific test is explicitly about execution-substrate transport.

### Gated Live Smoke

Only run this when the repo has live `GITHUB_TOKEN` and `LINEAR_API_KEY` access configured:

```bash
HARNESS_RUN_LIVE_RESET_TESTS=1 python3 -m unittest tests.test_reset_live_smoke -v
```

This creates real throwaway Linear and GitHub artifacts in the configured dry-run targets.

Record every successful mutation smoke under `docs/release/` with:

- exact command and environment switches
- Linear project and issue URLs
- GitHub repository, branch, commit, and PR URLs
- final Proofline verdicts
- any cleanup that was performed or intentionally left visible as proof

If Sean delegates this validation to a Hermes agent that already has Linear and GitHub access, use the copyable handoff in [Hermes Live Validation Handoff](hermes-live-validation.md). Hermes is only an external tester in that flow. Its report must still be reconciled against Proofline preflight output, command results, live artifact URLs, and final Proofline verdicts.

## What Counts As Proof

- healthy `/health` response
- live dashboard reading canonical APIs
- deterministic dry-run verdicts
- live Linear issue identifiers for live smoke
- live GitHub branch, commit, and PR artifacts for live smoke
- canonical read-model, timeline, or reset contract state that matches external artifacts

For completion claims, inspect `completion_validation_summary` on successful persisted evaluation responses, `GET /tasks`, or `GET /tasks/<task_id>/read-model`. A task is not operator-accepted just because an executor said it finished. The validation summary should show `completion_claimed=true`, `completion_accepted=true`, `intent_status=matched`, and `evidence_status=sufficient` before the dashboard or CLI presents the work as actually done. If the summary reports `blocked`, `review_required`, `pending`, `insufficient`, or `invalid`, the task still needs evidence, reconciliation, repair, or explicit review.
