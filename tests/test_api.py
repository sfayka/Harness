from __future__ import annotations

import json
import tempfile
import threading
import unittest
from dataclasses import asdict, is_dataclass
from enum import Enum
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from modules.api import HarnessApiService, evaluate_http_payload, run_server
from modules.demo_cases import build_demo_request
from modules.store import FileBackedHarnessStore


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
    return {"request": _to_jsonable(build_demo_request(case_name))}


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


class HarnessApiServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.service = HarnessApiService(store=FileBackedHarnessStore(self.temp_dir.name))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_service_persists_evaluation_and_task_snapshot(self) -> None:
        status, payload = self.service.evaluate(_request_payload("accepted_completion"))

        self.assertEqual(status, 200)
        self.assertEqual(payload["task_envelope"]["status"], "completed")
        self.assertEqual(payload["evaluation_record"]["task_id"], payload["task_envelope"]["id"])

        task_status, task_payload = self.service.get_task(payload["task_envelope"]["id"])
        history_status, history_payload = self.service.get_evaluation_history(payload["task_envelope"]["id"])

        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["status"], "completed")
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 1)

    def test_service_rejects_invalid_input_without_persisting_state(self) -> None:
        task_id = _request_payload("invalid_input")["request"]["task_envelope"]["id"]

        status, payload = self.service.evaluate(_request_payload("invalid_input"))
        task_status, task_payload = self.service.get_task(task_id)
        history_status, history_payload = self.service.get_evaluation_history(task_id)

        self.assertEqual(status, 400)
        self.assertTrue(payload["invalid_input"])
        self.assertEqual(task_status, 404)
        self.assertIn("not found", task_payload["error"].lower())
        self.assertEqual(history_status, 404)
        self.assertIn("not found", history_payload["error"].lower())


class HarnessHttpApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.server = run_server(host="127.0.0.1", port=0, store_root=self.temp_dir.name)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp_dir.cleanup()

    def _get_json(self, path: str) -> tuple[int, dict]:
        try:
            with urlopen(self.base_url + path) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            try:
                return error.code, json.loads(error.read().decode("utf-8"))
            finally:
                error.close()

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
            try:
                return error.code, json.loads(error.read().decode("utf-8"))
            finally:
                error.close()

    def test_health_endpoint(self) -> None:
        status, payload = self._get_json("/health")

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")

    def test_api_persists_accepted_completion_and_exposes_history(self) -> None:
        status, payload = self._post_json("/evaluate", _request_payload("accepted_completion"))
        task_id = payload["task_envelope"]["id"]

        task_status, task_payload = self._get_json(f"/tasks/{task_id}")
        history_status, history_payload = self._get_json(f"/tasks/{task_id}/evaluations")

        self.assertEqual(status, 200)
        self.assertEqual(payload["action"], "transition_applied")
        self.assertEqual(payload["task_envelope"]["status"], "completed")
        self.assertIn("evaluation_record", payload)
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["status"], "completed")
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 1)
        self.assertEqual(history_payload["evaluations"][0]["result"]["task_envelope"]["status"], "completed")

    def test_api_persists_blocked_result(self) -> None:
        status, payload = self._post_json("/evaluate", _request_payload("blocked_insufficient_evidence"))
        task_id = payload["task_envelope"]["id"]

        task_status, task_payload = self._get_json(f"/tasks/{task_id}")
        history_status, history_payload = self._get_json(f"/tasks/{task_id}/evaluations")

        self.assertEqual(status, 200)
        self.assertEqual(payload["target_status"], "blocked")
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["status"], "blocked")
        self.assertEqual(history_status, 200)
        self.assertEqual(history_payload["evaluations"][0]["result"]["target_status"], "blocked")

    def test_api_persists_reconciliation_mismatch_result(self) -> None:
        status, payload = self._post_json("/evaluate", _request_payload("blocked_reconciliation_mismatch"))
        task_id = payload["task_envelope"]["id"]

        task_status, task_payload = self._get_json(f"/tasks/{task_id}")
        history_status, history_payload = self._get_json(f"/tasks/{task_id}/evaluations")

        self.assertEqual(status, 200)
        self.assertEqual(payload["target_status"], "blocked")
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["status"], "blocked")
        self.assertEqual(history_status, 200)
        self.assertEqual(
            history_payload["evaluations"][0]["result"]["enforcement_result"]["verification_result"]["outcome"],
            "external_mismatch",
        )

    def test_api_persists_review_required_result(self) -> None:
        status, payload = self._post_json("/evaluate", _request_payload("review_required"))
        task_id = payload["task_envelope"]["id"]

        task_status, task_payload = self._get_json(f"/tasks/{task_id}")
        history_status, history_payload = self._get_json(f"/tasks/{task_id}/evaluations")

        self.assertEqual(status, 200)
        self.assertEqual(payload["action"], "review_required")
        self.assertTrue(payload["requires_review"])
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["status"], payload["task_envelope"]["status"])
        self.assertEqual(history_status, 200)
        self.assertEqual(history_payload["evaluations"][0]["result"]["action"], "review_required")

    def test_api_rejects_invalid_input_without_persisting_state(self) -> None:
        invalid_payload = _request_payload("invalid_input")
        task_id = invalid_payload["request"]["task_envelope"]["id"]

        status, payload = self._post_json("/evaluate", invalid_payload)
        task_status, task_payload = self._get_json(f"/tasks/{task_id}")
        history_status, history_payload = self._get_json(f"/tasks/{task_id}/evaluations")

        self.assertEqual(status, 400)
        self.assertEqual(payload["action"], "invalid_input")
        self.assertTrue(payload["invalid_input"])
        self.assertEqual(task_status, 404)
        self.assertEqual(history_status, 404)
        self.assertIn("not found", task_payload["error"].lower())
        self.assertIn("not found", history_payload["error"].lower())

    def test_api_retrieves_append_only_evaluation_history(self) -> None:
        payload = _request_payload("accepted_completion")
        task_id = payload["request"]["task_envelope"]["id"]

        first_status, _ = self._post_json("/evaluate", payload)
        second_status, _ = self._post_json("/evaluate", payload)
        history_status, history_payload = self._get_json(f"/tasks/{task_id}/evaluations")

        self.assertEqual(first_status, 200)
        self.assertEqual(second_status, 200)
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 2)

    def test_api_returns_not_found_for_missing_task(self) -> None:
        task_status, task_payload = self._get_json("/tasks/missing-task")
        history_status, history_payload = self._get_json("/tasks/missing-task/evaluations")

        self.assertEqual(task_status, 404)
        self.assertEqual(history_status, 404)
        self.assertIn("not found", task_payload["error"].lower())
        self.assertIn("not found", history_payload["error"].lower())

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
