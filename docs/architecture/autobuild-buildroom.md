# Auto-build Buildroom Architecture

Auto-build v0 is a local, approval-gated contract chain. It is not a scheduler, runtime, PM tool, or permission slip for agents to build whatever they notice.

## Why This Exists

Research and agents can surface more candidate work than Sean should manually track. The useful capability is not automatic output volume; it is compounding judgment with receipts.

The buildroom turns a signal into reviewable work only when the handoff is explicit:

```text
research packet
  -> idea contract
  -> intent review
  -> Main review
  -> product plan
  -> build plan
  -> coder receipt
  -> QA receipt
  -> verification delta
  -> trust report
  -> retention review
  -> operator summary
```

## Role Boundaries

- **Research** gathers evidence.
- **Dreamer / Auto-think** shapes signals into candidate idea contracts.
- **Main** decides whether a candidate is worth building and writes the bounded product plan.
- **Coder** implements only the approved, bounded plan.
- **QA** independently verifies the implementation and evidence.
- **Trust** summarizes room health as `clean`, `watch`, or `investigate`.
- **Retention** recommends `keep`, `improve`, `park`, or `prune` without side effects.
- **Operator** sees the compressed status and next actions.

## v0 Constraints

The first useful version is intentionally local:

- no cron
- no live GitHub/Linear mutation
- no unattended commits
- no production deploys
- no deletion or pruning side effects
- no private runtime path dependency
- no expansion of Proofline into an execution scheduler

## Acceptance Boundary

Proofline remains the acceptance authority. Coder receipts are evidence, not truth. QA receipts are independent evidence, not automatic acceptance. Trust reports compress state, but they must not hide uncertainty.

The buildroom strengthens existing Proofline boundaries by making the planning-to-build handoff explicit and auditable.

## Validation

Use:

```bash
python3 scripts/validate_buildroom.py buildroom/examples/demo-room
python3 -m unittest tests.test_buildroom_contract -v
```

The validator checks:

- required ordered artifacts exist
- all artifacts share one `job_id`
- Dreamer cannot approve itself
- Main approval precedes build planning
- Coder changed paths stay within the product plan
- QA is independent from Coder
- verification delta is confirmed
- retention is recommendation-only
- live mutations are disabled

## Future Work

Only after the local chain proves useful:

1. render operator summaries in the dashboard
2. add more schemas and fixtures
3. connect approved product plans to existing Proofline task envelopes
4. add optional cron-generated candidate packets
5. add live execution hooks behind explicit operator approval
