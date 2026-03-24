# Contributing

Harness is still early. The most useful contributions right now are the ones that make contracts, verification rules, and control-plane boundaries clearer.

## Before Opening A Change

- read the README for project positioning
- read the docs in `docs/architecture/`
- check accepted ADRs in `docs/adrs/`
- prefer opening focused changes rather than broad mixed refactors

## Contribution Guidelines

- keep Harness positioned as a control plane and reliability layer
- do not treat executor-reported success as sufficient completion evidence
- preserve the boundary between ingress, control plane, systems of record, and executors
- avoid introducing runtime or framework choices that conflict with accepted ADRs
- update docs when contracts or architectural assumptions change

## Development Notes

- Python is the primary implementation runtime
- machine-readable contracts live in `schemas/`
- implementation modules live in `modules/`
- tests live in `tests/`

## Public Repository Hygiene

- do not commit secrets, tokens, or local credentials
- do not commit `.env` files, local virtual environments, or terminal dumps
- use obviously fake placeholders when examples need values

## License

License selection is not defined in this file. Maintainers should confirm the intended open-source license before making the repository public.
