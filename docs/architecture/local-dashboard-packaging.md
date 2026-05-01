# Local Dashboard Packaging

The local Harness dashboard path should not ask operators to install Node, `pnpm`, or keep a developer checkout just to inspect task progress.

Harness can package the dashboard as static assets and serve those assets from the local Python runtime at `/dashboard`.
The dashboard still reads canonical Harness APIs. It does not get a separate local truth store and it does not fall back to sample data when the backend is unavailable.

## Decision

Use a prebuilt static dashboard bundle for local CLI/web operation.

The local dashboard build:

- runs with `HARNESS_DASHBOARD_OUTPUT=export`
- sets the Next base path to `/dashboard`
- removes the staged `app/api` routes before export
- builds the existing read-only dashboard routes as static files
- writes a manifest to `dist/local-dashboard/dashboard-manifest.json`

The normal hosted and developer dashboard build remains a Next.js app. It keeps `app/api/harness/[...path]/route.ts` so hosted deployments can proxy dashboard reads through the web service.

This split is intentional. The local static-dashboard path does not need a Node server because it talks to the same-origin Python API. The hosted path still benefits from the Next proxy because Vercel owns the web/backend service boundary.

## Build Artifact

From a repo checkout:

```bash
pnpm build:dashboard:local
```

The output directory is:

```text
dist/local-dashboard/
```

The generated bundle expects to be served at:

```text
/dashboard
```

The generated JavaScript resolves API calls in this order:

- `window.__HARNESS_DASHBOARD_CONFIG__.apiBaseUrl`, when an embedding shell provides it
- `NEXT_PUBLIC_PROOFLINE_API_BASE_URL`, when an explicit public API URL is compiled in
- `NEXT_PUBLIC_HARNESS_API_BASE_URL`, as a compatibility fallback
- same-origin paths, when `NEXT_PUBLIC_HARNESS_DASHBOARD_MODE=local-static`
- `/api/harness`, for the normal hosted/developer Next proxy mode

## Runtime Mount

The Python backend mounts packaged assets when `PROOFLINE_DASHBOARD_ASSETS_DIR` points at a directory containing `index.html`. `HARNESS_DASHBOARD_ASSETS_DIR` remains a compatibility fallback.

```bash
PROOFLINE_DASHBOARD_ASSETS_DIR="$PWD/dist/local-dashboard" \
python3 -m uvicorn backend.server:app --host 127.0.0.1 --port 8765
```

Expected local routes:

- `GET /dashboard/`
- `GET /dashboard/tasks/`
- `GET /dashboard/verification/`
- `GET /dashboard/reconciliation/`
- `GET /dashboard/reviews/`

The same process serves the canonical API routes such as `GET /tasks`, `GET /tasks/<task_id>/read-model`, and `GET /runtime/status`.

## Local Packaging Contract

A future packaged CLI/web distribution should either:

- place the prebuilt dashboard bundle at the configured `dashboard_assets_dir`
- set `PROOFLINE_DASHBOARD_ASSETS_DIR` before starting the Proofline runtime

The operator-facing launcher should open:

```text
http://127.0.0.1:<runtime-port>/dashboard
```

Closing a browser tab or optional dashboard window must not stop the runtime. Runtime control belongs to the CLI/runtime contract.

## Validation

Run both build modes before changing packaging behavior:

```bash
pnpm build
pnpm build:dashboard:local
pnpm test:frontend
```

Run backend validation when changing the runtime mount:

```bash
python3 -m unittest tests.test_fastapi_backend tests.test_local_runtime -v
```

If the dashboard cannot reach the local API, the UI should show the backend error. It must not silently switch to demo or sample data.
