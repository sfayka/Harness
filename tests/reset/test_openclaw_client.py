from __future__ import annotations

import json
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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


if __name__ == "__main__":
    unittest.main()
