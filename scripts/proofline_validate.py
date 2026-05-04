#!/usr/bin/env python3
"""Run Proofline's synthetic/local validation ladder.

This script intentionally excludes live Linear/GitHub mutation smoke. Use the
gated command in docs/howto/test-and-validate.md only after credentials and
artifact-creation approval are explicit.
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class ValidationStep:
    name: str
    command: tuple[str, ...]
    category: str


BACKEND_STEPS: tuple[ValidationStep, ...] = (
    ValidationStep(
        name="backend-unit-suite",
        command=("python3", "-m", "unittest", "discover", "-s", "tests"),
        category="backend",
    ),
)

SYNTHETIC_STEPS: tuple[ValidationStep, ...] = (
    ValidationStep(
        name="execution-substrate-event-stream",
        command=("python3", "-m", "modules.execution_substrate_dryrun", "event-stream"),
        category="synthetic",
    ),
    ValidationStep(
        name="execution-substrate-intent-consumer",
        command=("python3", "-m", "modules.execution_substrate_dryrun", "intent-consumer"),
        category="synthetic",
    ),
    ValidationStep(
        name="execution-substrate-handoff",
        command=("python3", "-m", "modules.execution_substrate_dryrun", "handoff"),
        category="synthetic",
    ),
    ValidationStep(
        name="reset-success-dryrun",
        command=("python3", "-m", "modules.reset_dryrun", "success"),
        category="synthetic",
    ),
    ValidationStep(
        name="reset-review-dryrun",
        command=("python3", "-m", "modules.reset_dryrun", "review"),
        category="synthetic",
    ),
)

FRONTEND_STEPS: tuple[ValidationStep, ...] = (
    ValidationStep(name="frontend-tests", command=("pnpm", "test:frontend"), category="frontend"),
    ValidationStep(name="frontend-lint", command=("pnpm", "lint"), category="frontend"),
    ValidationStep(name="frontend-build", command=("pnpm", "build"), category="frontend"),
)

COVERAGE_STEPS: tuple[ValidationStep, ...] = (
    ValidationStep(
        name="backend-coverage-run",
        command=("python3", "-m", "coverage", "run", "-m", "unittest", "discover", "-s", "tests"),
        category="coverage",
    ),
    ValidationStep(
        name="backend-coverage-report",
        command=("python3", "-m", "coverage", "report", "-m"),
        category="coverage",
    ),
)


def build_plan(*, include_frontend: bool, include_coverage: bool) -> tuple[ValidationStep, ...]:
    steps: list[ValidationStep] = []
    steps.extend(BACKEND_STEPS)
    if include_coverage:
        steps.extend(COVERAGE_STEPS)
    steps.extend(SYNTHETIC_STEPS)
    if include_frontend:
        steps.extend(FRONTEND_STEPS)
    return tuple(steps)


def run_step(step: ValidationStep, *, env: dict[str, str]) -> int:
    rendered = " ".join(shlex.quote(part) for part in step.command)
    print(f"\n==> {step.name} [{step.category}]\n{rendered}", flush=True)
    completed = subprocess.run(step.command, env=env, check=False)
    if completed.returncode != 0:
        print(f"\nFAILED: {step.name} exited {completed.returncode}", file=sys.stderr)
    return completed.returncode


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-frontend",
        action="store_true",
        help="Run only backend and synthetic dry-run checks.",
    )
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="Also run backend coverage. Requires coverage from requirements-dev.txt.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print the validation plan without running it.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    steps = build_plan(include_frontend=not args.skip_frontend, include_coverage=args.coverage)

    if args.list:
        for step in steps:
            rendered = " ".join(shlex.quote(part) for part in step.command)
            print(f"{step.name}\t{step.category}\t{rendered}")
        return 0

    env = dict(os.environ)
    for step in steps:
        exit_code = run_step(step, env=env)
        if exit_code != 0:
            return exit_code
    print("\nProofline synthetic/local validation passed.")
    print("Live Linear/GitHub mutation smoke remains gated and is not run by this script.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
