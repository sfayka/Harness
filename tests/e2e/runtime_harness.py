from __future__ import annotations

import json
import tempfile
import threading
import unittest
from copy import deepcopy
from dataclasses import dataclass
from typing import Callable
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from modules.api import run_server


_CODE_EXECUTION_ARTIFACT_TYPES = frozenset({"branch", "commit", "pull_request", "changed_file"})


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


@dataclass(frozen=True)
class RuntimeTaskSnapshot:
    task_fetch_status: int
    task_fetch_response: dict
    read_model_status: int
    read_model_response: dict
    timeline_status: int
    timeline_response: dict
    history_status: int
    history_response: dict


@dataclass(frozen=True)
class RuntimeTaskStepResult:
    action: str
    status: int
    response: dict
    snapshot: RuntimeTaskSnapshot

    @property
    def task(self) -> dict:
        return self.snapshot.task_fetch_response["task"]

    @property
    def read_model(self) -> dict:
        return self.snapshot.read_model_response

    @property
    def timeline(self) -> dict:
        return self.snapshot.timeline_response

    @property
    def history(self) -> dict:
        return self.snapshot.history_response


class RuntimeTaskScenario:
    def __init__(self, case: "RuntimeApiTestCase", *, task_id: str, created: RuntimeTaskStepResult) -> None:
        self.case = case
        self.task_id = task_id
        self.created = created
        self.last_step = created

    def refresh(self) -> RuntimeTaskSnapshot:
        snapshot = self.case.snapshot_task(self.task_id)
        return snapshot

    def mutate_task(self, mutator: Callable[[dict], None]) -> RuntimeTaskSnapshot:
        store = self.case.server.RequestHandlerClass.service.store
        task = deepcopy(store.get_task(self.task_id))
        mutator(task)
        store.update_task(task)
        return self.refresh()

    def reevaluate(self, payload: dict) -> RuntimeTaskStepResult:
        result = self.case.post_task_action(self.task_id, "reevaluate", payload)
        self.last_step = result
        return result

    def dispatch(self, payload: dict) -> RuntimeTaskStepResult:
        result = self.case.post_task_action(self.task_id, "dispatch", payload)
        self.last_step = result
        return result

    def completion_claim(self, payload: dict) -> RuntimeTaskStepResult:
        result = self.case.post_task_action(self.task_id, "completion-claims", payload)
        self.last_step = result
        return result


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

    @property
    def service(self):
        return self.server.RequestHandlerClass.service

    def set_reconciliation_registry(self, registry) -> None:
        self.service.reconciliation_registry = registry

    def get_json(self, path: str) -> tuple[int, dict]:
        try:
            with urlopen(self.base_url + path) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            try:
                return error.code, json.loads(error.read().decode("utf-8"))
            finally:
                error.close()

    def list_tasks(self) -> tuple[int, dict]:
        return self.get_json("/tasks")

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

    def snapshot_task(self, task_id: str) -> RuntimeTaskSnapshot:
        task_fetch_status, task_fetch_response = self.get_json(f"/tasks/{task_id}")
        read_model_status, read_model_response = self.get_json(f"/tasks/{task_id}/read-model")
        timeline_status, timeline_response = self.get_json(f"/tasks/{task_id}/timeline")
        history_status, history_response = self.get_json(f"/tasks/{task_id}/evaluations")
        return RuntimeTaskSnapshot(
            task_fetch_status=task_fetch_status,
            task_fetch_response=task_fetch_response,
            read_model_status=read_model_status,
            read_model_response=read_model_response,
            timeline_status=timeline_status,
            timeline_response=timeline_response,
            history_status=history_status,
            history_response=history_response,
        )

    def create_task_scenario(self, payload: dict) -> RuntimeTaskScenario:
        status, response = self.post_json("/tasks", payload)
        task_id = response["task_envelope"]["id"]
        created = RuntimeTaskStepResult(
            action="create_task",
            status=status,
            response=response,
            snapshot=self.snapshot_task(task_id),
        )
        return RuntimeTaskScenario(self, task_id=task_id, created=created)

    def create_manual_ingress_scenario(self, payload: dict) -> RuntimeTaskScenario:
        status, response = self.post_json("/ingress/manual", payload)
        task_id = response["task_envelope"]["id"]
        created = RuntimeTaskStepResult(
            action="manual_ingress",
            status=status,
            response=response,
            snapshot=self.snapshot_task(task_id),
        )
        return RuntimeTaskScenario(self, task_id=task_id, created=created)

    def create_evaluate_scenario(self, payload: dict) -> RuntimeTaskScenario:
        status, response = self.post_json("/evaluate", payload)
        task_id = response["task_envelope"]["id"]
        created = RuntimeTaskStepResult(
            action="evaluate_new_task",
            status=status,
            response=response,
            snapshot=self.snapshot_task(task_id),
        )
        return RuntimeTaskScenario(self, task_id=task_id, created=created)

    def post_task_action(self, task_id: str, action: str, payload: dict) -> RuntimeTaskStepResult:
        status, response = self.post_json(f"/tasks/{task_id}/{action}", payload)
        return RuntimeTaskStepResult(
            action=action,
            status=status,
            response=response,
            snapshot=self.snapshot_task(task_id),
        )

    def _canonicalize_existing_task_update_payload(self, payload: dict) -> dict:
        request = deepcopy(payload["request"])
        request.pop("task_envelope", None)
        request.pop("task_status", None)
        request.pop("assigned_executor", None)
        linked_artifacts = request.pop("linked_artifacts", None)
        if linked_artifacts is not None:
            request["new_artifacts"] = linked_artifacts
        if self._request_uses_execution_artifacts({"request": request}):
            request.pop("runtime_facts", None)
        return {"request": request}

    def _request_uses_execution_artifacts(self, payload: dict) -> bool:
        request = payload.get("request") if isinstance(payload, dict) else None
        if not isinstance(request, dict):
            return False
        new_artifacts = request.get("new_artifacts")
        if not isinstance(new_artifacts, list):
            return False
        for artifact in new_artifacts:
            if not isinstance(artifact, dict):
                continue
            artifact_type = str(artifact.get("type") or "").strip()
            if artifact_type in _CODE_EXECUTION_ARTIFACT_TYPES:
                return True
        return False

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
        reevaluation_payload = self._canonicalize_existing_task_update_payload(evaluate_payload)
        evaluate_status, evaluate_response = self.post_json(
            f"/tasks/{task_id}/reevaluate",
            reevaluation_payload,
        )
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
        if self._request_uses_execution_artifacts(reevaluate_payload):
            reevaluate_payload = deepcopy(reevaluate_payload)
            request = reevaluate_payload.get("request")
            if isinstance(request, dict):
                request.pop("runtime_facts", None)
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
