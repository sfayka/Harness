#!/usr/bin/env python3
"""Generate the minimal execution-facing contract bundle for sync consumers."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]


DEFAULT_OUTPUT_DIR = REPO_ROOT / "exports" / "agent-contract"
DEFAULT_EXAMPLES_DIR = REPO_ROOT / "examples" / "api"
SOURCE_PATHS = (
    "AGENTS.md",
    "README.md",
    "docs/api/agent-api-usage.md",
    "docs/architecture/runtime-execution-contract.md",
    "docs/integration/openclaw-harness-spike.md",
    "examples/api/create-task.json",
    "examples/api/evaluate-happy-path.json",
    "examples/api/evaluate-mismatch.json",
    "examples/api/evaluate-review-required.json",
    "scripts/render_api_examples.py",
)


def _repo_head_sha(repo_root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _bundle_readme(*, commit_sha: str, generated_at: str) -> str:
    source_docs = "\n".join(f"- `{path}`" for path in SOURCE_PATHS)
    return f"""# Harness Agent Contract Bundle

This directory is generated from the canonical Harness repository for execution agents and sync consumers such as `HARNESS-DRYRUN`.

Do not edit files in this directory manually. Re-run `.venv/bin/python scripts/export_agent_contract.py` from the Harness repo instead.

## Canonical API Surface

- `POST /tasks`: submit a new canonical task envelope
- `POST /tasks/<task_id>/reevaluate`: submit new evidence, facts, or review actions for an existing task
- `GET /tasks/<task_id>/read-model`: inspect current task truth
- `GET /tasks/<task_id>/timeline`: inspect the auditable task timeline

## Included Examples

- `examples/create-task.json`: canonical `POST /tasks` submission example generated from the ingress/OpenClaw request builder
- `examples/evaluate-happy-path.json`: canonical accepted-completion evaluation request
- `examples/evaluate-mismatch.json`: canonical reconciliation-mismatch evaluation request
- `examples/evaluate-review-required.json`: canonical review-required evaluation request

## Source Of Truth

This bundle was generated from these Harness source files:

{source_docs}

## Provenance

- source repo: `Harness`
- source commit: `{commit_sha}`
- generated at: `{generated_at}`
"""


def export_agent_contract(output_dir: Path) -> Path:
    commit_sha = _repo_head_sha(REPO_ROOT)
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    if output_dir.exists():
        shutil.rmtree(output_dir)

    render_examples_script = REPO_ROOT / "scripts" / "render_api_examples.py"
    subprocess.run([sys.executable, str(render_examples_script)], cwd=REPO_ROOT, check=True)

    examples_dir = output_dir / "examples"
    examples_dir.mkdir(parents=True, exist_ok=True)

    _write_json(
        output_dir / "provenance.json",
        {
            "generated_at": generated_at,
            "generator": "scripts/export_agent_contract.py",
            "source_commit_sha": commit_sha,
            "source_paths": list(SOURCE_PATHS),
            "source_repo": "Harness",
        },
    )
    (output_dir / "README.md").write_text(
        _bundle_readme(commit_sha=commit_sha, generated_at=generated_at),
        encoding="utf-8",
    )

    for example_name in (
        "create-task.json",
        "evaluate-happy-path.json",
        "evaluate-mismatch.json",
        "evaluate-review-required.json",
    ):
        shutil.copy2(DEFAULT_EXAMPLES_DIR / example_name, examples_dir / example_name)

    return output_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Export the minimal Harness agent contract bundle.")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory where the generated bundle should be written.",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir).expanduser().resolve()
    export_agent_contract(output_dir)
    print(output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
