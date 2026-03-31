from __future__ import annotations

import json
import tempfile
import threading
import unittest
from dataclasses import dataclass
from typing import Callable
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from modules.api import run_server


@dataclass(frozen=True)
class RuntimeFlowResult:
    task_id: str
    create_status: int
    create_response: dict
    initial_fetch_status: int
    initial_fetch_response: dict
    evaluate_status: int
    evaluate_payload: dict
    evaluate_response: dict
    final_fetch_status: int
    final_fetch_response: dict


@dataclass(frozen=True)
class RuntimeReevaluationFlowResult:
    task_id: str
    create_status: int
    create_response: dict
    initial_fetch_status: int
    initial_fetch_response: dict
    reevaluate_status: int
    reevaluate_payload: dict
    reevaluate_response: dict
    final_fetch_status: int
    final_fetch_response: dict


class RuntimeApiTestCase(unittest.TestCase):
    """Run E2E scenarios against a real local HTTP server with deterministic storage."""

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

    def get_json(self, path: str) -> tuple[int, dict]:
        try:
            with urlopen(self.base_url + path) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            try:
                return error.code, json.loads(error.read().decode("utf-8"))
            finally:
                error.close()

    def post_json(self, path: str, payload: dict) -> tuple[int, dict]:
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

    def run_create_fetch_evaluate_fetch(
        self,
        *,
        create_payload: dict,
        evaluate_payload_builder: Callable[[dict], dict],
    ) -> RuntimeFlowResult:
        create_status, create_response = self.post_json("/tasks", create_payload)
        task_id = create_response["task_envelope"]["id"]
        initial_fetch_status, initial_fetch_response = self.get_json(f"/tasks/{task_id}")
        evaluate_payload = evaluate_payload_builder(initial_fetch_response["task"])
        evaluate_status, evaluate_response = self.post_json("/evaluate", evaluate_payload)
        final_fetch_status, final_fetch_response = self.get_json(f"/tasks/{task_id}")
        return RuntimeFlowResult(
            task_id=task_id,
            create_status=create_status,
            create_response=create_response,
            initial_fetch_status=initial_fetch_status,
            initial_fetch_response=initial_fetch_response,
            evaluate_status=evaluate_status,
            evaluate_payload=evaluate_payload,
            evaluate_response=evaluate_response,
            final_fetch_status=final_fetch_status,
            final_fetch_response=final_fetch_response,
        )

    def run_create_fetch_reevaluate_fetch(
        self,
        *,
        create_payload: dict,
        reevaluate_payload_builder: Callable[[dict], dict],
    ) -> RuntimeReevaluationFlowResult:
        create_status, create_response = self.post_json("/tasks", create_payload)
        task_id = create_response["task_envelope"]["id"]
        initial_fetch_status, initial_fetch_response = self.get_json(f"/tasks/{task_id}")
        reevaluate_payload = reevaluate_payload_builder(initial_fetch_response["task"])
        reevaluate_status, reevaluate_response = self.post_json(
            f"/tasks/{task_id}/reevaluate",
            reevaluate_payload,
        )
        final_fetch_status, final_fetch_response = self.get_json(f"/tasks/{task_id}")
        return RuntimeReevaluationFlowResult(
            task_id=task_id,
            create_status=create_status,
            create_response=create_response,
            initial_fetch_status=initial_fetch_status,
            initial_fetch_response=initial_fetch_response,
            reevaluate_status=reevaluate_status,
            reevaluate_payload=reevaluate_payload,
            reevaluate_response=reevaluate_response,
            final_fetch_status=final_fetch_status,
            final_fetch_response=final_fetch_response,
        )
