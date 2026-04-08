from __future__ import annotations

import tempfile
import threading
import unittest

from modules.api import run_server
from modules.connectors.ingress_request_builder import (
    IngressRequestBuilderError,
    IngressSourceContext,
    IngressTaskIntent,
    build_task_reevaluation_payload,
    build_task_submission_payload,
)


class IngressRequestBuilderTests(unittest.TestCase):
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

    def _context(self) -> IngressSourceContext:
        return IngressSourceContext(
            source_system="openclaw",
            source_id="msg-ingress-1",
            ingress_name="OpenClaw",
            ingress_id="conv-ingress-1",
            requested_by="operator@example.com",
            extension_namespace="openclaw",
            extension_payload={
                "conversation_id": "conv-ingress-1",
                "message_id": "msg-ingress-1",
                "channel": "cli",
            },
        )

    def _intent(self) -> IngressTaskIntent:
        return IngressTaskIntent(
            task_id="task-ingress-builder-1",
            title="Ingress builder task",
            description="Construct a canonical Harness submission payload from higher-level ingress inputs.",
            acceptance_criteria=(
                "The task submission payload validates at the Harness API boundary.",
                "The source metadata remains auditable.",
            ),
            objective_summary="Reduce ingress-side task submission friction.",
        )

    def _post_json(self, path: str, payload: dict) -> tuple[int, dict]:
        from json import dumps, loads
        from urllib.error import HTTPError
        from urllib.request import Request, urlopen

        request = Request(
            self.base_url + path,
            data=dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request) as response:
                return response.status, loads(response.read().decode("utf-8"))
        except HTTPError as error:
            try:
                return error.code, loads(error.read().decode("utf-8"))
            finally:
                error.close()

    def test_builds_valid_new_task_submission_payload(self) -> None:
        payload = build_task_submission_payload(intent=self._intent(), context=self._context())

        task = payload["request"]["task_envelope"]
        self.assertEqual(task["origin"]["source_system"], "openclaw")
        self.assertEqual(task["extensions"]["openclaw"]["conversation_id"], "conv-ingress-1")

        status, response = self._post_json("/tasks", payload)
        self.assertEqual(status, 200)
        self.assertEqual(response["task_envelope"]["id"], "task-ingress-builder-1")

    def test_builds_valid_reevaluation_payload(self) -> None:
        payload = build_task_reevaluation_payload(
            external_facts={"linear_facts": {"record_found": False, "reasons": ["awaiting sync"]}},
            new_artifacts=(
                {
                    "id": "artifact-ingress-review-note-1",
                    "type": "review_note",
                    "title": "Ingress review note",
                    "description": "The ingress client supplied a manual review note.",
                    "location": None,
                    "content_type": "text/plain",
                    "external_id": None,
                    "commit_sha": None,
                    "pull_request_number": None,
                    "review_state": None,
                    "provenance": {
                        "source_system": "harness",
                        "source_type": "manual_review",
                        "source_id": "review/ingress-builder-note-1",
                        "captured_by": "operator",
                    },
                    "verification_status": "verified",
                    "repository": None,
                    "branch": None,
                    "changed_files": [],
                    "external_refs": [],
                    "captured_at": "2026-03-25T18:00:00Z",
                    "metadata": {},
                },
            ),
            claimed_completion=True,
            acceptance_criteria_satisfied=True,
        )

        self.assertEqual(payload["request"]["new_artifacts"][0]["type"], "review_note")
        self.assertTrue(payload["request"]["claimed_completion"])

    def test_rejects_untrusted_verified_artifacts(self) -> None:
        with self.assertRaises(IngressRequestBuilderError):
            build_task_reevaluation_payload(
                new_artifacts=(
                    {
                        "id": "artifact-ingress-review-note-untrusted-1",
                        "type": "review_note",
                        "title": "Untrusted note",
                        "description": "A caller tried to self-certify support evidence.",
                        "location": None,
                        "content_type": "text/plain",
                        "external_id": None,
                        "commit_sha": None,
                        "pull_request_number": None,
                        "review_state": None,
                        "provenance": {
                            "source_system": "openclaw",
                            "source_type": "manual",
                            "source_id": "msg-untrusted-review-note-1",
                            "captured_by": "ingress-builder-test",
                        },
                        "verification_status": "verified",
                        "repository": None,
                        "branch": None,
                        "changed_files": [],
                        "external_refs": [],
                        "captured_at": "2026-03-25T18:10:00Z",
                        "metadata": {},
                    },
                ),
                claimed_completion=True,
                acceptance_criteria_satisfied=True,
            )

    def test_rejects_completion_truth_on_initial_submission(self) -> None:
        with self.assertRaises(IngressRequestBuilderError):
            build_task_submission_payload(
                intent=self._intent(),
                context=self._context(),
                claimed_completion=True,
            )

        with self.assertRaises(IngressRequestBuilderError):
            build_task_submission_payload(
                intent=self._intent(),
                context=self._context(),
                runtime_facts={"executor_reported_success": True},
            )

        with self.assertRaises(IngressRequestBuilderError):
            build_task_submission_payload(
                intent=IngressTaskIntent(
                    **{
                        **self._intent().__dict__,
                        "linked_artifacts": (
                            {
                                "id": "artifact-pr-1",
                                "type": "pull_request",
                            },
                        ),
                    }
                ),
                context=self._context(),
            )

        with self.assertRaises(IngressRequestBuilderError):
            build_task_submission_payload(
                intent=IngressTaskIntent(
                    **{
                        **self._intent().__dict__,
                        "completion_evidence": {"status": "deferred"},
                    }
                ),
                context=self._context(),
            )

        with self.assertRaises(IngressRequestBuilderError):
            build_task_submission_payload(
                intent=IngressTaskIntent(
                    **{
                        **self._intent().__dict__,
                        "linked_artifacts": (
                            {
                                "id": "artifact-ingress-initial-review-note-1",
                                "type": "review_note",
                                "title": "Initial review note",
                                "description": "A caller tried to seed verified support proof on a new task.",
                                "location": None,
                                "content_type": "text/plain",
                                "external_id": None,
                                "commit_sha": None,
                                "pull_request_number": None,
                                "review_state": None,
                                "provenance": {
                                    "source_system": "harness",
                                    "source_type": "manual_review",
                                    "source_id": "review/ingress-initial-note-1",
                                    "captured_by": "operator",
                                },
                                "verification_status": "verified",
                                "repository": None,
                                "branch": None,
                                "changed_files": [],
                                "external_refs": [],
                                "captured_at": "2026-03-25T18:20:00Z",
                                "metadata": {},
                            },
                        ),
                    }
                ),
                context=self._context(),
            )

    def test_rejects_pre_satisfied_completion_evidence_without_claimed_completion(self) -> None:
        with self.assertRaises(IngressRequestBuilderError):
            build_task_reevaluation_payload(
                completion_evidence={
                    "status": "satisfied",
                    "validated_artifact_ids": ["artifact-1"],
                },
                claimed_completion=False,
            )

    def test_rejects_execution_artifacts_on_generic_reevaluation(self) -> None:
        with self.assertRaises(IngressRequestBuilderError):
            build_task_reevaluation_payload(
                new_artifacts=(
                    {
                        "id": "artifact-pr-1",
                        "type": "pull_request",
                    },
                ),
                claimed_completion=True,
                runtime_facts={"executor_reported_success": True},
            )

    def test_rejects_missing_required_upstream_inputs(self) -> None:
        with self.assertRaises(IngressRequestBuilderError):
            build_task_submission_payload(
                intent=IngressTaskIntent(
                    task_id="task-ingress-invalid-1",
                    title="",
                    description="Missing title should fail fast.",
                    acceptance_criteria=("A criterion exists.",),
                ),
                context=self._context(),
            )

        with self.assertRaises(IngressRequestBuilderError):
            build_task_submission_payload(
                intent=IngressTaskIntent(
                    task_id="task-ingress-invalid-2",
                    title="No criteria",
                    description="Missing criteria should fail fast.",
                    acceptance_criteria=(),
                ),
                context=self._context(),
            )

    def test_preserves_openclaw_extension_metadata_without_runtime_coupling(self) -> None:
        payload = build_task_submission_payload(intent=self._intent(), context=self._context())

        task = payload["request"]["task_envelope"]
        self.assertEqual(task["extensions"]["openclaw"]["channel"], "cli")
        self.assertEqual(task["origin"]["ingress_name"], "OpenClaw")
        self.assertEqual(task["origin"]["source_type"], "ingress_request")


if __name__ == "__main__":
    unittest.main()
