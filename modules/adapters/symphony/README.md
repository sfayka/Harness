# Symphony Execution Substrate Adapter

This adapter renders Harness execution-substrate intents into a Symphony-compatible handoff payload.

Current scope:

- accept only validated `ExecutionSubstrateIntent` objects
- preserve `completion_authority=harness_verification`
- include the Harness callback endpoint for runner events
- carry explicit runner prohibitions for completion, Linear Done state, and auto-merge
- produce an inert `render_only` payload for local tests and future transport wiring

Non-goals:

- starting Symphony
- polling Linear
- launching Codex
- mutating GitHub
- accepting runner completion as Harness completion truth
