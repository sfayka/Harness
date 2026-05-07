# CLAUDE.md

This file gives Claude Code and other Claude-backed agents the repo-specific rules for working in Proofline.

Read `AGENTS.md` first. It is the canonical agent instruction file for this repository. This file exists so Claude-oriented tooling has an obvious local entrypoint without maintaining a second, divergent rule set.

## Product Boundary

Proofline validates agentic completion against user intent and evidence.

The repo may still be named Harness in paths, routes, env vars, persisted fields, and historical docs during the staged rename. Use Proofline for product-facing copy. Preserve Harness compatibility identifiers unless a task explicitly changes them and adds tested aliases.

## Non-Negotiable Invariants

- Agent-reported success is advisory only.
- Runner/Symphony/Codex/Hermes/OpenClaw completion is not Proofline truth.
- GitHub is artifact proof.
- Linear is intended-work state.
- Proofline owns lifecycle acceptance, verification, reconciliation, manual review, and append-only evaluation history.
- `TaskEnvelope` remains the canonical structured-work contract.
- Completion claims must flow through Proofline verification/reconciliation before work is called done.
- Manual review gates are sticky until an explicit review decision resolves them.
- Dashboard and inspection endpoints are read-only truth projections, not mutation shortcuts.

## Work Surfaces

Supported:

- Python backend/API
- CLI/runtime contract through `python3 -m modules.proofline_runtime ...`
- Next.js web dashboard
- static local dashboard assets served by the Python backend

Not active product direction:

- native macOS app
- menu-bar app
- notarization/DMG packaging
- Launch at Login
- notification-dependent workflows

## Execution Substrate Boundary

Symphony-compatible execution belongs below Proofline. It can schedule work, create workspaces, launch Codex, retry attempts, and report events. Those events remain advisory.

Do not build a competing always-on scheduler, Linear poller, Codex workspace manager, or unbounded retry loop inside Proofline unless a task explicitly reopens that architecture decision.

## Validation Commands

Docs-only changes:

```bash
git diff --check
python3 -m unittest tests.test_hosted_docs -v
```

Backend changes:

```bash
python3 -m unittest discover -s tests
```

Frontend changes:

```bash
pnpm test:frontend
pnpm lint
pnpm build
```

Synthetic full validation:

```bash
python3 scripts/proofline_validate.py
```

Live Linear/GitHub mutation smoke is gated and must stay on the approved dry-run targets:

```bash
HARNESS_RUN_LIVE_RESET_TESTS=1 python3 scripts/proofline_live_preflight.py --json
HARNESS_RUN_LIVE_RESET_TESTS=1 python3 -m unittest tests.test_reset_live_smoke -v
```

Approved targets:

- Linear project: `HARNESS-DRYRUN`
- GitHub repository: `sfayka/HARNESS-DRYRUN`
- Base branch: `main`

Do not run live mutation smoke against production work.

## Documentation Expectations

Keep the human docs readable:

- top-level `README.md` explains the product, current surfaces, setup, validation, and doc map
- `AGENTS.md` carries canonical repo rules
- this `CLAUDE.md` stays aligned with `AGENTS.md`
- detailed behavior lives in `docs/architecture/`, `docs/howto/`, `docs/setup/`, `docs/api/`, and `docs/release/`

Do not leave docs describing Proofline as a native macOS app, a PM tool, or an executor layer.
