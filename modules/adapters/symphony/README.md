# Symphony Execution Substrate Adapter

This adapter renders Harness execution-substrate intents into a Symphony-compatible handoff payload.

Current scope:

- accept only validated `ExecutionSubstrateIntent` objects
- preserve `completion_authority=harness_verification`
- include the Harness callback endpoint for runner events
- carry explicit runner prohibitions for completion, Linear Done state, and auto-merge
- produce an inert `render_only` payload for local tests and future transport wiring
- expose `DisabledSymphonyExecutionTransport` as the only transport boundary until a live policy exists

`DisabledSymphonyExecutionTransport.preview()` renders the same inert handoff shape without side effects.
`DisabledSymphonyExecutionTransport.dispatch()` always raises `SymphonyTransportDisabledError`.
Future live Symphony work should replace or wrap that transport boundary under an explicit policy gate instead of adding side effects to handoff preview rendering.

Non-goals:

- starting Symphony
- polling Linear
- launching Codex
- mutating GitHub
- accepting runner completion as Harness completion truth
