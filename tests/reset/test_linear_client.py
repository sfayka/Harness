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
    issue_update_success = True
    comment_create_success = True
    apply_state_change = True
    issue_update_apply_sequence: list[bool] = []
    comment_reset_state_to_in_progress = False
    current_state_id = "state-in-progress"
    current_state_name = "In Progress"
    current_state_type = "started"

    @classmethod
    def reset(cls) -> None:
        cls.calls = []
        cls.issue_update_success = True
        cls.comment_create_success = True
        cls.apply_state_change = True
        cls.issue_update_apply_sequence = []
        cls.comment_reset_state_to_in_progress = False
        cls.current_state_id = "state-in-progress"
        cls.current_state_name = "In Progress"
        cls.current_state_type = "started"

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
                        "state": {
                            "id": _LinearHandler.current_state_id,
                            "name": _LinearHandler.current_state_name,
                            "type": _LinearHandler.current_state_type,
                        },
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
            state_id = payload["variables"]["input"]["stateId"]
            should_apply_state = (
                _LinearHandler.issue_update_apply_sequence.pop(0)
                if _LinearHandler.issue_update_apply_sequence
                else _LinearHandler.apply_state_change
            )
            if _LinearHandler.issue_update_success and should_apply_state:
                state_lookup = {
                    "state-in-progress": ("state-in-progress", "In Progress", "started"),
                    "state-review": ("state-review", "In Review", "started"),
                    "state-done": ("state-done", "Done", "completed"),
                }
                (
                    _LinearHandler.current_state_id,
                    _LinearHandler.current_state_name,
                    _LinearHandler.current_state_type,
                ) = state_lookup[state_id]
            response = {"data": {"issueUpdate": {"success": _LinearHandler.issue_update_success}}}
        elif "mutation CreateComment" in query:
            if _LinearHandler.comment_create_success and _LinearHandler.comment_reset_state_to_in_progress:
                _LinearHandler.current_state_id = "state-in-progress"
                _LinearHandler.current_state_name = "In Progress"
                _LinearHandler.current_state_type = "started"
            response = {"data": {"commentCreate": {"success": _LinearHandler.comment_create_success}}}
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
        _LinearHandler.reset()
        self.port = _free_port()
        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), _LinearHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = LinearResetClient(
            api_key="linear-test-token",
            api_url=f"http://127.0.0.1:{self.port}/graphql",
            state_confirmation_attempts=2,
            state_confirmation_delay_seconds=0,
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
        self.assertEqual(len(_LinearHandler.calls), 5)
        issue_query, update_mutation, state_readback_query, comment_mutation, final_state_query = _LinearHandler.calls
        self.assertEqual(issue_query["headers"]["Authorization"], "linear-test-token")
        self.assertEqual(update_mutation["variables"]["id"], "uuid-123")
        self.assertEqual(update_mutation["variables"]["input"]["stateId"], "state-done")
        self.assertIn("query IssueContext", state_readback_query["query"])
        self.assertEqual(comment_mutation["variables"]["input"]["issueId"], "uuid-123")
        self.assertIn("Harness status: verified", comment_mutation["variables"]["input"]["body"])
        self.assertIn("query IssueContext", final_state_query["query"])

    def test_raises_when_requested_state_is_missing(self) -> None:
        with self.assertRaises(LinearClientError):
            self.client.update_issue(
                "KNO-999",
                state="Blocked",
                harness_status="retrying",
                comment="missing state",
            )

    def test_raises_when_issue_update_reports_unsuccessful_mutation(self) -> None:
        _LinearHandler.issue_update_success = False

        with self.assertRaises(LinearClientError):
            self.client.update_issue(
                "KNO-999",
                state="In Review",
                harness_status="needs_review",
                comment="state update failed",
            )

    def test_raises_when_comment_create_reports_unsuccessful_mutation(self) -> None:
        _LinearHandler.comment_create_success = False

        with self.assertRaises(LinearClientError):
            self.client.update_issue(
                "KNO-999",
                state="In Review",
                harness_status="needs_review",
                comment="comment failed",
            )

    def test_raises_when_state_readback_does_not_match_requested_state(self) -> None:
        _LinearHandler.apply_state_change = False

        with self.assertRaises(LinearClientError):
            self.client.update_issue(
                "KNO-999",
                state="In Review",
                harness_status="needs_review",
                comment="state readback mismatch",
            )

    def test_retries_state_transition_when_first_confirmation_misses(self) -> None:
        _LinearHandler.issue_update_apply_sequence = [False, True]

        result = self.client.update_issue(
            "KNO-999",
            state="In Review",
            harness_status="needs_review",
            comment="retry state transition",
        )

        self.assertEqual(result["state"], "In Review")
        update_calls = [call for call in _LinearHandler.calls if "mutation UpdateIssue" in call["query"]]
        self.assertEqual(len(update_calls), 2)

    def test_reapplies_state_when_post_comment_verification_detects_drift(self) -> None:
        _LinearHandler.comment_reset_state_to_in_progress = True

        result = self.client.update_issue(
            "KNO-999",
            state="In Review",
            harness_status="needs_review",
            comment="post-comment drift",
        )

        self.assertEqual(result["state"], "In Review")
        update_calls = [call for call in _LinearHandler.calls if "mutation UpdateIssue" in call["query"]]
        self.assertEqual(len(update_calls), 2)


if __name__ == "__main__":
    unittest.main()
