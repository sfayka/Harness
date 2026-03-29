#!/usr/bin/env python3
"""Render canonical API examples from Harness source-of-truth builders."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from modules.connectors.openclaw_harness_spike import (  # noqa: E402
    OpenClawSourceContext,
    OpenClawTaskIntent,
    build_task_submission_payload,
)
from modules.demo_cases import build_demo_request  # noqa: E402


DEFAULT_OUTPUT_DIR = REPO_ROOT / "examples" / "api"


def _to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _to_jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _create_task_example() -> dict[str, Any]:
    return build_task_submission_payload(
        intent=OpenClawTaskIntent(
            task_id="task-openclaw-spike-1",
            title="Validate Harness API boundary from OpenClaw",
            description="Submit a task through the canonical Harness API boundary.",
            acceptance_criteria=(
                "Harness accepts the canonical task envelope at POST /tasks.",
                "The stored task preserves ingress provenance for later evaluation.",
            ),
            objective_summary="Prove that ingress clients can submit work through the canonical Harness API.",
            deliverable_type="api_submission",
            success_signal="Harness stores the task and returns the canonical inspection surfaces.",
            requested_by="operator@example.com",
        ),
        context=OpenClawSourceContext(
            conversation_id="conv-openclaw-spike-1",
            message_id="msg-openclaw-spike-1",
            channel="cli",
            workspace_id="workspace-openclaw-spike",
            user_id="operator@example.com",
            agent_id="openclaw-assistant",
        ),
    )


def render_examples(output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)

    examples = {
        "create-task.json": _create_task_example(),
        "evaluate-happy-path.json": {"request": _to_jsonable(build_demo_request("accepted_completion"))},
        "evaluate-mismatch.json": {"request": _to_jsonable(build_demo_request("blocked_reconciliation_mismatch"))},
        "evaluate-review-required.json": {"request": _to_jsonable(build_demo_request("review_required"))},
    }

    for filename, payload in examples.items():
        _write_json(output_dir / filename, payload)

    return output_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Render canonical Harness API examples.")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory where the generated examples should be written.",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir).expanduser().resolve()
    render_examples(output_dir)
    print(output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
