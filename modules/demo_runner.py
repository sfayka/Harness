"""Canonical demo scenario pack with timeline and visual trace output."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from pathlib import Path
import threading
from typing import Any

from modules.api import run_server
from modules.simulator import SimulationResult, SimulationStepResult, list_scenarios, run_scenario


@dataclass(frozen=True)
class DemoScenarioSpec:
    """Canonical public demo scenario definition."""

    name: str
    title: str
    description: str


CANONICAL_DEMO_SCENARIOS: tuple[DemoScenarioSpec, ...] = (
    DemoScenarioSpec("successful_completion", "Accepted Completion", "A task is submitted with aligned evidence and accepted immediately."),
    DemoScenarioSpec("missing_evidence_then_completed", "Blocked To Completed", "A task is blocked for insufficient evidence, then resolved with additional artifacts."),
    DemoScenarioSpec("wrong_target_corrected", "Wrong Target Corrected", "A task starts with wrong repo or branch facts, then is corrected and accepted."),
    DemoScenarioSpec("review_required_then_completed", "Review Required To Completed", "A task enters manual review, then completes after an explicit review decision."),
    DemoScenarioSpec("contradictory_facts_blocked", "Contradictory Facts Rollback", "A task is accepted, then contradictory external facts force a rollback to blocked."),
    DemoScenarioSpec("long_running_handoff", "Long-Running Handoff", "A task accumulates progress and handoff artifacts over time before final completion."),
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


def _extract_updates(step: SimulationStepResult) -> list[str]:
    request = step.request_payload or {}
    request_body = request.get("request") if isinstance(request, dict) else None
    if not isinstance(request_body, dict):
        return []

    updates: list[str] = []
    if "new_artifacts" in request_body:
        artifacts = request_body.get("new_artifacts") or []
        artifact_types = [artifact.get("type", "unknown") for artifact in artifacts if isinstance(artifact, dict)]
        if artifact_types:
            updates.append(f"new_artifacts={', '.join(artifact_types)}")
    elif step.name == "submit":
        task_envelope = request_body.get("task_envelope")
        if isinstance(task_envelope, dict):
            items = task_envelope.get("artifacts", {}).get("items", [])
            artifact_types = [item.get("type", "unknown") for item in items if isinstance(item, dict)]
            if artifact_types:
                updates.append(f"artifacts={', '.join(artifact_types)}")

    if "external_facts" in request_body:
        external_facts = request_body.get("external_facts") or {}
        if isinstance(external_facts, dict):
            if external_facts.get("github_facts") is not None:
                branch_name = (((external_facts.get("github_facts") or {}).get("branch") or {}).get("name"))
                if branch_name:
                    updates.append(f"github_branch={branch_name}")
            if external_facts.get("linear_facts") is not None:
                linear_state = (external_facts.get("linear_facts") or {}).get("state")
                if linear_state:
                    updates.append(f"linear_state={linear_state}")

    if "completion_evidence" in request_body:
        evidence = request_body.get("completion_evidence") or {}
        validated_ids = evidence.get("validated_artifact_ids") or []
        if validated_ids:
            updates.append(f"validated_artifacts={len(validated_ids)}")

    if "review_decision" in request_body:
        decision = request_body.get("review_decision") or {}
        record = decision.get("record") or {}
        outcome = record.get("outcome")
        if outcome:
            updates.append(f"review_decision={outcome}")

    return updates


def _extract_verification_outcome(step: SimulationStepResult) -> str | None:
    return (
        (((step.payload.get("enforcement_result") or {}).get("verification_result") or {}).get("outcome"))
        if isinstance(step.payload, dict)
        else None
    )


def _extract_reconciliation_outcome(step: SimulationStepResult) -> str | None:
    verification = ((step.payload.get("enforcement_result") or {}).get("verification_result") or {})
    reconciliation = verification.get("reconciliation_result") or {}
    return reconciliation.get("outcome")


def render_console_timeline(result: SimulationResult) -> str:
    """Render a readable step-by-step timeline for one demo scenario."""

    lines = [
        f"Scenario: {result.scenario_name}",
        f"Task ID: {result.final_task_id}",
        f"Initial Task State: {result.steps[0].task_status if result.steps else 'unknown'}",
    ]
    for index, step in enumerate(result.steps, start=1):
        verification_outcome = _extract_verification_outcome(step) or "n/a"
        reconciliation_outcome = _extract_reconciliation_outcome(step) or "n/a"
        updates = _extract_updates(step)
        update_text = "; ".join(updates) if updates else "no new facts or artifacts"
        lines.extend(
            [
                f"{index}. {step.name}",
                f"   request: {step.method} {step.path}",
                f"   http_status: {step.http_status}",
                f"   added: {update_text}",
                f"   verification: {verification_outcome}",
                f"   reconciliation: {reconciliation_outcome}",
                f"   lifecycle: action={step.action} target_status={step.target_status} task_status={step.task_status}",
            ]
        )
    lines.append(f"Final Task State: {result.final_task_status}")
    return "\n".join(lines)


def render_mermaid_trace(result: SimulationResult) -> str:
    """Render a Mermaid sequence diagram for one demo scenario."""

    lines = [
        "sequenceDiagram",
        '    actor Simulator as "Demo Runner"',
        '    participant API as "Harness API"',
        '    participant Store as "Task Store"',
    ]
    for step in result.steps:
        updates = _extract_updates(step)
        verification_outcome = _extract_verification_outcome(step) or "n/a"
        reconciliation_outcome = _extract_reconciliation_outcome(step) or "n/a"
        update_label = "\\n".join(updates) if updates else "no new facts"
        lines.extend(
            [
                f'    Simulator->>API: {step.method} {step.path}\\n{step.name}',
                f'    Note right of API: {update_label}',
                f'    API->>Store: persist evaluation for {step.task_id}',
                f'    Store-->>API: task_status={step.task_status}',
                f'    API-->>Simulator: action={step.action}\\ntarget={step.target_status}\\nverification={verification_outcome}\\nreconciliation={reconciliation_outcome}',
            ]
        )
    lines.append(f'    Note over Simulator,API: final task state = {result.final_task_status}')
    return "\n".join(lines)


def _write_scenario_artifacts(output_dir: Path, result: SimulationResult) -> dict[str, str]:
    slug = result.scenario_name
    timeline_path = output_dir / f"{slug}.timeline.txt"
    mermaid_path = output_dir / f"{slug}.mmd"
    json_path = output_dir / f"{slug}.json"

    timeline_path.write_text(render_console_timeline(result) + "\n", encoding="utf-8")
    mermaid_path.write_text(render_mermaid_trace(result) + "\n", encoding="utf-8")
    json_path.write_text(json.dumps(_to_jsonable(result), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return {
        "timeline": str(timeline_path),
        "mermaid": str(mermaid_path),
        "json": str(json_path),
    }


def run_demo_pack(
    *,
    scenario_names: tuple[str, ...] | None = None,
    output_dir: str = "demo-output",
    base_url: str | None = None,
    store_root: str | None = None,
) -> tuple[SimulationResult, ...]:
    """Run the canonical demo scenario pack and write trace artifacts."""

    selected = scenario_names or tuple(spec.name for spec in CANONICAL_DEMO_SCENARIOS)
    invalid = [name for name in selected if name not in list_scenarios()]
    if invalid:
        raise ValueError(f"Unknown demo scenarios: {', '.join(invalid)}")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    if base_url is not None:
        results = tuple(run_scenario(name, base_url=base_url) for name in selected)
    else:
        collected: list[SimulationResult] = []
        for name in selected:
            scenario_store_root = store_root or str(output_path / ".demo-store" / name)
            Path(scenario_store_root).mkdir(parents=True, exist_ok=True)
            server = run_server(host="127.0.0.1", port=0, store_root=scenario_store_root)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                collected.append(run_scenario(name, base_url=base))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
        results = tuple(collected)

    index: list[dict[str, Any]] = []
    for result in results:
        files = _write_scenario_artifacts(output_path, result)
        index.append(
            {
                "scenario_name": result.scenario_name,
                "final_task_id": result.final_task_id,
                "final_task_status": result.final_task_status,
                "files": files,
            }
        )

    (output_path / "index.json").write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return results


def build_parser() -> argparse.ArgumentParser:
    """Build the demo-runner CLI parser."""

    parser = argparse.ArgumentParser(description="Run canonical Harness demo scenarios and generate trace artifacts.")
    parser.add_argument("--output-dir", default="demo-output", help="Directory where demo artifacts will be written")
    parser.add_argument("--base-url", default=None, help="Existing Harness API base URL; if omitted the runner starts a local API server")
    parser.add_argument("--store-root", default=None, help="Store root when the runner starts its own local API server")
    parser.add_argument("--json", action="store_true", dest="as_json", help="Emit machine-readable summary JSON to stdout")
    parser.add_argument("scenario_names", nargs="*", help="Optional subset of demo scenarios to run")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the canonical demo scenario pack."""

    args = build_parser().parse_args(argv)
    selected = tuple(args.scenario_names) if args.scenario_names else None
    results = run_demo_pack(
        scenario_names=selected,
        output_dir=args.output_dir,
        base_url=args.base_url,
        store_root=args.store_root,
    )

    if args.as_json:
        print(json.dumps(_to_jsonable(results), indent=2, sort_keys=True))
    else:
        for result in results:
            print(render_console_timeline(result))
            print("")
        print(f"Artifacts written to {Path(args.output_dir).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
