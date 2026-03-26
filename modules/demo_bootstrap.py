"""One-command local demo bootstrap for Harness."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from modules.api import run_server
from modules.demo_walkthrough import CANONICAL_WALKTHROUGH, DemoWalkthroughResult, reset_demo_state, run_demo_walkthrough


@dataclass(frozen=True)
class DemoBootstrapResult:
    """Structured result for a local demo bootstrap run."""

    api_base_url: str
    dashboard_url: str
    store_root: str
    output_dir: str
    walkthrough: DemoWalkthroughResult


def _wait_for_http_ready(url: str, *, timeout_seconds: float, interval_seconds: float = 0.25) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        try:
            with urlopen(url) as response:
                if 200 <= response.status < 500:
                    return
        except Exception as error:  # pragma: no cover - exercised via timeout path
            last_error = error
        time.sleep(interval_seconds)

    detail = f": {last_error}" if last_error is not None else ""
    raise TimeoutError(f"Timed out waiting for {url}{detail}")


def _default_dashboard_command(*, host: str, port: int) -> list[str]:
    return ["pnpm", "exec", "next", "dev", "--turbopack", "--hostname", host, "--port", str(port)]


def _start_dashboard_process(
    *,
    command: list[str],
    cwd: Path,
    api_base_url: str,
) -> subprocess.Popen[str]:
    env = dict(os.environ)
    env["HARNESS_API_BASE_URL"] = api_base_url
    return subprocess.Popen(command, cwd=str(cwd), env=env)


def _stop_dashboard_process(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return

    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _env_flag(name: str) -> bool:
    value = os.environ.get(name, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_or_default(name: str, default: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value


def format_bootstrap_summary(result: DemoBootstrapResult) -> str:
    """Render the operator-facing bootstrap summary."""

    lines = [
        "Harness Local Demo Bootstrap",
        f"Dashboard URL: {result.dashboard_url}",
        f"API Base URL: {result.api_base_url}",
        f"Store Root: {Path(result.store_root).resolve()}",
        f"Artifacts Directory: {Path(result.output_dir).resolve()}",
        "",
        "Demo Scenarios:",
    ]

    for index, scenario in enumerate(result.walkthrough.scenarios, start=1):
        lines.extend(
            [
                f"{index}. {scenario.scenario_title}",
                f"   task_id: {scenario.task_id}",
                f"   final_status: {scenario.final_status}",
                f"   dashboard_url: {scenario.dashboard_url}",
            ]
        )

    lines.extend(
        [
            "",
            "Available walkthrough scenarios:",
        ]
    )
    for scenario in CANONICAL_WALKTHROUGH:
        lines.append(f"- {scenario.name}: {scenario.title}")

    return "\n".join(lines)


def bootstrap_demo(
    *,
    api_host: str = "127.0.0.1",
    api_port: int = 8000,
    dashboard_host: str = "127.0.0.1",
    dashboard_port: int = 3000,
    store_root: str = ".demo-store",
    output_dir: str = "demo-output/walkthrough",
    dashboard_command: list[str] | None = None,
    scenario_names: tuple[str, ...] | None = None,
    readiness_timeout_seconds: float = 90.0,
) -> tuple[DemoBootstrapResult, Any, threading.Thread, subprocess.Popen[str]]:
    """Reset local demo state, start local surfaces, and seed the walkthrough."""

    repo_root = Path(__file__).resolve().parent.parent
    reset_demo_state(store_root=store_root, output_dir=output_dir)

    server = run_server(host=api_host, port=api_port, store_root=store_root)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    api_base_url = f"http://{api_host}:{server.server_port}"
    _wait_for_http_ready(f"{api_base_url}/health", timeout_seconds=readiness_timeout_seconds)

    dashboard_url = f"http://{dashboard_host}:{dashboard_port}"
    command = dashboard_command or _default_dashboard_command(host=dashboard_host, port=dashboard_port)
    dashboard_process = _start_dashboard_process(command=command, cwd=repo_root, api_base_url=api_base_url)

    try:
        _wait_for_http_ready(dashboard_url, timeout_seconds=readiness_timeout_seconds)
    except Exception:
        _stop_dashboard_process(dashboard_process)
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        raise

    try:
        walkthrough = run_demo_walkthrough(
            base_url=api_base_url,
            output_dir=output_dir,
            dashboard_url=dashboard_url,
            scenario_names=scenario_names,
        )
    except Exception:
        _stop_dashboard_process(dashboard_process)
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        raise
    result = DemoBootstrapResult(
        api_base_url=api_base_url,
        dashboard_url=dashboard_url,
        store_root=store_root,
        output_dir=output_dir,
        walkthrough=walkthrough,
    )
    return result, server, thread, dashboard_process


def bootstrap_against_existing_surfaces(
    *,
    api_base_url: str,
    dashboard_url: str,
    store_root: str = ".demo-store",
    output_dir: str = "demo-output/walkthrough",
    scenario_names: tuple[str, ...] | None = None,
    readiness_timeout_seconds: float = 90.0,
) -> DemoBootstrapResult:
    """Reset demo state and seed scenarios against existing API and dashboard surfaces."""

    reset_demo_state(store_root=store_root, output_dir=output_dir)
    _wait_for_http_ready(f"{api_base_url.rstrip('/')}/health", timeout_seconds=readiness_timeout_seconds)
    _wait_for_http_ready(dashboard_url, timeout_seconds=readiness_timeout_seconds)

    walkthrough = run_demo_walkthrough(
        base_url=api_base_url,
        output_dir=output_dir,
        dashboard_url=dashboard_url,
        scenario_names=scenario_names,
    )
    return DemoBootstrapResult(
        api_base_url=api_base_url,
        dashboard_url=dashboard_url,
        store_root=store_root,
        output_dir=output_dir,
        walkthrough=walkthrough,
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the local demo bootstrap CLI parser."""

    parser = argparse.ArgumentParser(description="Run the one-command Harness local demo bootstrap.")
    parser.add_argument("--api-host", default="127.0.0.1", help="Host interface for the Harness API")
    parser.add_argument("--api-port", type=int, default=8000, help="Port for the Harness API")
    parser.add_argument(
        "--api-base-url",
        default=None,
        help="Optional existing Harness API base URL to reuse instead of starting a local API server",
    )
    parser.add_argument("--dashboard-host", default="127.0.0.1", help="Host for the dashboard dev server")
    parser.add_argument("--dashboard-port", type=int, default=3000, help="Port for the dashboard dev server")
    parser.add_argument(
        "--dashboard-url",
        default=None,
        help="Optional existing dashboard URL to reuse instead of starting a local dashboard process",
    )
    parser.add_argument("--store-root", default=".demo-store", help="Directory for persisted demo task state")
    parser.add_argument("--output-dir", default="demo-output/walkthrough", help="Directory for walkthrough artifacts")
    parser.add_argument(
        "--dashboard-command",
        default=None,
        help="Optional dashboard command override, for example 'pnpm exec next dev --turbopack --hostname 127.0.0.1 --port 3000'",
    )
    parser.add_argument(
        "--readiness-timeout",
        type=float,
        default=90.0,
        help="Seconds to wait for the API and dashboard to become reachable",
    )
    parser.add_argument("--json", action="store_true", dest="as_json", help="Emit machine-readable JSON summary")
    parser.add_argument(
        "--exit-after-seed",
        action="store_true",
        help="Exit after printing the seeded demo summary instead of keeping local surfaces running",
    )
    parser.add_argument("scenario_names", nargs="*", help="Optional subset of canonical demo scenarios to seed")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the one-command local demo bootstrap."""

    args = build_parser().parse_args(argv)
    scenario_names = tuple(args.scenario_names) if args.scenario_names else None
    dashboard_command = shlex.split(args.dashboard_command) if args.dashboard_command else None
    reuse_existing_surfaces = _env_flag("HARNESS_DEMO_BOOTSTRAP_REUSE_SURFACES")
    api_base_url = args.api_base_url or (os.environ.get("HARNESS_API_BASE_URL") if reuse_existing_surfaces else None)
    dashboard_url = args.dashboard_url or (os.environ.get("HARNESS_DASHBOARD_URL") if reuse_existing_surfaces else None)
    store_root = _env_or_default("HARNESS_STORE_ROOT", args.store_root) if reuse_existing_surfaces else args.store_root
    output_dir = _env_or_default("HARNESS_DEMO_OUTPUT_DIR", args.output_dir) if reuse_existing_surfaces else args.output_dir
    server = None
    thread = None
    dashboard_process = None

    if api_base_url and dashboard_url:
        result = bootstrap_against_existing_surfaces(
            api_base_url=api_base_url,
            dashboard_url=dashboard_url,
            store_root=store_root,
            output_dir=output_dir,
            scenario_names=scenario_names,
            readiness_timeout_seconds=args.readiness_timeout,
        )
    else:
        result, server, thread, dashboard_process = bootstrap_demo(
            api_host=args.api_host,
            api_port=args.api_port,
            dashboard_host=args.dashboard_host,
            dashboard_port=args.dashboard_port,
            store_root=store_root,
            output_dir=output_dir,
            dashboard_command=dashboard_command,
            scenario_names=scenario_names,
            readiness_timeout_seconds=args.readiness_timeout,
        )

    if args.as_json:
        print(json.dumps(asdict(result), indent=2, sort_keys=True))
    else:
        print(format_bootstrap_summary(result))

    if args.exit_after_seed:
        _stop_dashboard_process(dashboard_process)
        if server is not None and thread is not None:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        return 0

    print("")
    print("Local demo surfaces are running. Press Ctrl-C to stop them.")

    try:
        while True:
            if dashboard_process is not None and dashboard_process.poll() is not None:
                raise RuntimeError("Dashboard process exited unexpectedly")
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        _stop_dashboard_process(dashboard_process)
        if server is not None and thread is not None:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
