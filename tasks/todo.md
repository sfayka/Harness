# Acceptance Circuit Demo Prototype

## Spec

Create a read-only `/demo/acceptance-circuit` prototype with two selectable visual directions for the Proofline acceptance demo. Both versions should explain that an agent completion claim is advisory until Proofline validates intent, evidence, external facts, lifecycle policy, and review gates.

## Plan

- [x] Add a demo route with two selectable visual concepts.
- [x] Implement Version A as a dark aerospace/circuit-board acceptance board.
- [x] Implement Version B as a lighter forensic evidence-lab acceptance flow.
- [x] Keep both versions read-only and clearly demo/replay-oriented.
- [x] Revise the visual system toward a directional map/diagram with arrows and moving payloads.
- [x] Normalize vertical arrow offsets so up/down arrows use the same visual gap between node edges.
- [x] Add a lightweight animated acceptance-circuit hero asset for the README.
- [x] Reference the animated hero from the top of `README.md`.
- [x] Run frontend validation and inspect rendered output.

## Review

- Built as a contained prototype route at `/demo/acceptance-circuit`.
- `git diff --check` passed.
- Static preview route returned `200`, and the served HTML includes the corrected `162px` / `172px` vertical arrow offsets.
- Headless Chrome screenshot generated at `output/acceptance-circuit-arrow-check.png` for visual inspection.
- Animated README hero added at `docs/assets/proofline-acceptance-circuit.svg`; XML parsing and `git diff --check` passed.
- Full lint, typecheck, build, and local Next rendering were attempted, but Node/Next commands hung before producing diagnostics or binding a server in this sandbox. Stuck processes were stopped.
