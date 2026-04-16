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

Reset-slice storage is different from canonical task storage. The reset verifier still uses a local file-backed store today. In hosted Vercel runtimes, the application filesystem is read-only outside writable temp space, so the reset slice now defaults to:

- `HARNESS_RESET_STORE_ROOT=/tmp/harness-reset`

That keeps `/backend/health`, `/backend/tasks`, and the canonical task API healthy instead of crashing the whole service at import time.

That path is writable on Vercel but not durable across cold starts. Do not treat it as canonical hosted persistence.

If even the reset temp root cannot be created, `/reset/*` now fails explicitly with `503` instead of taking down the whole backend.

Apply the schema before first real use:

```bash
psql "$POSTGRES_URL" -f sql/postgres/001_harness_store.sql
```

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
