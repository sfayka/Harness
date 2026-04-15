from __future__ import annotations

import json
import unittest
from pathlib import Path


class HostedDeploymentContractTests(unittest.TestCase):
    def test_vercel_json_declares_web_and_api_services(self) -> None:
        payload = json.loads(Path("vercel.json").read_text(encoding="utf-8"))

        services = payload["experimentalServices"]
        self.assertEqual(services["web"]["entrypoint"], ".")
        self.assertEqual(services["web"]["framework"], "nextjs")
        self.assertEqual(services["web"]["routePrefix"], "/")
        self.assertEqual(services["api"]["entrypoint"], "backend/server.py")
        self.assertEqual(services["api"]["framework"], "fastapi")
        self.assertEqual(services["api"]["routePrefix"], "/backend")

    def test_env_example_documents_local_override_only(self) -> None:
        env_example = Path(".env.example").read_text(encoding="utf-8")

        self.assertIn("HARNESS_API_BASE_URL=http://127.0.0.1:8000", env_example)
        self.assertIn("Hosted Vercel deployments derive the backend route automatically", env_example)
        self.assertIn("POSTGRES_URL", env_example)
        self.assertIn("BLOB_READ_WRITE_TOKEN", env_example)

    def test_backend_requirements_are_declared_inline_for_vercel_python_builds(self) -> None:
        backend_requirements = Path("backend/requirements.txt").read_text(encoding="utf-8")

        self.assertNotIn("-r ../requirements.txt", backend_requirements)
        self.assertIn("fastapi==0.115.12", backend_requirements)
