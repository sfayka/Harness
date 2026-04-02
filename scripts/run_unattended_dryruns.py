#!/usr/bin/env python
"""Run unattended dry-run scenarios against the deployed Harness backend.

Tmux:
  tmux new -s harness-dryruns 'python scripts/run_unattended_dryruns.py --interval-seconds 300'

Environment:
  HARNESS_DRYRUN_BASE_URL=https://harness-qeav.onrender.com
  HARNESS_DRYRUN_OUTPUT_DIR=runs
  HARNESS_DRYRUN_INTERVAL_SECONDS=300
  HARNESS_DRYRUN_ITERATIONS=0
  HARNESS_DRYRUN_TIMEOUT_SECONDS=45
  HARNESS_DRYRUN_HEALTH_RETRIES=6
  HARNESS_DRYRUN_HEALTH_BACKOFF_SECONDS=5
  HARNESS_DRYRUN_MAX_RETRIES=2
  HARNESS_DRYRUN_DIAGNOSTICS_ENABLED=true
  HARNESS_DRYRUN_MAX_E2E_SUITE_RUNS=1

Stop / restart:
  Stop with Ctrl-C in the tmux pane. Restart by rerunning the same command.

Inspect logs:
  tail -f runs/log.jsonl
  find runs/reports -type f | sort
  find runs/raw -type f | sort
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.unattended_dryruns import default_config_from_env, run_unattended_loop


def build_parser() -> argparse.ArgumentParser:
    defaults = default_config_from_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=defaults["base_url"], help="Harness backend base URL")
    parser.add_argument("--output-dir", default=defaults["output_dir"], help="Directory for JSONL logs and raw response artifacts")
    parser.add_argument("--interval-seconds", type=float, default=defaults["interval_seconds"], help="Sleep interval between full three-scenario loops")
    parser.add_argument("--iterations", type=int, default=defaults["iterations"], help="How many loops to run. Use 0 to run forever.")
    parser.add_argument("--timeout-seconds", type=float, default=defaults["timeout_seconds"], help="HTTP timeout for health and scenario requests")
    parser.add_argument("--health-retries", type=int, default=defaults["health_retries"], help="Maximum health-check retries before a loop is recorded as failed")
    parser.add_argument("--health-backoff-seconds", type=float, default=defaults["health_backoff_seconds"], help="Base backoff between health retries; multiplied by attempt number")
    parser.add_argument("--max-retries", type=int, default=defaults["max_retries"], help="Maximum bounded retries for retryable unexpected failures")
    parser.add_argument("--max-e2e-suite-runs", type=int, default=defaults["max_e2e_suite_runs"], help="Maximum times to run the local E2E suite per unattended session")
    parser.add_argument(
        "--disable-diagnostics",
        action="store_true",
        help="Disable diagnostic report writing and the optional E2E regression hook",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return run_unattended_loop(
        base_url=args.base_url,
        output_dir=args.output_dir,
        interval_seconds=args.interval_seconds,
        iterations=args.iterations,
        timeout_seconds=args.timeout_seconds,
        health_retries=args.health_retries,
        health_backoff_seconds=args.health_backoff_seconds,
        max_retries=args.max_retries,
        diagnostics_enabled=not args.disable_diagnostics,
        max_e2e_suite_runs=args.max_e2e_suite_runs,
    )


if __name__ == "__main__":
    raise SystemExit(main())
