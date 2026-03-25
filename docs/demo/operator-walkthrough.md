# Harness Operator Demo Walkthrough

This walkthrough uses the real public Harness API, persisted task state, and the dashboard's real inspection surfaces.

## Purpose

Use this flow when you want one repeatable demo that shows:

- accepted completion
- blocked due to insufficient evidence, then later accepted
- contradictory external facts forcing rollback to blocked
- review-required flow with explicit manual resolution
- long-running progress and handoff artifacts visible in timeline/evidence views

## Local Demo Flow

1. Reset prior demo state:

```bash
python -m modules.demo_walkthrough reset --store-root .demo-store --output-dir demo-output/walkthrough
```

2. Start the Harness API against the demo store:

```bash
.venv/bin/python -m modules.api --host 127.0.0.1 --port 8000 --store-root .demo-store
```

3. Start the dashboard in a separate terminal:

```bash
cp .env.example .env.local
pnpm install --frozen-lockfile
pnpm dev
```

The dashboard reads `HARNESS_API_BASE_URL` server-side through the Next proxy route. Set it in `.env.local`:

```bash
HARNESS_API_BASE_URL=http://127.0.0.1:8000
```

4. Seed the canonical walkthrough scenarios:

```bash
python -m modules.demo_walkthrough seed \
  --base-url http://127.0.0.1:8000 \
  --dashboard-url http://127.0.0.1:3000 \
  --output-dir demo-output/walkthrough
```

This writes:

- `demo-output/walkthrough/walkthrough.txt`
- `demo-output/walkthrough/walkthrough.json`
- per-scenario `.timeline.txt`, `.mmd`, and `.json` trace files

## Operator Narrative

Open the dashboard and inspect these seeded tasks:

- `demo-successful-completion`
  - Show that aligned evidence and reconciliation allow Harness to preserve `completed`.
- `demo-missing-evidence-then-completed`
  - Show the initial blocked decision, then the later evidence-driven completion.
- `demo-contradictory-facts-blocked`
  - Show a previously acceptable completion being rolled back to `blocked` because facts no longer align.
- `demo-review-required-then-completed`
  - Show that review is explicit and auditable, then later resolved.
- `demo-long-running-handoff`
  - Show `progress_artifact` and `handoff_artifact` appearing in the timeline before final completion.

If you passed `--dashboard-url`, the walkthrough summary prints direct links like:

- `http://127.0.0.1:3000/?task=demo-successful-completion`

## What To Explain

For each task, narrate:

1. what happened
2. what evidence or external facts arrived
3. what verification or reconciliation outcome Harness produced
4. which lifecycle transition resulted
5. why the final state is trustworthy or blocked
