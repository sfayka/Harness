# Render + Supabase Deployment

Use this mode when the Vercel dashboard should read durable hosted Harness state that survives backend restarts and redeploys.

## Backend Configuration

Set these environment variables on the Render service:

- `HARNESS_STORE_BACKEND=postgres`
- `DATABASE_URL=<Supabase Postgres connection string>`

Leave `HARNESS_STORE_ROOT` unset for this mode.

## Database Bootstrap

Apply [`sql/postgres/001_harness_store.sql`](/Users/ssbob/Documents/Developer/Knox_Analytics/Harness/sql/postgres/001_harness_store.sql) to the Supabase database before the first backend start.

You can do that from the Supabase SQL editor or with `psql`:

```bash
psql "$DATABASE_URL" -f sql/postgres/001_harness_store.sql
```

After startup, `GET /health` reports the active `store_backend`, whether a database is configured, the parsed `database_host`, and whether the required `tasks` and `evaluation_records` tables are present. The endpoint never returns the raw `DATABASE_URL` or credentials.

## Dashboard Configuration

Set the Vercel dashboard environment variable:

- `HARNESS_API_BASE_URL=https://<render-service-url>`

The dashboard will continue using the canonical inspection APIs:

- `GET /tasks`
- `GET /tasks/<task_id>/read-model`
- `GET /tasks/<task_id>/timeline`

With the Postgres backend enabled, task envelopes and evaluation history persist across Render restarts and redeploys.
