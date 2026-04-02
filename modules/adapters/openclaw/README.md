# OpenClaw Executor Adapter

This directory contains a minimal real OpenClaw executor adapter path.

Current scope:

- project canonical `ExecutorDispatchInput` into a minimal OpenClaw request payload
- call an OpenClaw runtime client through a thin transport protocol
- normalize OpenClaw events/artifacts into canonical advisory execution models
- preserve advisory-only completion semantics for Harness lifecycle enforcement

The adapter intentionally keeps OpenClaw-specific request/response fields local to translation code in `executor_adapter.py`.

This directory remains distinct from ingress/client code in `modules/connectors/openclaw_harness_spike.py`.

Non-goals for this module:

- broad OpenClaw orchestration support
- lifecycle mutation from executor output
- bypassing canonical completion interception or reevaluation paths
