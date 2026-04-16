from __future__ import annotations

import json
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from modules.reset.linear_client import LinearClientError, LinearResetClient


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _LinearHandler(BaseHTTPRequestHandler):
    calls: list[dict] = []

    def do_POST(self) -> None:  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode("utf-8")
        payload = json.loads(body)
        _LinearHandler.calls.append(
            {
                "headers": dict(self.headers.items()),
                "query": payload["query"],
                "variables": payload["variables"],
            }
        )

        query = payload["query"]
        if "query IssueContext" in query:
            response = {
                "data": {
                    "issue": {
                        "id": "uuid-123",
                        "identifier": "KNO-999",
                        "url": "https://linear.app/knoxanalytics/issue/KNO-999/example",
                        "title": "Example",
                        "state": {"id": "state-in-progress", "name": "In Progress", "type": "started"},
                        "team": {
                            "id": "team-1",
                            "name": "Knoxanalytics",
                            "states": {
                                "nodes": [
                                    {"id": "state-in-progress", "name": "In Progress", "type": "started"},
                                    {"id": "state-review", "name": "In Review", "type": "started"},
                                    {"id": "state-done", "name": "Done", "type": "completed"},
                                ]
                            },
                        },
                    }
                }
            }
        elif "mutation UpdateIssue" in query:
            response = {"data": {"issueUpdate": {"success": True}}}
        elif "mutation CreateComment" in query:
            response = {"data": {"commentCreate": {"success": True}}}
        else:
            response = {"errors": [{"message": "unexpected query"}]}

        encoded = json.dumps(response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


class LinearResetClientTests(unittest.TestCase):
    def setUp(self) -> None:
        _LinearHandler.calls = []
        self.port = _free_port()
        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), _LinearHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = LinearResetClient(
            api_key="linear-test-token",
            api_url=f"http://127.0.0.1:{self.port}/graphql",
        )

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def test_update_issue_uses_uuid_for_mutation_and_raw_api_key_header(self) -> None:
        result = self.client.update_issue(
            "KNO-999",
            state="Done",
            harness_status="verified",
            comment="github proof verified",
        )

        self.assertEqual(result["issue_id"], "uuid-123")
        self.assertEqual(result["state"], "Done")
        self.assertEqual(len(_LinearHandler.calls), 3)
        issue_query, update_mutation, comment_mutation = _LinearHandler.calls
        self.assertEqual(issue_query["headers"]["Authorization"], "linear-test-token")
        self.assertEqual(update_mutation["variables"]["id"], "uuid-123")
        self.assertEqual(update_mutation["variables"]["input"]["stateId"], "state-done")
        self.assertEqual(comment_mutation["variables"]["input"]["issueId"], "uuid-123")
        self.assertIn("Harness status: verified", comment_mutation["variables"]["input"]["body"])

    def test_raises_when_requested_state_is_missing(self) -> None:
        with self.assertRaises(LinearClientError):
            self.client.update_issue(
                "KNO-999",
                state="Blocked",
                harness_status="retrying",
                comment="missing state",
            )


if __name__ == "__main__":
    unittest.main()
