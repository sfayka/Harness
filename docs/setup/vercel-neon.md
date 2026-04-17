# Vercel + Neon Deployment

Use this mode when Harness should run as one Vercel project with:

- a `web` service for the Next.js dashboard
- an `api` service for the Python backend
- Neon-backed Postgres injected through Vercel
- optional Vercel Blob storage for future file/object surfaces

This is the default hosted deployment path for Harness.

## Project Shape

The Vercel project is declared in [`vercel.json`](../../vercel.json) with:

- `web` service
  - entrypoint: `.`
  - framework: `nextjs`
  - route prefix: `/`
- `api` service
  - entrypoint: `backend/server.py`
  - framework: `fastapi`
  - route prefix: `/backend`

## Backend Configuration

Set these environment variables for the backend service:

- `HARNESS_STORE_BACKEND=postgres`
- `POSTGRES_URL=<provided by the Neon + Vercel integration>`

Harness resolves the database connection string in this order:

- `DATABASE_URL`
- `POSTGRES_URL`
- `POSTGRES_URL_NON_POOLING`
- `POSTGRES_PRISMA_URL`
- `POSTGRES_URL_NO_SSL`

For a Vercel-managed Neon project, the normal hosted path is to leave `DATABASE_URL` unset and let the injected `POSTGRES_URL` win automatically.

Leave `HARNESS_STORE_ROOT` unset in hosted mode.

Reset-slice storage is different from canonical task storage. In hosted Vercel runtimes, the reset verifier now prefers Postgres-backed contract storage, with temp filesystem fallback only when no database URL is available:

- Postgres-backed `reset_contracts` storage when `POSTGRES_URL` or another supported database URL is available

That is now the default hosted path. `/reset/*` contracts survive across requests the same way the canonical task store does.

If the hosted runtime does not have a database URL, the reset slice falls back to:

- `HARNESS_RESET_STORE_ROOT=/tmp/harness-reset`

That keeps `/backend/health`, `/backend/tasks`, and the canonical task API healthy instead of crashing the whole service at import time.

That temp path is writable on Vercel but not durable across cold starts. Do not treat it as canonical hosted persistence.

If even the reset temp root cannot be created, `/reset/*` now fails explicitly with `503` instead of taking down the whole backend.

Apply the schema before first real use:

```bash
psql "$POSTGRES_URL" -f sql/postgres/001_harness_store.sql
```

The reset verifier now also bootstraps its own `reset_contracts` table on first Postgres access if that slice has not been migrated yet. That protects hosted `/backend/reset/*` routes from failing with opaque `500` errors when the canonical task schema exists but the reset slice has not been applied yet.

For hosted repair dispatch, set `OPENCLAW_BASE_URL` to a real remote receiver that the Vercel runtime can reach. Do not reuse a local development value like `http://127.0.0.1:18789`, because that only points back at the serverless container itself.

If that remote receiver requires bearer authentication, also set `OPENCLAW_REPAIR_BEARER_TOKEN`. Hosted Harness will include it as `Authorization: Bearer <token>` on the repair callback request.

If Harness rejects a completion claim and the OpenClaw repair callback is unreachable, the reset verifier now records the failed claim, moves the contract to `needs_review`, and updates Linear to `In Review`. It no longer returns a transport-only `400` that leaves the contract looking idle.

The backend health endpoint remains:

- `GET /backend/health`

It reports:

- `status`
- `store_backend`
- `database_configured`
- `database_host`
- `database_schema_ready`

The endpoint never returns raw credentials.

## Frontend Configuration

Hosted deployments should not require a manual `HARNESS_API_BASE_URL` when the dashboard and backend are deployed in the same Vercel project.

The dashboard derives the backend route automatically from:

- `VERCEL_URL`
- the backend route prefix `/backend`

`HARNESS_API_BASE_URL` remains available as a local-development override only. Hosted Vercel deployments prefer the same-project `/backend` route even if an older external override is still present in project settings.

## Storage Notes

Harness canonical state remains in Postgres:

- tasks
- evaluation records
- read-model inputs
- timeline inputs

Vercel Blob is optional in this slice. Only use it for real file-like hosted outputs if a concrete persistence surface needs it. Do not move canonical task truth out of Postgres.

When a Blob store is connected through Vercel, the platform injects:

- `BLOB_READ_WRITE_TOKEN`

Do not add Blob-specific application wiring until a concrete artifact surface actually needs object storage.
