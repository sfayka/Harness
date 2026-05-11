# Auto-build Buildroom

The buildroom is a filesystem-backed contract chain for approval-gated Auto-build work.

It is deliberately boring in v0:

- no cron
- no unattended commits
- no production deploys
- no private Hermes runtime state
- no deletion side effects
- no live GitHub or Linear mutation

The point is to prove that a candidate signal can move through evidence, idea shaping, Main approval, bounded planning, implementation receipt, independent QA, trust reporting, retention recommendation, and operator summary without blurring truth boundaries.

## Contract Chain

A complete local buildroom contains these ordered artifacts:

1. `research_packet`
2. `idea_contract`
3. `intent_review`
4. `main_review`
5. `product_plan`
6. `build_plan`
7. `coder_receipt`
8. `qa_receipt`
9. `verification_delta`
10. `trust_report`
11. `retention_review`
12. `operator_summary`

## Guardrails

- Dreamer/Auto-think may create an idea contract, but it cannot approve itself.
- Main approval is required before build planning.
- Coder must stay within the product plan's allowed paths / planned files.
- QA must be independent from Coder.
- Trust reporting compresses room health without hiding uncertainty.
- Retention is recommendation-only in v0; it never deletes or moves live artifacts.

## Validate

```bash
python3 scripts/validate_buildroom.py buildroom/examples/demo-room
python3 -m unittest tests.test_buildroom_contract -v
```
