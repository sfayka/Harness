from __future__ import annotations

import contextlib
import io
import json
import socket
import sys
import tempfile
import unittest
from pathlib import Path

from modules.demo_bootstrap import bootstrap_demo, main
from modules.store import FileBackedHarnessStore


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class DemoBootstrapTests(unittest.TestCase):
    def _dashboard_command(self, *, port: int, root: Path) -> list[str]:
        return [
            sys.executable,
            "-m",
            "http.server",
            str(port),
            "--bind",
            "127.0.0.1",
            "--directory",
            str(root),
        ]

    def test_bootstrap_seeds_demo_and_returns_urls(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            dashboard_root = temp_path / "dashboard"
            dashboard_root.mkdir()
            (dashboard_root / "index.html").write_text("<html><body>Harness Demo</body></html>", encoding="utf-8")

            store_root = temp_path / "store"
            output_dir = temp_path / "output"
            api_port = _free_port()
            dashboard_port = _free_port()

            result, server, thread, dashboard_process = bootstrap_demo(
                api_port=api_port,
                dashboard_port=dashboard_port,
                store_root=str(store_root),
                output_dir=str(output_dir),
                dashboard_command=self._dashboard_command(port=dashboard_port, root=dashboard_root),
                readiness_timeout_seconds=10.0,
            )
            try:
                self.assertEqual(result.dashboard_url, f"http://127.0.0.1:{dashboard_port}")
                self.assertEqual(result.api_base_url, f"http://127.0.0.1:{api_port}")
                self.assertEqual(len(result.walkthrough.scenarios), 5)
                self.assertTrue((output_dir / "walkthrough.txt").exists())

                store = FileBackedHarnessStore(str(store_root))
                tasks = store.list_tasks()
                task_ids = {task["id"] for task in tasks}
                self.assertIn("demo-successful-completion", task_ids)
                self.assertIn("demo-long-running-handoff", task_ids)
            finally:
                dashboard_process.terminate()
                dashboard_process.wait(timeout=5)
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_cli_exit_after_seed_emits_json_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            dashboard_root = temp_path / "dashboard"
            dashboard_root.mkdir()
            (dashboard_root / "index.html").write_text("<html><body>Harness Demo</body></html>", encoding="utf-8")

            stdout = io.StringIO()
            api_port = _free_port()
            dashboard_port = _free_port()
            with contextlib.redirect_stdout(stdout):
                exit_code = main(
                    [
                        "--api-port",
                        str(api_port),
                        "--dashboard-port",
                        str(dashboard_port),
                        "--store-root",
                        str(temp_path / "store"),
                        "--output-dir",
                        str(temp_path / "output"),
                        "--dashboard-command",
                        " ".join(self._dashboard_command(port=dashboard_port, root=dashboard_root)),
                        "--exit-after-seed",
                        "--json",
                        "successful_completion",
                    ]
                )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["walkthrough"]["scenarios"][0]["task_id"], "demo-successful-completion")
            self.assertEqual(payload["dashboard_url"], f"http://127.0.0.1:{dashboard_port}")


if __name__ == "__main__":
    unittest.main()
