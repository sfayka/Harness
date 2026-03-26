from __future__ import annotations

import contextlib
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path

from modules.api import run_server
from modules.demo_walkthrough import main, reset_demo_state, run_demo_walkthrough
from modules.store import FileBackedHarnessStore


class DemoWalkthroughTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store_root = Path(self.temp_dir.name) / "store"
        self.output_dir = Path(self.temp_dir.name) / "output"
        self.server = run_server(host="127.0.0.1", port=0, store_root=str(self.store_root))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp_dir.cleanup()

    def _run_cli(self, *args: str) -> tuple[int, str]:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(list(args))
        return exit_code, stdout.getvalue()

    def test_runs_canonical_walkthrough_and_persists_tasks(self) -> None:
        result = run_demo_walkthrough(
            base_url=self.base_url,
            output_dir=str(self.output_dir),
            dashboard_url="http://127.0.0.1:3000",
        )

        store = FileBackedHarnessStore(self.store_root)
        tasks = store.list_tasks()
        task_ids = {task["id"] for task in tasks}

        self.assertEqual(len(result.scenarios), 5)
        self.assertEqual(len(tasks), 5)
        self.assertIn("demo-successful-completion", task_ids)
        self.assertIn("demo-review-required-then-completed", task_ids)
        self.assertTrue((self.output_dir / "walkthrough.txt").exists())
        self.assertTrue((self.output_dir / "walkthrough.json").exists())
        self.assertTrue(all(item.dashboard_url for item in result.scenarios))

    def test_reset_helper_removes_demo_state(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.store_root.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "placeholder.txt").write_text("demo", encoding="utf-8")
        (self.store_root / "placeholder.txt").write_text("store", encoding="utf-8")

        reset_demo_state(store_root=str(self.store_root), output_dir=str(self.output_dir))

        self.assertTrue(self.output_dir.exists())
        self.assertTrue(self.store_root.exists())
        self.assertEqual(list(self.output_dir.iterdir()), [])
        self.assertEqual(list(self.store_root.iterdir()), [])

    def test_cli_seed_emits_json_summary(self) -> None:
        exit_code, output = self._run_cli(
            "seed",
            "--base-url",
            self.base_url,
            "--output-dir",
            str(self.output_dir),
            "--dashboard-url",
            "http://127.0.0.1:3000",
            "successful_completion",
            "--json",
        )
        payload = json.loads(output)

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(payload["scenarios"]), 1)
        self.assertEqual(payload["scenarios"][0]["task_id"], "demo-successful-completion")


if __name__ == "__main__":
    unittest.main()
