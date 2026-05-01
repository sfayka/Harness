# Acceptance-Layer Inventory

## Purpose

Harness should now be treated as the working repository name for an acceptance layer, not as an execution product.

Codex, Symphony, Hermes, OpenClaw, and adjacent agent systems are absorbing runner features quickly. That is not a reason to broaden this repo. It is the reason to narrow it. The durable product is the system that decides whether AI-assisted software work is acceptable, evidence-backed, reconciled, and safe to call complete.

This inventory classifies the current repository into four buckets:

- `keep`: core acceptance-layer capability.
- `wrap`: useful only behind a boundary to an external system.
- `freeze`: keep working for compatibility, but do not expand.
- `delete`: remove after a separate cleanup PR proves no active path depends on it.

## Decision Rule

Keep a module only if it answers at least one acceptance-layer question:

1. What was supposed to happen?
2. What actually happened?
3. What evidence proves it?
4. What is still missing or contradictory?
5. What repair should be requested?
6. Can the work safely move to a terminal lifecycle state?

If a module primarily polls work, launches agents, supervises workspaces, performs unbounded retries, or offers a richer operator shell, it belongs below this system and should be wrapped, frozen, or deleted.

## Keep

These are the product.

| Area | Current Homes | Why It Stays |
| --- | --- | --- |
| Canonical work contract | `schemas/task_envelope.schema.json`, `modules/contracts/`, `modules/intake/`, `docs/architecture/task-envelope.md` | Defines the work and evidence contract that execution tools must satisfy. |
| Lifecycle enforcement | `modules/evaluation.py`, `modules/contracts/task_envelope_lifecycle.py`, `modules/contracts/task_envelope_enforcement.py`, state-transition docs | Prevents worker, Linear, or dashboard claims from bypassing policy. |
| Verification and evidence policy | `modules/contracts/task_envelope_verification.py`, `modules/contracts/task_envelope_evidence.py`, `docs/architecture/verification-and-completion-enforcement.md`, `docs/architecture/artifact-and-completion-evidence.md` | This is the acceptance boundary. |
| Reconciliation | `modules/contracts/task_envelope_reconciliation.py`, `modules/reconciliation_runtime.py`, reset reconciliation paths | Detects mismatches across Linear, GitHub, executor claims, and stored lifecycle state. |
| GitHub proof validation | `modules/connectors/github_artifact_validation.py`, `modules/connectors/github_facts.py`, `modules/reset/github_verifier.py` | GitHub remains the artifact truth for code-bearing work. |
| Linear truth alignment | `modules/connectors/linear_facts.py`, `modules/connectors/linear_ingress.py`, `modules/reset/linear_client.py`, `docs/architecture/linear-harness-boundary.md` | Linear is the visible structured-work surface, but not completion truth. |
| Manual review gates | `modules/contracts/task_envelope_review.py`, review endpoints/read-model fields | Human acceptance remains explicit and sticky. |
| Completion-claim ingestion | completion-claim endpoint paths, execution advisory contracts, attempt validation | Worker claims are useful input only after Harness applies proof policy. |
| Read model and timeline | `modules/read_model.py`, `GET /tasks`, `GET /tasks/<task_id>/read-model`, `GET /tasks/<task_id>/timeline` | Operators need inspectable acceptance state, not worker narrative. |
| Reset verifier slice | `modules/reset/`, `/reset/*` routes | It is the narrowest working expression of the acceptance-layer product. |
| Local CLI/API/web runtime | `modules/local_runtime.py`, `modules/local_setup.py`, `docs/architecture/local-runtime-contract.md` | The supported operator surfaces for inspection and local verification. Keep it portable. |

## Wrap

These should exist only as adapters. They should not define product truth.

| Area | Current Homes | Boundary |
| --- | --- | --- |
| Symphony-compatible execution | `modules/adapters/symphony/`, `modules/contracts/execution_substrate.py`, `modules/execution_substrate_dryrun.py`, `docs/architecture/symphony-execution-substrate.md` | Symphony can schedule and report attempts. It cannot complete work. |
| Codex and Codex Cloud | `modules/adapters/codex_cloud/`, Codex Cloud execution docs | Codex is an executor. It provides artifacts and summaries, not lifecycle authority. |
| OpenClaw/Hermes-style desktop clients | `modules/adapters/openclaw/`, `modules/connectors/openclaw_*`, `docs/integration/openclaw-harness-spike.md` | Treat as ingress or repair receivers. Do not couple the product to one client. |
| Linear mutation | Linear connector paths and reset client | Mutations must be projections of accepted Harness state or intended work setup, not agent-authored truth. |
| GitHub sync | GitHub connector paths and `/sync/github` | GitHub facts can upgrade evidence trust only through normalized sync and verification policy. |
| Execution substrate handoff previews | `/execution-substrate/intents`, `/execution-substrate/handoffs`, `/execution-substrate/transport-status` | Keep render-only and advisory until a separate live policy exists. |

## Freeze

These may stay for now, but new product work should not accumulate here.

| Area | Current Homes | Freeze Rule |
| --- | --- | --- |
| Historical macOS docs | macOS architecture and release notes | No new native features, signing, notarization, Launch at Login, notifications, or onboarding. Archive later. |
| Legacy direct dispatch paths | direct dispatch/test paths around old executor flow | Keep deterministic tests and compatibility only. New dispatch should target execution-substrate intents. |
| Planner/decomposition experiments | `modules/goal_to_work.py`, `modules/prd_ingestion.py`, `modules/prd_breakdown.py`, planner docs | Freeze until the acceptance boundary is stronger. Linear/Codex/Symphony may cover enough of this layer. |
| Demo/simulator surfaces | `modules/demo_*`, `modules/simulator.py`, `modules/runtime_scenario_builders.py` | Keep only when they prove acceptance semantics honestly. Do not let demos bypass canonical APIs. |
| Evolution engine concepts | `modules/evolution/`, `docs/architecture/harness-evolution-engine.md` | Interesting later, but not core until acceptance proof is stable. |
| Local eval harness | `docs/architecture/local-eval-harness.md` and related fixture ideas | Keep as verification support. Do not let it become a general agent benchmark product. |

## Delete After Separate PR

Do not delete these in the inventory PR. Deletion should be a narrow follow-up with validation.

| Candidate | Reason | Required Before Delete |
| --- | --- | --- |
| Native macOS app tree | Removed from the active tree after this inventory because it was no longer a supported surface and created validation noise. | Do not reintroduce unless the product decision is explicitly reopened. |
| macOS packaging scripts | Removed from the active tree because they encoded a rejected product path. | Do not reintroduce unless the product decision is explicitly reopened. |
| Historical macOS architecture docs | They are stale implementation guidance. | Move to `docs/archive/` or mark historical in-place before removal. |
| OpenClaw-specific naming in canonical docs | The role is client-neutral. | Keep concrete adapter docs, but remove OpenClaw as a default product anchor. |
| Broad planner/runtime language in README | It suggests Harness owns too much of the lifecycle. | Replace with acceptance-layer positioning and link to this inventory. |

## What Not To Build

Do not add:

- a competing Symphony daemon
- a custom always-on Linear poller
- a Codex workspace manager
- agent retry loops outside explicit budgets
- auto-merge as a default
- agent-authored Linear `Done` as completion truth
- a broad planner-intelligence surface
- a native desktop product shell
- a dashboard that becomes a mutation-heavy PM tool

## Near-Term Architecture Target

The product boundary should look like this:

```text
Linear intended work
        |
Acceptance contract
        |
Symphony/Codex/Hermes/OpenClaw execution adapters
        |
GitHub artifacts and runner events
        |
Acceptance verification, reconciliation, manual review
        |
Linear/GitHub/dashboard projections of accepted state
```

The layer in the middle may change every month. The acceptance boundary should not.

## Immediate PR Sequence

1. Land this inventory and rename ADR.
2. Retarget README and AGENTS language from "Harness control plane" toward the acceptance-layer name once the new name is accepted.
3. Archive or delete native macOS app code and packaging docs in a separate PR.
4. Mark direct dispatch paths as compatibility-only in code comments and docs.
5. Keep strengthening completion-claim, GitHub sync, Linear reconciliation, and manual-review enforcement.
