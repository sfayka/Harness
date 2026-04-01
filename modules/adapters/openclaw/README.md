# OpenClaw Executor Adapter Scaffold

This directory reserves a future home for an execution adapter that lets Harness use OpenClaw as a worker backend.

Its intended boundary is executor-facing only:

- map assigned Harness work into an OpenClaw execution request
- normalize OpenClaw execution events back into Harness execution facts
- preserve artifact and trace references for later verification

This directory is distinct from the current ingress/client spike in `modules/connectors/openclaw_harness_spike.py`.

It does not currently implement:

- API wiring
- runtime dispatch
- execution logic
- completion acceptance
