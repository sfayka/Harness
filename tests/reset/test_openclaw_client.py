from __future__ import annotations

import json
import socket
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from modules.reset.openclaw_client import OpenClawRepairClient


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _OpenClawHandler(BaseHTTPRequestHandler):
    calls: list[dict] = []

    def do_POST(self) -> None:  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode("utf-8")
        payload = json.loads(body)
        _OpenClawHandler.calls.append({"path": self.path, "payload": payload})
        encoded = json.dumps({"status": "accepted"}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


class OpenClawRepairClientTests(unittest.TestCase):
    def setUp(self) -> None:
        _OpenClawHandler.calls = []
        self.port = _free_port()
        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), _OpenClawHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = OpenClawRepairClient(
            transport="http",
            base_url=f"http://127.0.0.1:{self.port}",
            repair_endpoint="/repair",
        )

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def test_request_repair_posts_expected_payload(self) -> None:
        response = self.client.request_repair(
            "KNO-999",
            reason="commit sha does not exist in the expected repository",
            contract_id="contract-1",
        )

        self.assertEqual(response["status"], "accepted")
        self.assertEqual(len(_OpenClawHandler.calls), 1)
        self.assertEqual(_OpenClawHandler.calls[0]["path"], "/repair")
        self.assertEqual(
            _OpenClawHandler.calls[0]["payload"],
            {
                "linear_issue_id": "KNO-999",
                "reason": "commit sha does not exist in the expected repository",
                "contract_id": "contract-1",
            },
        )

    def test_cli_transport_invokes_local_openclaw_agent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            capture_path = temp_path / "capture.json"
            cli_path = temp_path / "openclaw"
            cli_path.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import json",
                        "import os",
                        "import sys",
                        f"capture_path = {str(capture_path)!r}",
                        "with open(capture_path, 'w', encoding='utf-8') as handle:",
                        "    json.dump({'argv': sys.argv[1:], 'env': {",
                        "        'OPENCLAW_CONFIG_PATH': os.environ.get('OPENCLAW_CONFIG_PATH'),",
                        "        'OPENCLAW_STATE_DIR': os.environ.get('OPENCLAW_STATE_DIR'),",
                        "    }}, handle)",
                        "print(json.dumps({'status': 'queued'}))",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            cli_path.chmod(0o755)

            client = OpenClawRepairClient(
                transport="cli",
                cli_bin=str(cli_path),
                config_path="/tmp/openclaw.local.json5",
                state_dir="/tmp/openclaw-state",
                agent_id="harness-local",
                timeout_seconds=7.0,
            )

            response = client.request_repair(
                "KNO-999",
                reason="commit sha does not exist in the expected repository",
                contract_id="contract-1",
            )

            captured = json.loads(capture_path.read_text(encoding="utf-8"))
            self.assertEqual(response, {"status": "queued"})
            self.assertEqual(
                captured["argv"][:8],
                [
                    "agent",
                    "--local",
                    "--agent",
                    "harness-local",
                    "--session-id",
                    "harness-repair-kno-999",
                    "--message",
                    "Harness rejected completion for Linear issue KNO-999.\nHarness contract id: contract-1.\nVerification failure: commit sha does not exist in the expected repository.\nRe-dispatch work in OpenClaw, use the issue's existing repo and branch context, and do not treat the task as complete until there is a real repository, branch, commit SHA, and PR URL.",
                ],
            )
            self.assertEqual(captured["argv"][8:], ["--json", "--timeout", "7"])
            self.assertEqual(captured["env"]["OPENCLAW_CONFIG_PATH"], "/tmp/openclaw.local.json5")
            self.assertEqual(captured["env"]["OPENCLAW_STATE_DIR"], "/tmp/openclaw-state")


if __name__ == "__main__":
    unittest.main()
