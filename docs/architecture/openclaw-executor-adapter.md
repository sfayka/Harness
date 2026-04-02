# OpenClaw Executor Adapter

## Purpose

Define the future adapter boundary that would allow Harness to use OpenClaw as an execution engine while keeping lifecycle truth, verification, and completion enforcement inside Harness.

This document is planning-only. It does not add a working OpenClaw execution integration.

## Scope

This architecture definition is limited to:

- executor-side boundary definition for a future OpenClaw adapter
- separation between ingress/client behavior and executor behavior
- explicit constraints that preserve Harness as lifecycle and completion authority

## Why It Exists

The repository already contains an ingress-side OpenClaw spike proving that OpenClaw can act as a thin client against Harness's public API.

A future executor adapter is a different concern:

- ingress answers how work enters Harness
- executor adaptation answers how assigned work could later be executed by OpenClaw

Keeping those concerns separate protects the core design:

- Harness remains the control plane
- OpenClaw remains replaceable
- completion remains evidence-backed instead of executor-declared

## Responsibilities

The future OpenClaw executor adapter should own only execution-boundary concerns such as:

- mapping canonical assigned-task data into an OpenClaw execution request
- translating OpenClaw runtime events into canonical execution facts
- normalizing produced artifacts, outputs, and trace references
- returning completion claims to Harness for verification instead of accepting them directly
- preserving provenance needed for audit and reevaluation

## Explicit Non-Responsibilities

The adapter must not:

- define lifecycle policy or terminal state semantics
- decide whether work is complete
- bypass `POST /tasks/<task_id>/reevaluate` or canonical enforcement paths
- replace Linear, GitHub, or other external fact sources
- act as the system of record for task truth
- absorb planning, decomposition, or verification responsibilities
- couple Harness control-plane rules to OpenClaw-specific runtime internals

## Non-Goals

This architecture definition explicitly does **not** include:

- implementing OpenClaw API wiring
- implementing a production-ready OpenClaw runtime integration
- making OpenClaw the source of lifecycle truth, completion truth, or policy decisions

## Inputs

Expected adapter inputs:

- canonical `TaskEnvelope` data for a task in an execution-ready state
- assignment metadata identifying OpenClaw as the selected executor
- execution attempt context from Harness runtime or dispatch layers
- constraints, acceptance criteria, artifact expectations, and provenance metadata

## Outputs

Expected adapter outputs:

- normalized execution start, progress, stall, failure, and completion events
- references to produced outputs and artifacts
- normalized trace or log references that later diagnostics can inspect
- explicit completion claims returned for Harness-side validation

The adapter output is execution telemetry and artifact references, not trusted completion.

## Relationship To Existing Harness Concepts

### TaskEnvelope

`TaskEnvelope` remains canonical. The adapter may project a subset into an OpenClaw request, but OpenClaw-specific request shape must not become the source of truth.

### Lifecycle States

Harness remains responsible for `assigned`, `executing`, `in_review`, `completed`, `blocked`, and related transitions. The adapter only reports execution facts that Harness may later evaluate.

### Execution Traces

The adapter is a likely producer of normalized execution-trace references. Those traces should support later audit and diagnostics, including future HEE analysis.

### Artifacts And Proof Of Completion

Artifacts produced through OpenClaw remain subject to Harness verification, reconciliation, and manual review rules. An OpenClaw success report is advisory only.

## Relationship To The Existing OpenClaw Spike

The existing spike in [`modules/connectors/openclaw_harness_spike.py`](../../modules/connectors/openclaw_harness_spike.py) proves an ingress/client boundary using the public Harness API.

This future adapter would be separate and executor-facing. It should not reuse the ingress spike as a runtime implementation shortcut.

## Replaceability Constraints

To preserve executor replaceability:

- Harness-facing adapter APIs should remain executor-generic instead of OpenClaw-specific.
- OpenClaw-specific request/response details should stay inside adapter translation code.
- Control-plane policies (evaluation outcomes, lifecycle transitions, review gates, reconciliation) must remain in Harness modules.
- Any future executor can implement the same canonical adapter contract without changing TaskEnvelope semantics.

## Future Implementation Notes

- Define a stable executor-adapter contract before any OpenClaw API wiring.
- Intercept completion claims and route them through canonical Harness verification rather than accepting executor status as terminal truth.
- Keep OpenClaw payload mapping explicit so executor-specific fields stay outside control-plane contracts.
- Preserve replaceability by keeping the adapter contract generic enough for other executors.
- Treat execution traces and artifact references as first-class outputs from the adapter boundary.

## Boundary Summary

OpenClaw may become a future execution backend.

Harness still owns truth.

## Related References

- [`completion-interception-and-artifact-validation-boundary.md`](./completion-interception-and-artifact-validation-boundary.md)
- [`task-envelope-to-openclaw-mapping.md`](./task-envelope-to-openclaw-mapping.md)
- [`codex-cloud-execution.md`](./codex-cloud-execution.md)
