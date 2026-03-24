# Harness

Harness is a task orchestration layer built around Openclaw.

The goal is to give users a place to hand over ambiguous projects or loosely defined tasks, let the agent clarify what it needs, and then route the actual execution through a system that can be inspected and verified.

## Purpose

Harness is a continuation of the ideas behind InboxToBacklog, but in a fresh repository with a tighter focus on execution management.

At a high level, Harness should:

- accept a project or task from an upstream agent interface
- support clarification and validation when requirements are incomplete
- decompose work into smaller, concrete tasks
- assign tasks to subagents
- track assignment, progress, completion, and reporting
- provide an auditable record of what was planned, delegated, and finished

## Problem Statement

Autonomous agent systems often claim they can take a vague request and carry it through to completion. In practice, the missing layer is reliable task management.

Harness exists to fill that gap:

- break large work into manageable units
- make ownership explicit
- monitor work instead of assuming it completes
- surface status clearly back to the coordinating agent

## Rough Workflow

1. A user gives Openclaw a request.
2. Openclaw asks follow-up questions if needed.
3. Openclaw hands validated work to Harness.
4. Harness decomposes the work into tasks and sub-tasks.
5. Harness assigns those tasks to subagents.
6. Harness watches progress and handles follow-up when tasks stall or fail.
7. Harness aggregates results and reports status back upstream.

## Early Scope

This repository is expected to grow toward:

- task models and state tracking
- decomposition and assignment logic
- subagent coordination
- progress monitoring and retry handling
- reporting back to the controlling interface

## Initial Constraints

For now, Harness should optimize for clarity over automation theater.

- every task should have explicit state
- delegation should be visible and reviewable
- stalled or failed work should be surfaced instead of silently ignored
- upstream reporting should be grounded in actual task status
- ambiguous requests should be clarified before decomposition when possible

## Status

This is an early project scaffold. The README currently captures the intent and operating model so the repo has a concrete starting point.

## Architecture Docs

The architecture baseline for Epic 1 lives under `docs/`:

- [System Context](/Users/ssbob/Documents/Developer/Knox_Analytics/Harness/docs/architecture/system-context.md)
- [Module Boundaries](/Users/ssbob/Documents/Developer/Knox_Analytics/Harness/docs/architecture/module-boundaries.md)
- [Canonical Vocabulary](/Users/ssbob/Documents/Developer/Knox_Analytics/Harness/docs/architecture/canonical-vocabulary.md)
- [Repository Layout Proposal](/Users/ssbob/Documents/Developer/Knox_Analytics/Harness/docs/architecture/repository-layout.md)
- [ADR 0001](/Users/ssbob/Documents/Developer/Knox_Analytics/Harness/docs/adrs/0001-openclaw-as-ingress-harness-as-control-plane.md)
- [ADR 0002](/Users/ssbob/Documents/Developer/Knox_Analytics/Harness/docs/adrs/0002-initial-substrate-choice-and-replacement-strategy.md)
- [Initial Codex Tickets](/Users/ssbob/Documents/Developer/Knox_Analytics/Harness/docs/planning/initial-codex-tickets.md)
