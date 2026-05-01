# Local Quickstart

## Goal

Get Proofline running locally, prove the runtime is healthy, and open the dashboard that shows canonical task state.

Proofline is the product name. During the staged rename, checkout commands, environment variables, runtime paths, and stored evidence still use the Harness compatibility namespace. Do not rename those local identifiers by hand.

## Supported Local Path

The supported local operator path is CLI + web dashboard. The native macOS app is deprecated and should not be used as the normal install or validation path.

Use this path when you are developing the current Harness implementation or validating a PR.

```bash
python3 -m pip install -r requirements.txt
pnpm install --frozen-lockfile
```

Create repo-root `.env.local` when you need live GitHub or Linear validation:

```bash
GITHUB_TOKEN=...
LINEAR_API_KEY=...
PROOFLINE_API_BASE_URL=http://127.0.0.1:8000
# HARNESS_API_BASE_URL remains a compatibility fallback.
```

Start the backend:

```bash
python3 -m uvicorn backend.server:app --host 127.0.0.1 --port 8000
```

Start the dashboard in another terminal:

```bash
pnpm dev
```

Verify health:

```bash
curl -sS http://127.0.0.1:8000/health
```

Run one deterministic reset proof:

```bash
python3 -m modules.reset_dryrun success
```

For local static-dashboard validation, build the dashboard assets and serve them through the Python runtime:

```bash
pnpm build:dashboard:local
export PROOFLINE_DASHBOARD_ASSETS_DIR="$PWD/dist/local-dashboard"
python3 -m modules.proofline_runtime --json init
python3 -m modules.proofline_runtime --json start
python3 -m modules.proofline_runtime --json status
python3 -m modules.proofline_runtime --json stop
```

The Proofline-named alias is available for the same local runtime contract:

```bash
python3 -m modules.proofline_runtime --json status
```

Without packaged dashboard assets, the runtime can still be healthy, but `/dashboard` cannot render the static UI.

## What Good Looks Like

- `/health` returns `status: ok`
- the dashboard opens at `http://127.0.0.1:3000`
- deterministic reset dry runs produce accepted or review-required results without live GitHub or Linear mutations
- the local runtime can start, stop, recover, and serve the dashboard without direct SQLite edits
