from __future__ import annotations

import json
import threading
import unittest
from dataclasses import asdict, is_dataclass
from enum import Enum
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from modules.api import HarnessApiHandler, evaluate_http_payload, run_server
from modules.demo_cases import build_demo_request


def _to_jsonable(value):
    if is_dataclass(value):
        return {key: _to_jsonable(val) for key, val in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _to_jsonable(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    return value


def _request_payload(case_name: str) -> dict:
    return _to_jsonable(build_demo_request(case_name))


class HarnessApiPayloadTests(unittest.TestCase):
    def test_accepts_completion_payload(self) -> None:
        status, payload = evaluate_http_payload(_request_payload("accepted_completion"))

        self.assertEqual(status, 200)
        self.assertEqual(payload["action"], "transition_applied")
        self.assertEqual(payload["task_envelope"]["status"], "completed")

    def test_rejects_invalid_input_payload(self) -> None:
        status, payload = evaluate_http_payload(_request_payload("invalid_input"))

        self.assertEqual(status, 400)
        self.assertEqual(payload["action"], "invalid_input")
        self.assertTrue(payload["invalid_input"])


class HarnessHttpApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = run_server(host="127.0.0.1", port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def _post_json(self, path: str, payload: dict) -> tuple[int, dict]:
        request = Request(
            self.base_url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    def test_health_endpoint(self) -> None:
        with urlopen(self.base_url + "/health") as response:
            payload = json.loads(response.read().decode("utf-8"))

        self.assertEqual(response.status, 200)
        self.assertEqual(payload["status"], "ok")

    def test_api_returns_accepted_completion(self) -> None:
        status, payload = self._post_json("/evaluate", _request_payload("accepted_completion"))

        self.assertEqual(status, 200)
        self.assertEqual(payload["action"], "transition_applied")
        self.assertEqual(payload["task_envelope"]["status"], "completed")

    def test_api_returns_blocked_for_insufficient_evidence(self) -> None:
        status, payload = self._post_json("/evaluate", _request_payload("blocked_insufficient_evidence"))

        self.assertEqual(status, 200)
        self.assertEqual(payload["target_status"], "blocked")
        self.assertEqual(payload["task_envelope"]["status"], "blocked")

    def test_api_returns_blocked_for_reconciliation_mismatch(self) -> None:
        status, payload = self._post_json("/evaluate", _request_payload("blocked_reconciliation_mismatch"))

        self.assertEqual(status, 200)
        self.assertEqual(payload["target_status"], "blocked")
        self.assertEqual(payload["task_envelope"]["status"], "blocked")

    def test_api_returns_review_required(self) -> None:
        status, payload = self._post_json("/evaluate", _request_payload("review_required"))

        self.assertEqual(status, 200)
        self.assertEqual(payload["action"], "review_required")
        self.assertTrue(payload["requires_review"])

    def test_api_rejects_invalid_input(self) -> None:
        status, payload = self._post_json("/evaluate", _request_payload("invalid_input"))

        self.assertEqual(status, 400)
        self.assertEqual(payload["action"], "invalid_input")
        self.assertTrue(payload["invalid_input"])

    def test_api_rejects_malformed_json(self) -> None:
        request = Request(
            self.base_url + "/evaluate",
            data=b"{not-json",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request):
                self.fail("Expected malformed JSON request to be rejected")
        except HTTPError as error:
            self.assertEqual(error.code, 400)
            error.close()


if __name__ == "__main__":
    unittest.main()
