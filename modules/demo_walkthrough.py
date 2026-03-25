"""Canonical end-to-end demo walkthrough for Harness."""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from modules.demo_runner import render_console_timeline, render_mermaid_trace
from modules.simulator import SimulationResult, run_scenario


@dataclass(frozen=True)
class DemoWalkthroughScenario:
    """One polished operator-facing demo scenario."""

    name: str
    title: str
    operator_focus: str
    dashboard_focus: str


@dataclass(frozen=True)
class DemoWalkthroughItem:
    """Persisted summary for one seeded demo scenario."""

    scenario_name: str
    scenario_title: str
    task_id: str
    final_status: str | None
    operator_focus: str
    dashboard_focus: str
    dashboard_url: str | None
    artifact_files: dict[str, str]


@dataclass(frozen=True)
class DemoWalkthroughResult:
    """Structured output for a canonical demo walkthrough seed run."""

    base_url: str
    output_dir: str
    scenarios: tuple[DemoWalkthroughItem, ...]


CANONICAL_WALKTHROUGH: tuple[DemoWalkthroughScenario, ...] = (
    DemoWalkthroughScenario(
        "successful_completion",
        "Accepted Completion",
        "Explain how aligned evidence and reconciliation allow Harness to preserve completed.",
        "Open the task timeline and show the single verification pass that ends in completed.",
    ),
    DemoWalkthroughScenario(
        "missing_evidence_then_completed",
        "Blocked To Completed",
        "Show that completion claims are blocked until the missing evidence actually arrives.",
        "Open the timeline and point out the blocked evaluation before the later review note resolves it.",
    ),
    DemoWalkthroughScenario(
        "contradictory_facts_blocked",
        "Contradictory Facts Rollback",
        "Show Harness reversing a previously accepted completion when external facts contradict it.",
        "Open the task detail and highlight the completed-to-blocked lifecycle reversal.",
    ),
    DemoWalkthroughScenario(
        "review_required_then_completed",
        "Review Required To Completed",
        "Show that manual review is explicit, auditable, and non-terminal until resolved.",
        "Open the review panel and timeline to show request then decision.",
    ),
    DemoWalkthroughScenario(
        "long_running_handoff",
        "Long-Running Handoff",
        "Show progress and handoff artifacts accumulating across evaluations without counting as completion evidence by default.",
        "Open evidence and timeline views to point out progress_artifact and handoff_artifact before final completion.",
    ),
)


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


def _slug(value: str) -> str:
    return value.replace("_", "-")


def reset_demo_state(*, store_root: str | None = None, output_dir: str | None = None) -> None:
    """Remove persisted demo state and walkthrough artifacts."""

    for target in (store_root, output_dir):
        if not target:
            continue
        path = Path(target)
        if path.exists():
            shutil.rmtree(path)


def _write_scenario_artifacts(output_dir: Path, result: SimulationResult) -> dict[str, str]:
    timeline_path = output_dir / f"{result.scenario_name}.timeline.txt"
    mermaid_path = output_dir / f"{result.scenario_name}.mmd"
    json_path = output_dir / f"{result.scenario_name}.json"

    timeline_path.write_text(render_console_timeline(result) + "\n", encoding="utf-8")
    mermaid_path.write_text(render_mermaid_trace(result) + "\n", encoding="utf-8")
    json_path.write_text(json.dumps(_to_jsonable(result), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return {
        "timeline": str(timeline_path),
        "mermaid": str(mermaid_path),
        "json": str(json_path),
    }


def run_demo_walkthrough(
    *,
    base_url: str,
    output_dir: str = "demo-output/walkthrough",
    dashboard_url: str | None = None,
    scenario_names: tuple[str, ...] | None = None,
) -> DemoWalkthroughResult:
    """Seed the canonical demo scenarios into one live Harness API."""

    selected_specs = tuple(
        spec for spec in CANONICAL_WALKTHROUGH if scenario_names is None or spec.name in scenario_names
    )
    invalid = sorted(set(scenario_names or ()) - {spec.name for spec in CANONICAL_WALKTHROUGH})
    if invalid:
        raise ValueError(f"Unknown walkthrough scenarios: {', '.join(invalid)}")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    scenario_items: list[DemoWalkthroughItem] = []
    for spec in selected_specs:
        task_id = f"demo-{_slug(spec.name)}"
        title = f"Demo: {spec.title}"
        result = run_scenario(
            spec.name,
            base_url=base_url,
            task_id_override=task_id,
            task_title_override=title,
            origin_source_id_override=task_id,
        )
        files = _write_scenario_artifacts(output_path, result)
        scenario_items.append(
            DemoWalkthroughItem(
                scenario_name=spec.name,
                scenario_title=spec.title,
                task_id=task_id,
                final_status=result.final_task_status,
                operator_focus=spec.operator_focus,
                dashboard_focus=spec.dashboard_focus,
                dashboard_url=f"{dashboard_url.rstrip('/')}/?task={task_id}" if dashboard_url else None,
                artifact_files=files,
            )
        )

    result = DemoWalkthroughResult(
        base_url=base_url,
        output_dir=str(output_path),
        scenarios=tuple(scenario_items),
    )

    (output_path / "walkthrough.json").write_text(
        json.dumps(_to_jsonable(result), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_path / "walkthrough.txt").write_text(format_walkthrough_summary(result) + "\n", encoding="utf-8")
    return result


def format_walkthrough_summary(result: DemoWalkthroughResult) -> str:
    """Render a concise operator-facing walkthrough summary."""

    lines = [
        "Harness End-to-End Demo Walkthrough",
        f"API Base URL: {result.base_url}",
        f"Artifacts Directory: {Path(result.output_dir).resolve()}",
        "",
        "Scenarios:",
    ]
    for index, scenario in enumerate(result.scenarios, start=1):
        lines.extend(
            [
                f"{index}. {scenario.scenario_title}",
                f"   task_id: {scenario.task_id}",
                f"   final_status: {scenario.final_status}",
                f"   operator_focus: {scenario.operator_focus}",
                f"   dashboard_focus: {scenario.dashboard_focus}",
                f"   timeline: {scenario.artifact_files['timeline']}",
                f"   mermaid: {scenario.artifact_files['mermaid']}",
                f"   json: {scenario.artifact_files['json']}",
            ]
        )
        if scenario.dashboard_url:
            lines.append(f"   dashboard_url: {scenario.dashboard_url}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    """Build the walkthrough CLI parser."""

    parser = argparse.ArgumentParser(description="Run the canonical Harness operator demo walkthrough.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List walkthrough scenarios")
    list_parser.add_argument("--json", action="store_true", dest="as_json", help="Emit machine-readable JSON")

    reset_parser = subparsers.add_parser("reset", help="Delete persisted demo store and generated walkthrough artifacts")
    reset_parser.add_argument("--store-root", default=".demo-store", help="Store root directory to remove")
    reset_parser.add_argument("--output-dir", default="demo-output/walkthrough", help="Walkthrough output directory to remove")

    seed_parser = subparsers.add_parser("seed", help="Seed the canonical walkthrough scenarios into a running Harness API")
    seed_parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Harness API base URL")
    seed_parser.add_argument("--output-dir", default="demo-output/walkthrough", help="Directory for walkthrough artifacts")
    seed_parser.add_argument("--dashboard-url", default=None, help="Optional dashboard URL used to print direct task links")
    seed_parser.add_argument("--json", action="store_true", dest="as_json", help="Emit machine-readable JSON")
    seed_parser.add_argument("scenario_names", nargs="*", help="Optional subset of walkthrough scenarios to seed")

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the canonical operator walkthrough."""

    args = build_parser().parse_args(argv)

    if args.command == "list":
        payload = [{"name": spec.name, "title": spec.title} for spec in CANONICAL_WALKTHROUGH]
        if args.as_json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            for item in payload:
                print(f"{item['name']}: {item['title']}")
        return 0

    if args.command == "reset":
        reset_demo_state(store_root=args.store_root, output_dir=args.output_dir)
        print(f"Removed demo state under {Path(args.store_root).resolve()} and {Path(args.output_dir).resolve()}")
        return 0

    selected = tuple(args.scenario_names) if args.scenario_names else None
    result = run_demo_walkthrough(
        base_url=args.base_url,
        output_dir=args.output_dir,
        dashboard_url=args.dashboard_url,
        scenario_names=selected,
    )
    if args.as_json:
        print(json.dumps(_to_jsonable(result), indent=2, sort_keys=True))
    else:
        print(format_walkthrough_summary(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
