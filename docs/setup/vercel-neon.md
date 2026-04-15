# Vercel + Neon Deployment

Use this mode when Harness should run as one Vercel project with:

- a `web` service for the Next.js dashboard
- an `api` service for the Python backend
- Neon-backed Postgres injected through Vercel

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
- `DATABASE_URL=<provided by the Neon + Vercel integration>`

Leave `HARNESS_STORE_ROOT` unset in hosted mode.

Apply the schema before first real use:

```bash
psql "$DATABASE_URL" -f sql/postgres/001_harness_store.sql
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

`HARNESS_API_BASE_URL` remains available as a local-development override only.

## Storage Notes

Harness canonical state remains in Postgres:

- tasks
- evaluation records
- read-model inputs
- timeline inputs

Vercel Blob is optional in this slice. Only use it for real file-like hosted outputs if a concrete persistence surface needs it. Do not move canonical task truth out of Postgres.
