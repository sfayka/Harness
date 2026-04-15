from __future__ import annotations

import tempfile
import unittest
from copy import deepcopy

from fastapi.testclient import TestClient

from backend.server import create_app
from modules.store import FileBackedHarnessStore
from tests.test_api import _manual_happy_path_overlay_payload


class FastApiBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = FileBackedHarnessStore(self.temp_dir.name)
        self.client = TestClient(create_app(store=self.store))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_health_route_returns_canonical_health_payload(self) -> None:
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertIn("store_backend", response.json())

    def test_submit_and_read_model_round_trip_through_fastapi_adapter(self) -> None:
        created = self.client.post(
            "/tasks",
            json={"request": {"task_envelope": deepcopy(_manual_happy_path_overlay_payload()["request"]["task_envelope"])}},
        )
        self.assertEqual(created.status_code, 200)

        task_id = created.json()["task_envelope"]["id"]

        read_model = self.client.get(f"/tasks/{task_id}/read-model")
        self.assertEqual(read_model.status_code, 200)
        self.assertEqual(read_model.json()["task"]["task_id"], task_id)
