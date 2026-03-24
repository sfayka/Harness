"""Minimal CLI/demo runner for Harness evaluation."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any

from modules.demo_cases import build_demo_request, list_demo_cases
from modules.evaluation import evaluate_task_case


def _to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _to_jsonable(val) for key, val in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _to_jsonable(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    return value


def _format_text_result(case_name: str, payload: dict[str, Any]) -> str:
    lines = [
        f"case: {case_name}",
        f"action: {payload['action']}",
        f"target_status: {payload['target_status']}",
        f"task_status: {payload['task_envelope']['status']}",
        f"accepted_completion: {payload['accepted_completion']}",
        f"requires_review: {payload['requires_review']}",
        f"invalid_input: {payload['invalid_input']}",
    ]
    reasons = payload.get("reasons") or []
    if reasons:
        lines.append("reasons:")
        lines.extend(f"- {reason}" for reason in reasons)
    error = payload.get("error")
    if error:
        lines.append(f"error: {error}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    """Build the minimal CLI parser."""

    parser = argparse.ArgumentParser(description="Run a canonical Harness evaluation demo case.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List canonical demo cases")
    list_parser.add_argument("--json", action="store_true", dest="as_json", help="Emit machine-readable JSON output")

    run_parser = subparsers.add_parser("run", help="Evaluate a canonical demo case")
    run_parser.add_argument("case_name", choices=list_demo_cases(), help="Canonical demo case to evaluate")
    run_parser.add_argument("--json", action="store_true", dest="as_json", help="Emit machine-readable JSON output")

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for local Harness evaluation demos."""

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "list":
        cases = list_demo_cases()
        if args.as_json:
            print(json.dumps({"cases": list(cases)}, indent=2, sort_keys=True))
        else:
            print("\n".join(cases))
        return 0

    request = build_demo_request(args.case_name)
    result = evaluate_task_case(request)
    payload = _to_jsonable(result)
    if args.as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(_format_text_result(args.case_name, payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
