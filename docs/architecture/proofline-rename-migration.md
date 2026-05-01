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
- API proxy route `app/api/proofline/[...path]`, with `app/api/harness/[...path]` retained as a compatibility alias
- environment variables such as `PROOFLINE_API_BASE_URL`, with `HARNESS_API_BASE_URL` retained as a compatibility alias
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

## Compatibility Map

| Identifier | Current Examples | Classification | Rename Rule |
| --- | --- | --- | --- |
| Product name | `Proofline` in README, dashboard labels, browser metadata, system context | current product name | Use for product-facing copy. |
| Repository name | `Harness`, `sfayka/Harness`, local path segments | rename-later | Rename last, after deployment, Codex Cloud, local clone, and GitHub integration migration notes exist. |
| CLI command shape | `python3 -m modules.local_runtime ...`, future `harness ...` examples | alias-first | Do not introduce a Proofline command until existing commands are documented and tested as compatibility aliases. |
| Frontend package name | `harness-dashboard` in `package.json` | rename-later | Rename only after build, deployment, and local dashboard packaging checks prove no package-name coupling. |
| Next.js proxy route | `app/api/proofline/[...path]`, `app/api/harness/[...path]` | alias-first | The Proofline route is the dashboard default. Keep the Harness route as a compatibility alias until external links and deployments have migrated. Both routes must share the same backend proxy behavior. |
| API base env vars | `PROOFLINE_API_BASE_URL`, `NEXT_PUBLIC_PROOFLINE_API_BASE_URL`, `HARNESS_API_BASE_URL`, `NEXT_PUBLIC_HARNESS_API_BASE_URL` | alias-first | Prefer Proofline-named overrides when both are present. Keep Harness-named overrides valid as compatibility fallbacks. Hosted same-project Vercel routing still takes precedence over either explicit override. |
| Storage env vars | `PROOFLINE_STORE_BACKEND`, `PROOFLINE_STORE_ROOT`, `PROOFLINE_SQLITE_PATH`, `PROOFLINE_RESET_STORE_BACKEND`, `PROOFLINE_RESET_STORE_ROOT`, plus Harness-named fallbacks | alias-first | Prefer Proofline-named storage overrides when both names are present. Keep Harness-named overrides valid as compatibility fallbacks. |
| Dashboard asset env vars | `PROOFLINE_DASHBOARD_ASSETS_DIR`, `HARNESS_DASHBOARD_ASSETS_DIR` | alias-first | Prefer the Proofline-named assets directory when both are present. Keep the Harness-named variable as a compatibility fallback. |
| Runtime/process env vars | `HARNESS_RUNTIME_*` | rename-later | Keep old env vars valid. Add Proofline aliases only after local-runtime process precedence is documented and tested. |
| Secret/service namespace | `com.knoxanalytics.harness.local-runtime`, Keychain/service labels | alias-first | Do not rename until migration preserves existing stored secrets or documents an explicit migration command. |
| Persisted schema fields | `harness_state`, `source_system=harness`, artifact metadata like `harness-task-id` | stable compatibility | Do not rename in-place. Add new projection fields only if old fields remain readable. |
| Task contract name | `TaskEnvelope` | stable | Do not rename unless schema versioning, docs, adapter mappings, and tests are updated together. |
| Python modules | `modules.local_runtime`, `modules.evaluation`, `modules.contracts.*` | rename-later | Keep until external imports, scripts, tests, and docs have aliases. |
| API routes | `/tasks`, `/reset/*`, `/sync/github`, `/execution-substrate/*`, `/ingress/*` | stable public surface | Do not rename for branding. Add only additive aliases with tests if a product need appears. |
| Demo and proof artifacts | `docs/demo/*`, `HARNESS-DRYRUN`, historical JSON payloads | historical evidence | Do not rewrite historical proof for branding. |
| ADRs and archive docs | old Harness/macOS decision records | historical evidence | Preserve original terms except for short framing notes when needed. |
| Vercel/deployment identifiers | project names, route config, hosted env keys | blocked | Audit separately before any rename. Hosted availability matters more than brand cleanliness. |

## Operator Naming Note

During the migration, operators may see Proofline in product surfaces while commands, env vars, route paths, and stored evidence still say Harness. That is expected. Treat Proofline as the product name and Harness as the current compatibility namespace.

## Phase 1: Product Copy And UI

Status: complete for the first visible surfaces.

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

Status: in progress.

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
