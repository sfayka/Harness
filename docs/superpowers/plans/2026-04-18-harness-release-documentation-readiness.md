# Harness Release Documentation Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring Harness documentation to release-readiness by making it current, accurate, readable, screenshot-backed, and complete across setup, configuration, testing, operation, and validation.

**Architecture:** Treat the docs as a product surface, not as a loose collection of notes. First run a reality audit against the current code and local runtime, then rebuild the reader-facing flow around a small how-to set, then capture deterministic screenshots from real local runs, and finally run a strict release QA pass so no command, route, screenshot, or file path drifts from the code. Preserve the current OpenClaw-shaped implementation details where the code still uses them, but explain them as replaceable client adapters rather than product truth.

**Tech Stack:** Markdown docs, Python `unittest`, FastAPI, local `uvicorn`, Next.js dashboard, deterministic demo walkthroughs, reset dry runs, live reset smoke, canonical Harness `/tasks`, `/reset/*`, `/sync/github`, and `/supervision/queue` routes, screenshot assets checked into the repo

---

## File Map

- `README.md`
  Reframe the top-level product story, docs map, screenshot references, and release-facing quick links.

- `docs/setup/local-development.md`
  Keep as the operator runbook for local setup, local testing, and local reset flows.

- `docs/setup/vercel-neon.md`
  Keep as the hosted deployment and hosted verification runbook.

- `docs/setup/openclaw-local.md`
  Keep as the current concrete bootstrap doc for one local client implementation while making the architecture brand-agnostic.

- `docs/api/agent-api-usage.md`
  Keep as the source-of-truth API boundary doc for ingress, reevaluation, sync, dispatch, and supervision.

- `docs/architecture/system-context.md`
  Keep as the source-of-truth architecture framing doc.

- `docs/demo/operator-walkthrough.md`
  Keep as the deterministic seeded-flow operator walkthrough for dashboard screenshots and demo narration.

- `docs/howto/index.md`
  Create as the reader-facing documentation index for release use.

- `docs/howto/local-quickstart.md`
  Create as the shortest credible start-here guide for first-time local users.

- `docs/howto/configure-harness.md`
  Create as the configuration guide covering required env vars, optional overrides, storage selection, and current repair-receiver wiring.

- `docs/howto/test-and-validate.md`
  Create as the end-to-end testing and validation guide, including dry runs, local live smoke, hosted callback smoke, and what counts as proof.

- `docs/howto/use-harness.md`
  Create as the how-to for day-one use: submit work, inspect task truth, use the reset verifier, read the supervision queue, and judge whether Harness is actually working.

- `docs/howto/troubleshoot.md`
  Create as the operator troubleshooting guide for startup failures, env mistakes, hosted reset issues, unreachable repair callbacks, and bad-proof loops.

- `docs/howto/images/local-dashboard-tasks.png`
- `docs/howto/images/local-dashboard-task-detail.png`
- `docs/howto/images/local-dashboard-reviews.png`
- `docs/howto/images/reset-dryrun-verified.png`
- `docs/howto/images/reset-dryrun-review.png`
- `docs/howto/images/health-check-response.png`
  Create as screenshot assets referenced directly by the new how-to docs.

- `docs/release/documentation-readiness-checklist.md`
  Create as the final ship gate for docs completeness and verification evidence.

### Task 1: Run The Documentation Reality Audit Against The Current Product

**Files:**
- Modify: `README.md`
- Modify: `docs/setup/local-development.md`
- Modify: `docs/setup/vercel-neon.md`
- Modify: `docs/api/agent-api-usage.md`
- Modify: `docs/architecture/system-context.md`
- Reference: `backend/server.py`
- Reference: `modules/reset/service.py`
- Reference: `modules/reset_live_smoke.py`
- Reference: `docs/demo/operator-walkthrough.md`

- [ ] **Step 1: Start from a clean install and verify the documented local commands still work**

Run:

```bash
python3 -m pip install -r requirements.txt
pnpm install --frozen-lockfile
python3 -m unittest tests.test_fastapi_backend tests.test_reset_dryrun tests.test_autonomous_dryrun tests.test_unattended_dryruns -v
pnpm lint
pnpm build
```

Expected:
- backend validation passes
- frontend lint and build pass
- any command drift is found before doc rewriting starts

- [ ] **Step 2: Run the documented local API and dashboard startup exactly as written**

Run in one terminal:

```bash
python3 -m uvicorn backend.server:app --host 127.0.0.1 --port 8000
```

Run in another terminal:

```bash
pnpm dev
```

Expected:
- backend responds on `http://127.0.0.1:8000/health`
- dashboard responds on `http://127.0.0.1:3000`
- no undocumented env prerequisite blocks startup

- [ ] **Step 3: Verify the current docs against the running product and write down every mismatch before editing prose**

Check:
- `README.md`
- `docs/setup/local-development.md`
- `docs/setup/vercel-neon.md`
- `docs/api/agent-api-usage.md`
- `docs/architecture/system-context.md`

Expected:
- a concrete mismatch list with exact file paths, commands, or route names
- no vague note like "docs feel stale"

- [ ] **Step 4: Commit the audit-driven corrections before broader restructuring**

```bash
git add README.md docs/setup/local-development.md docs/setup/vercel-neon.md docs/api/agent-api-usage.md docs/architecture/system-context.md
git commit -m "docs: correct release-facing command and boundary drift"
```

### Task 2: Build The Reader-Facing Documentation Information Architecture

**Files:**
- Create: `docs/howto/index.md`
- Modify: `README.md`
- Modify: `docs/setup/local-development.md`
- Modify: `docs/setup/vercel-neon.md`
- Modify: `docs/demo/operator-walkthrough.md`

- [ ] **Step 1: Create the new reader-facing documentation index**

Create:

````markdown
# Harness How-To Index

Start here if you want to run, verify, and trust Harness without reading the full architecture set first.

## Start Here

- [Local Quickstart](./local-quickstart.md)
- [Configure Harness](./configure-harness.md)
- [Use Harness](./use-harness.md)
- [Test And Validate](./test-and-validate.md)
- [Troubleshoot](./troubleshoot.md)

## Source-Of-Truth References

- [Agent API Usage](../api/agent-api-usage.md)
- [System Context](../architecture/system-context.md)
- [Local Development](../setup/local-development.md)
- [Vercel + Neon Deployment](../setup/vercel-neon.md)
- [Operator Demo Walkthrough](../demo/operator-walkthrough.md)
````

- [ ] **Step 2: Update the top-level README docs section so release readers land in the how-to flow first**

Modify the docs map in `README.md` so it leads with:

````markdown
## Docs And Screenshots

Start here:

- [`docs/howto/index.md`](docs/howto/index.md)
- [`docs/howto/local-quickstart.md`](docs/howto/local-quickstart.md)
- [`docs/howto/test-and-validate.md`](docs/howto/test-and-validate.md)

Source-of-truth references:

- [`docs/api/agent-api-usage.md`](docs/api/agent-api-usage.md)
- [`docs/architecture/system-context.md`](docs/architecture/system-context.md)
- [`docs/setup/local-development.md`](docs/setup/local-development.md)
- [`docs/setup/vercel-neon.md`](docs/setup/vercel-neon.md)
- [`docs/demo/operator-walkthrough.md`](docs/demo/operator-walkthrough.md)
````

- [ ] **Step 3: Remove duplicated navigation detours from the setup docs**

Update:
- `docs/setup/local-development.md`
- `docs/setup/vercel-neon.md`

Expected:
- those docs stay focused on execution details
- they do not compete with the new how-to index for orientation

- [ ] **Step 4: Commit the doc IA changes**

```bash
git add README.md docs/howto/index.md docs/setup/local-development.md docs/setup/vercel-neon.md docs/demo/operator-walkthrough.md
git commit -m "docs: add release-facing how-to index"
```

### Task 3: Write The Setup And Configuration Guides That Real Users Can Follow

**Files:**
- Create: `docs/howto/local-quickstart.md`
- Create: `docs/howto/configure-harness.md`
- Modify: `docs/setup/local-development.md`
- Modify: `docs/setup/vercel-neon.md`
- Modify: `docs/setup/openclaw-local.md`

- [ ] **Step 1: Write the local quickstart as the shortest credible path from clone to running system**

Create:

````markdown
# Local Quickstart

## Goal

Get Harness running locally with a healthy backend, a working dashboard, and one proof that the system is behaving correctly.

## 1. Install dependencies

```bash
python3 -m pip install -r requirements.txt
pnpm install --frozen-lockfile
```

## 2. Set local environment

Create repo-root `.env.local` with:

```bash
GITHUB_TOKEN=...
LINEAR_API_KEY=...
HARNESS_API_BASE_URL=http://127.0.0.1:8000
```

## 3. Start the backend

```bash
python3 -m uvicorn backend.server:app --host 127.0.0.1 --port 8000
```

## 4. Start the dashboard

```bash
pnpm dev
```

## 5. Verify the backend is healthy

```bash
curl -sS http://127.0.0.1:8000/health
```

## 6. Run one deterministic reset proof

```bash
python3 -m modules.reset_dryrun success
```
````

- [ ] **Step 2: Write the configuration guide with exact required and optional variables**

Create:

````markdown
# Configure Harness

## Required for reset verifier work

- `GITHUB_TOKEN`
- `LINEAR_API_KEY`

## Storage selection

- `HARNESS_STORE_BACKEND=file`
- `HARNESS_STORE_BACKEND=postgres`
- `DATABASE_URL`
- `POSTGRES_URL`

## Current repair receiver wiring

- `OPENCLAW_BASE_URL`
- `OPENCLAW_REPAIR_ENDPOINT`
- `OPENCLAW_REPAIR_BEARER_TOKEN`
- `OPENCLAW_CONFIG_PATH`
- `OPENCLAW_STATE_DIR`

The `OPENCLAW_*` names remain because the current concrete repair receiver adapter is OpenClaw-shaped today. They are not the product boundary.
````

- [ ] **Step 3: Tighten the setup docs so they agree with the new guides instead of partially overlapping them**

Modify:
- `docs/setup/local-development.md`
- `docs/setup/vercel-neon.md`
- `docs/setup/openclaw-local.md`

Expected:
- setup docs hold operational detail
- the new how-to docs hold the reader-first narrative

- [ ] **Step 4: Commit the setup and configuration guides**

```bash
git add docs/howto/local-quickstart.md docs/howto/configure-harness.md docs/setup/local-development.md docs/setup/vercel-neon.md docs/setup/openclaw-local.md
git commit -m "docs: add setup and configuration guides"
```

### Task 4: Write The Testing, Validation, And Troubleshooting Guides

**Files:**
- Create: `docs/howto/test-and-validate.md`
- Create: `docs/howto/troubleshoot.md`
- Modify: `docs/superpowers/plans/2026-04-18-reset-verifier-next-test-steps.md`
- Modify: `docs/api/agent-api-usage.md`
- Modify: `README.md`

- [ ] **Step 1: Write the testing and validation guide with staged commands**

Create:

````markdown
# Test And Validate Harness

## Fast local baseline

```bash
python3 -m unittest tests.test_fastapi_backend tests.test_reset_dryrun tests.test_autonomous_dryrun tests.test_unattended_dryruns -v
```

## Deterministic reset verifier proofs

```bash
python3 -m modules.reset_dryrun success
python3 -m modules.reset_dryrun review
```

## Local live smoke

```bash
HARNESS_RUN_LIVE_RESET_TESTS=1 python3 -m unittest tests.test_reset_live_smoke -v
```

## What counts as proof

- healthy `/health` response
- deterministic dry-run verdicts
- live Linear issue identifiers
- live GitHub branch, commit, and PR artifacts
- canonical read-model or reset contract state that matches the external artifacts
````

- [ ] **Step 2: Write the troubleshooting guide around real failure modes already present in the repo**

Create:

````markdown
# Troubleshoot Harness

## Backend starts but `/reset/*` is unavailable
- check database configuration
- check reset temp store fallback
- check startup logs for reset service initialization errors

## Dashboard loads but shows no real data
- verify `HARNESS_API_BASE_URL`
- verify backend reachability
- verify the dashboard is not pointing at a stale hosted backend

## Reset verifier cannot dispatch repair
- verify `OPENCLAW_BASE_URL`
- verify the remote receiver is reachable from the runtime
- verify bearer token configuration
- verify local `OPENCLAW_CONFIG_PATH` and `OPENCLAW_STATE_DIR` when using the local CLI path

## Claim says complete but Harness does not accept it
- verify repository
- verify branch
- verify commit SHA
- verify PR URL or PR number
- verify current-run proof instead of historical or unrelated branch reuse
````

- [ ] **Step 3: Align the how-to with the existing staged reset-test plan**

Modify:
- `docs/superpowers/plans/2026-04-18-reset-verifier-next-test-steps.md`

Expected:
- the narrow reset verifier plan and the reader-facing validation guide do not contradict each other

- [ ] **Step 4: Commit the testing and troubleshooting guides**

```bash
git add docs/howto/test-and-validate.md docs/howto/troubleshoot.md docs/superpowers/plans/2026-04-18-reset-verifier-next-test-steps.md docs/api/agent-api-usage.md README.md
git commit -m "docs: add testing, validation, and troubleshooting guides"
```

### Task 5: Run Harness Locally And Capture Deterministic Screenshot Assets

**Files:**
- Create: `docs/howto/images/local-dashboard-tasks.png`
- Create: `docs/howto/images/local-dashboard-task-detail.png`
- Create: `docs/howto/images/local-dashboard-reviews.png`
- Create: `docs/howto/images/reset-dryrun-verified.png`
- Create: `docs/howto/images/reset-dryrun-review.png`
- Create: `docs/howto/images/health-check-response.png`
- Modify: `docs/howto/use-harness.md`
- Modify: `docs/demo/operator-walkthrough.md`
- Modify: `README.md`

- [ ] **Step 1: Seed deterministic dashboard state before taking any screenshots**

Run:

```bash
python3 -m modules.demo_walkthrough reset --store-root .demo-store --output-dir demo-output/walkthrough
HARNESS_STORE_ROOT=.demo-store python3 -m uvicorn backend.server:app --host 127.0.0.1 --port 8000
pnpm dev
python3 -m modules.demo_walkthrough seed \
  --base-url http://127.0.0.1:8000 \
  --dashboard-url http://127.0.0.1:3000 \
  --output-dir demo-output/walkthrough
```

Expected:
- seeded tasks exist at deterministic local URLs
- screenshots are taken from stable state instead of ad hoc live data

- [ ] **Step 2: Capture the health and reset-verifier screenshots from real local runs**

Run:

```bash
curl -sS http://127.0.0.1:8000/health > /tmp/harness-health.json
python3 -m modules.reset_dryrun success
python3 -m modules.reset_dryrun review
```

Save screenshots as:
- `docs/howto/images/health-check-response.png`
- `docs/howto/images/reset-dryrun-verified.png`
- `docs/howto/images/reset-dryrun-review.png`

Expected:
- every screenshot reflects a real local run in the current repo

- [ ] **Step 3: Capture the dashboard screenshots from the seeded walkthrough**

Save screenshots as:
- `docs/howto/images/local-dashboard-tasks.png`
- `docs/howto/images/local-dashboard-task-detail.png`
- `docs/howto/images/local-dashboard-reviews.png`

Expected:
- task list, task detail, and review surfaces are visible and readable
- no stale screenshots from older product states remain referenced

- [ ] **Step 4: Write the usage guide around those exact screenshots**

Create:

````markdown
# Use Harness

## 1. Check backend health

See `docs/howto/images/health-check-response.png`.

## 2. Open the dashboard

See `docs/howto/images/local-dashboard-tasks.png`.

## 3. Inspect one task's canonical truth

See `docs/howto/images/local-dashboard-task-detail.png`.

## 4. Understand review and intervention surfaces

See `docs/howto/images/local-dashboard-reviews.png`.

## 5. Validate the reset verifier loop

See `docs/howto/images/reset-dryrun-verified.png` and `docs/howto/images/reset-dryrun-review.png`.
````

- [ ] **Step 5: Commit the screenshot-backed how-to**

```bash
git add docs/howto/use-harness.md docs/howto/images docs/demo/operator-walkthrough.md README.md
git commit -m "docs: add screenshot-backed usage guide"
```

### Task 6: Run The Final Release Documentation QA Pass

**Files:**
- Create: `docs/release/documentation-readiness-checklist.md`
- Modify: `README.md`
- Modify: `docs/howto/index.md`
- Modify: `docs/howto/local-quickstart.md`
- Modify: `docs/howto/configure-harness.md`
- Modify: `docs/howto/test-and-validate.md`
- Modify: `docs/howto/use-harness.md`
- Modify: `docs/howto/troubleshoot.md`

- [ ] **Step 1: Create the final release checklist**

Create:

````markdown
# Documentation Readiness Checklist

- [ ] every command in the reader-facing docs was run in this repo
- [ ] every route name matches the current backend
- [ ] every env var name matches the current code
- [ ] every screenshot comes from the current product state
- [ ] every screenshot is referenced from at least one doc
- [ ] quickstart works from clone to health check
- [ ] test guide works from deterministic dry runs through live smoke
- [ ] setup docs explain current OpenClaw-shaped env names without making the architecture vendor-specific
- [ ] README points readers to the right first doc
- [ ] no doc still describes an older product than the code
````

- [ ] **Step 2: Run the final documentation verification commands**

Run:

```bash
python3 -m unittest discover -s tests
pnpm lint
pnpm build
git diff --check
rg -n "TODO|TBD|coming soon|placeholder" README.md docs
```

Expected:
- tests pass
- frontend validation passes
- no whitespace issues
- no release-facing placeholder language remains

- [ ] **Step 3: Spot-check all new and modified doc links and screenshot references**

Check:
- `README.md`
- `docs/howto/index.md`
- `docs/howto/local-quickstart.md`
- `docs/howto/configure-harness.md`
- `docs/howto/test-and-validate.md`
- `docs/howto/use-harness.md`
- `docs/howto/troubleshoot.md`
- `docs/release/documentation-readiness-checklist.md`

Expected:
- all internal links resolve
- all screenshot paths exist

- [ ] **Step 4: Commit the release QA pass**

```bash
git add README.md docs/howto docs/release/documentation-readiness-checklist.md
git commit -m "docs: add release-readiness documentation checklist"
```
