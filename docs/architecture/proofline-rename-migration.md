# Proofline Rename Migration

## Purpose

Define how the codebase moves from the current `Harness` implementation name to the Proofline product name without breaking operators, integrations, deployment configuration, or historical task evidence.

This is a staged compatibility migration, not a mechanical rename.

## Current State

`Proofline` is now the product-facing name for the acceptance layer.

`Harness` remains the active implementation name for:

- repository path and GitHub repository
- Python module names
- Next.js package name
- CLI examples based on `python3 -m modules.local_runtime`
- API proxy route `app/api/harness/[...path]`
- environment variables such as `HARNESS_API_BASE_URL`
- persisted runtime fields such as `harness_state`
- existing docs, demos, tests, and historical artifacts that refer to the implementation

Those identifiers are allowed to remain until a compatibility alias exists and the migration has a rollback path.

## Migration Principles

1. Product language moves first.
2. Public identifiers move only with aliases.
3. Contract names do not change casually.
4. Historical evidence is not rewritten.
5. Deployment and local setup must survive every step.
6. No step may weaken the acceptance-layer boundary.

## Do Not Rename Yet

Do not rename these in the next implementation PR:

- `TaskEnvelope`
- lifecycle states
- `/tasks`, `/reset/*`, `/sync/github`, `/execution-substrate/*`, or existing ingress routes
- `HARNESS_*` environment variables
- persisted fields such as `harness_state`
- Python packages under `modules/`
- the GitHub repository
- Vercel project names or hosted deployment identifiers

These are compatibility surfaces, not branding copy.

## Phase 1: Product Copy And UI

Status: in progress.

Allowed changes:

- README and high-level docs say Proofline.
- Dashboard visible labels say Proofline.
- Browser metadata says Proofline.
- Architecture diagrams say Proofline for the product role.
- `Harness` is explicitly documented as the current implementation name.

Required validation:

- `pnpm lint`
- `pnpm test:frontend`
- `pnpm build`
- search proving visible dashboard copy no longer brands the product as Harness

## Phase 2: Documentation Compatibility Map

Status: next.

Allowed changes:

- Add a compatibility table for every remaining `Harness` identifier.
- Mark which identifiers are stable forever, alias-first, or rename-later.
- Update setup/how-to docs so operators understand that commands may still use `harness` while the product is Proofline.

Do not change runtime behavior in this phase.

## Phase 3: Public Alias Layer

Status: not started.

Only begin after Phase 2 is merged.

Allowed changes:

- Add non-breaking aliases such as Proofline-facing route helpers while preserving existing `harness` routes.
- Add CLI/package alias documentation before introducing new binaries or commands.
- Add tests proving old and new entrypoints resolve to the same behavior.

Required rule:

The old `Harness` route, env, or command must remain valid until there is a deliberate deprecation window.

## Phase 4: Package And Deployment Names

Status: blocked.

Only begin when:

- local setup docs are fully updated
- CI/build/test commands do not assume old package names
- Vercel and hosted runtime configuration are audited
- rollback steps are written

This phase may rename:

- frontend package display metadata
- deploy-facing project labels
- generated artifact names
- optional CLI wrappers

It should still avoid renaming canonical task contracts.

## Phase 5: Repository Rename

Status: last.

The repository rename is the final step, not an early cleanup.

Do it only after:

- all docs point at Proofline product language
- active commands work under compatibility aliases
- external integrations have been checked
- deployment config is updated
- local clones and Codex Cloud setup instructions have a migration note

## Permanent Harness Identifiers

Some names may remain `Harness` indefinitely because they are internal compatibility or historical evidence rather than product branding:

- `TaskEnvelope` examples that contain old task provenance
- old demo artifacts
- historical ADRs and archived docs
- stored evaluation records
- external issue/PR titles already created under the old name

Do not rewrite historical evidence to make branding look cleaner.

## Success Criteria

The rename is healthy when:

- operators see Proofline in product surfaces
- existing local and hosted commands still work
- old env vars and API routes remain compatible
- new alias paths are tested before adoption
- Linear/GitHub verification semantics are unchanged
- no executor, Symphony runner, or desktop agent is treated as completion truth
