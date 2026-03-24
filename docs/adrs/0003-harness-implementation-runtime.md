# Harness Implementation Runtime: Python With API-First Integration Boundary

- title: Harness implementation runtime: Python with API-first integration boundary
- status: accepted
- date: 2026-03-24

## Context

Harness is the control plane and reliability layer of the system. It owns:

- task contracts and lifecycle semantics
- orchestration rules and transitions
- intake normalization and clarification behavior
- execution routing and artifact tracking
- completion verification and auditability

OpenClaw is an ingress/interface layer and is implemented in a Node/TypeScript ecosystem. Harness must integrate cleanly with OpenClaw today, while also remaining replaceable and usable with other ingress layers later.

The project priorities are:

- long-term maintainability
- explicit control-plane boundaries
- minimal coupling to ingress/runtime choices
- low operational friction for an open-source project
- clean communication between OpenClaw and Harness
- reliable, artifact-backed execution guarantees

The current implementation direction needs an explicit runtime decision because intake was implemented opportunistically in Node.js before a repo-level runtime choice was made.

## Decision

Harness will use **Python** as its primary implementation runtime.

Integration between OpenClaw and Harness will be **API-first**, using explicit service boundaries rather than shared runtime boundaries.

The architectural rules are:

- Harness runs as a standalone Python service
- OpenClaw interacts with Harness over typed HTTP/JSON APIs, webhooks, or equivalent process boundaries
- Harness business logic must not depend on OpenClaw runtime internals
- OpenClaw-specific integration behavior stays behind adapters
- API contracts are first-class and must be documented through an OpenAPI specification

## Rationale

Python is selected because Harness is primarily a control-plane/backend system rather than a plugin/runtime-extension system.

This choice is preferred because it:

- fits orchestration, state handling, contract enforcement, and backend service responsibilities well
- fits verification, auditability, and system-of-record reconciliation responsibilities well
- keeps Harness independent from OpenClaw’s Node/TypeScript runtime
- reduces the chance that OpenClaw implementation details leak into Harness business logic
- preserves flexibility if OpenClaw is later replaced by another ingress layer
- works well with API-first service patterns

API-first integration is required because it makes cross-runtime communication explicit and durable. A clean HTTP/OpenAPI boundary is easier to maintain long-term than direct code-sharing or in-process coupling.

## Consequences

- the repo should converge on Python as the primary implementation runtime
- the opportunistic Node intake implementation should be replaced or migrated
- Harness must expose explicit API contracts for ingress integration
- OpenClaw/Harness integration will rely on network/process boundaries rather than shared libraries
- TypeScript client generation may be used later for OpenClaw-side ergonomics, but generated clients are downstream artifacts rather than primary source of truth
- runtime choice should reinforce Harness as a standalone control plane, not as an agent-hosted extension

## Alternatives Considered

### Node/TypeScript As Primary Harness Runtime

Not selected.

Pros:
- language alignment with OpenClaw
- easier type-sharing if tightly coupled
- familiar ecosystem for OpenClaw-side integration

Cons:
- optimizes for runtime alignment with one ingress layer instead of long-term control-plane independence
- increases the risk of building Harness as an extension of OpenClaw instead of as a standalone service
- does not provide a clear long-term advantage if the integration boundary is API-first anyway

### Mixed Runtime Without Explicit Boundary

Not selected.

Pros:
- local convenience for individual tasks
- low short-term friction

Cons:
- creates architectural ambiguity
- increases tooling drift and maintenance cost
- makes ownership of modules and runtime assumptions unclear

### Python With API-First Boundary

Selected.

Pros:
- strongest separation between ingress and control plane
- good fit for backend/orchestration responsibilities
- keeps Harness replaceable and independent
- supports explicit service contracts

Cons:
- requires disciplined API design
- requires migration of opportunistic Node implementation work into Python

## Implementation Guidance

- Python is the default language for new Harness implementation work
- FastAPI or equivalent API-first Python tooling is preferred for ingress-facing service boundaries
- OpenAPI should be treated as the integration contract for OpenClaw-facing communication
- OpenClaw integration should be implemented through adapters/clients, not shared internal code
- Existing Node intake code should be treated as transitional and migrated into the Python module structure

## Architectural Constraint

Harness must remain operable as a standalone service. OpenClaw is a client of Harness, not its host runtime.

Harness business logic must not depend on:

- OpenClaw internal runtime types
- OpenClaw package/module imports
- Node-specific execution assumptions

All ingress communication must pass through explicit contracts owned by Harness.

This runtime choice supports the broader requirement that Harness own correctness, traceability, evidence enforcement, and auditability independently of whichever worker or ingress system is current.
