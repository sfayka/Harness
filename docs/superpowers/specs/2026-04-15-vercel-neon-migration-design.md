# Harness Vercel + Neon Migration Design

## Goal

Migrate Harness from the current Vercel frontend plus separate Render/Supabase hosted posture to a single Vercel project using Vercel `Services`, Neon-hosted Postgres through Vercel Marketplace integration, and Vercel Blob for any real hosted object-storage needs.

This migration must preserve Harness's control-plane boundaries:

- Harness backend remains the canonical source of task truth
- task and evaluation persistence remain canonical and auditable
- agent claims remain advisory only
- deployment changes must not weaken evidence, reconciliation, or lifecycle enforcement

This migration is also explicitly an operations-simplification project:

- reduce always-on hosting cost where possible
- reduce the number of platforms and billing surfaces the operator must manage
- reduce the number of environment variables and deployment modes that can drift out of sync
- make hosted Harness easier to bring up for testing and end-to-end use without hours of configuration debugging

## Problem

The current hosted shape is operationally split:

- the dashboard is deployed on Vercel
- the Python backend is documented as a separate hosted service
- durable Postgres state is documented through Supabase
- repo docs and environment examples still assume local loopback during many flows

That posture creates three concrete issues:

1. It does not match the target operating model of a single Vercel-hosted project.
2. It leaves stale environment assumptions in place, especially around `HARNESS_API_BASE_URL=http://127.0.0.1:8000`.
3. It makes hosted execution and agent environments more fragile than they need to be because the deployment contract is split across products and older setup guidance.

There is also a fourth issue driving this migration:

4. Supabase's billing and hosted-runtime posture is a poor fit for the operator's goal of paying primarily for actual usage rather than carrying unnecessary always-on cost and operational overhead.

## Current Repo Reality

The repository audit shows:

- the dashboard is a Next.js app deployed via `vercel.json`
- the backend is a Python HTTP server in `modules/api.py`
- the frontend reaches the backend through `app/api/harness/[...path]/route.ts`
- persistence already uses generic Postgres via `DATABASE_URL`
- there is no direct Supabase SDK integration in the application code
- there is no active Supabase Auth migration surface in this repo today

This means the core migration is primarily about hosting topology, environment handling, and provider replacement rather than ripping out application-layer Supabase clients.

## Scope

This migration includes:

1. consolidating frontend and backend into one Vercel project using `Services`
2. replacing Supabase-hosted Postgres with Neon-hosted Postgres attached through Vercel
3. updating hosted deployment docs and environment contracts
4. removing hosted-path assumptions that point to `127.0.0.1`
5. introducing Vercel Blob only where hosted file/object storage is genuinely needed
6. reducing hosted configuration sprawl so Harness has one clear default hosted shape rather than several competing deployment stories

## Out Of Scope

This migration does not include:

- implementing or migrating user authentication
- changing canonical task, evaluation, read-model, or timeline semantics
- replacing Postgres as canonical task truth with Blob storage
- rewriting the backend into a new framework for aesthetic reasons
- changing ingress boundaries or moving control-plane policy into the frontend

## Platform Research Summary

The design is grounded in current platform capabilities:

- Vercel documents FastAPI/Python backend deployment and treats the deployed backend as a Vercel Function-backed service.
- Vercel's current Postgres guidance routes users to Marketplace-backed providers and notes that legacy Vercel Postgres is now Neon-backed for migrated users.
- Vercel Blob remains the hosted object-storage product for file-like data.
- Vercel `Services` is the preferred target for single-project consolidation in this migration because the user has confirmed that target is available in their account.

Relevant platform references:

- [Vercel Postgres](https://vercel.com/docs/postgres)
- [FastAPI on Vercel](https://vercel.com/docs/frameworks/backend/fastapi)
- [Vercel Blob](https://vercel.com/docs/vercel-blob)
- [Neon branching introduction](https://neon.com/branching/introduction)

## Operator Intent

The design and implementation plan should be optimized around the following operator intent:

1. move away from Supabase because the current pricing/runtime posture is a poor fit relative to Neon
2. consolidate to a single Vercel project when possible to reduce management and billing complexity
3. make Harness easy to stand up in one place for real testing and end-to-end use
4. minimize the number of systems, providers, and moving parts the operator must keep track of
5. make the hosted setup boring and predictable so agents are less likely to get trapped in environment-variable and deployment troubleshooting loops

This intent means the migration should prioritize:

- fewer platforms over theoretically flexible multi-provider posture
- one clear hosted path over several partially supported hosted paths
- explicit defaults over highly customizable but brittle configuration
- operational simplicity over clever deployment topology

## Recommended Approach

Use a single Vercel project with:

- one Next.js dashboard service
- one Python Harness API service
- one Neon Postgres database attached through Vercel-managed environment variables
- one optional Blob store for hosted file-like outputs

This is the recommended approach because it:

- satisfies the single-project hosting goal
- preserves the current backend/frontend boundary inside one deployment contract
- avoids an unnecessary backend rewrite during an infrastructure migration
- keeps canonical task truth in Postgres where it belongs
- simplifies provider management and billing into a much smaller operational surface
- creates one obvious hosted deployment story instead of Vercel-plus-separate-backend drift

## Rejected Alternatives

### Rewrite the backend into a Next.js-native API layer

Rejected for this phase because it combines:

- hosting migration
- runtime migration
- API surface migration
- operational migration

That is too much change at once for a control-plane system whose value depends on preserving semantic correctness.

### Keep the current split and only swap Supabase for Neon

Rejected as the primary plan because it does not satisfy the single-project hosting goal. It remains a fallback if `Services` becomes a real blocker during implementation.

## Target Architecture

### Frontend

The Next.js dashboard remains the user-facing inspection surface. It continues to read canonical backend APIs through a server-side proxy route rather than rebuilding control-plane truth client-side.

### Backend

The Python backend remains the control-plane API. It continues to own:

- canonical task submission
- reevaluation
- persistence
- read-model generation
- timeline generation
- evidence and reconciliation enforcement

### Database

Canonical task and evaluation state stays in Postgres. The repo already supports provider-neutral Postgres through `DATABASE_URL`, so Neon becomes the hosted provider without changing the storage model.

### Object Storage

Blob is not a database substitute. It is only for file-like hosted outputs such as:

- walkthrough exports
- captured operator artifacts
- future evidence bundles that are too large or too file-oriented for relational storage

Canonical task truth and append-only evaluation history remain in Postgres.

## Environment Contract

### Local Development

Local development should continue to support:

- `HARNESS_API_BASE_URL=http://127.0.0.1:8000`
- local file-backed store or local Postgres

This preserves fast local iteration and does not force hosted assumptions onto developers.

### Hosted Deployment

Hosted deployment must stop assuming loopback addresses. The dashboard proxy should resolve the backend using a hosted service URL or service-local environment variable appropriate for the Vercel project.

Principle:

- local mode may use loopback
- hosted mode must never depend on loopback assumptions

Hosted configuration should be deliberately minimal. The default hosted deployment should prefer a very small set of stable variables with obvious responsibility, rather than a large matrix of optional settings that can drift across environments.

### Database Configuration

Hosted database configuration should continue to center on `DATABASE_URL`, but the source of that value becomes the Vercel-attached Neon integration rather than Supabase or manually managed external setup.

The implementation plan should treat "fewer required env vars" as an explicit success criterion, not a side benefit.

## Migration Boundaries

The migration should be intentionally narrow:

1. update deployment topology
2. update provider attachment and environment handling
3. keep control-plane behavior unchanged

If backend runtime changes become necessary to satisfy Vercel service execution, they should be implemented as minimal hosting adapters rather than semantic changes to Harness logic.

The migration should also remove unnecessary deployment choices where possible. If there are multiple old hosted paths in docs or bootstrap flows, the implementation should converge them toward one preferred hosted story unless a secondary path is still clearly required.

## Rollout Plan

### Stage A: Deployment Contract Cleanup

- remove old hosted-path docs centered on Render + Supabase
- update README and setup docs to describe the new default hosted path
- fix examples and bootstrap guidance that incorrectly imply hosted loopback
- identify and remove stale or redundant hosted env knobs where they are no longer needed

### Stage B: Single-Project Vercel Support

- define the frontend and backend service layout
- wire hosted frontend proxying to the backend service
- preserve current local development behavior
- make the hosted path the obvious default rather than one option among many

### Stage C: Neon Validation

- validate schema bootstrap against Neon
- confirm health/readiness behavior remains correct
- verify backend tests still pass with Postgres-backed storage
- verify the database setup story is simple enough that a future agent is unlikely to misconfigure it

### Stage D: Blob Adoption

- identify file-like outputs that should survive in hosted mode
- move only those outputs to Blob-backed persistence
- leave canonical task/evaluation state untouched in Postgres

## Risks

### 1. Hosting Adapter Drift

The Python backend is currently a plain `http.server` application. Vercel service execution may require a small hosting adapter or an explicit backend service entrypoint.

Mitigation:

- keep control-plane logic in current modules
- isolate any hosting-specific adaptation at the boundary

### 2. Environment Confusion Across Local and Hosted Modes

The repo currently mixes local-first examples with hosted deployment docs.

Mitigation:

- make local and hosted env contracts explicit
- document which variables are loopback-only and which are hosted-only
- aggressively remove configuration branches that no longer provide real value

### 3. Blob Overreach

It would be easy to force Blob into core state because it is part of the target stack.

Mitigation:

- treat Blob as optional and purpose-specific
- require a concrete hosted object-storage need before moving any surface to Blob

### 4. Incidental Semantic Regression

Infrastructure changes can accidentally change request routing or startup semantics.

Mitigation:

- preserve canonical API paths
- preserve submission and reevaluation routes
- verify tests across backend and frontend surfaces before any completion claim

### 5. Simplicity Drift

It is easy for a migration plan to claim simplification while quietly preserving most of the old complexity under new names.

Mitigation:

- explicitly count and reduce hosted configuration inputs
- prefer one default hosted deployment path
- remove legacy docs and setup branches rather than merely adding a new preferred section beside them

## Success Criteria

1. Harness is deployed as a single Vercel project with separate frontend and backend services.
2. The hosted backend uses Neon-backed Postgres through Vercel-managed integration variables.
3. The default hosted deployment docs no longer depend on Render or Supabase.
4. Hosted execution paths no longer assume `127.0.0.1`.
5. Local development remains functional with loopback defaults.
6. Canonical read-model, timeline, lifecycle, and evaluation semantics remain unchanged.
7. Validation passes for the touched surfaces:
   - `python -m unittest discover -s tests`
   - `pnpm lint`
   - `pnpm build`
8. The hosted deployment path is materially simpler than the current state:
   - fewer providers
   - fewer required env variables
   - one clear default setup path in docs
9. Harness is easier to bring up for end-to-end testing without bespoke troubleshooting across separate hosting providers.

## Implementation Notes For The Follow-On Plan

The implementation plan should explicitly cover:

- `vercel.json` and any service layout/config changes
- backend service entrypoint requirements for Vercel hosting
- proxy route behavior in `app/api/harness/[...path]/route.ts`
- docs updates in `README.md` and `docs/setup/`
- any necessary Blob integration seam, only if tied to a real hosted artifact surface

The plan should avoid bundling auth, ingress redesign, or control-plane contract changes into this migration.
