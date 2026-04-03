from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from enum import Enum
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from modules.api import HarnessApiService, build_parser, evaluate_http_payload, run_server
from modules.contracts.task_envelope_review import (
    ReviewOutcome,
    ReviewRequest,
    ReviewTrigger,
    ReviewerIdentity,
    resolve_review_request,
)
from modules.demo_cases import build_demo_request
from modules.intake import create_task_envelope
from modules.store import FileBackedHarnessStore, PostgresHarnessStore


POSTGRES_TEST_DATABASE_URL = os.environ.get("HARNESS_TEST_DATABASE_URL")


class _FakeCursor:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows
        self._index = 0

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def execute(self, query: str, params: tuple[object, ...]) -> None:
        del query, params

    def fetchone(self) -> tuple[object, ...] | None:
        if self._index >= len(self._rows):
            return None
        row = self._rows[self._index]
        self._index += 1
        return row


class _FakeConnection:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(list(self._rows))


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


def _manual_happy_path_overlay_payload() -> dict:
    task_envelope = create_task_envelope(
        {
            "id": "task-http-happy-overlay-1",
            "title": "Dry-run happy path overlay",
            "description": "Exercise /evaluate with top-level evidence overlays.",
            "origin": {
                "source_system": "openclaw",
                "source_type": "ingress_request",
                "source_id": "req-happy-overlay-1",
            },
            "acceptance_criteria": [
                {
                    "id": "ac-1",
                    "description": "Harness accepts a fully reconciled, evidence-backed completion claim.",
                    "required": True,
                }
            ],
        },
        now="2026-03-31T14:30:00Z",
    )

    return {
        "request": {
            "task_envelope": task_envelope,
            "task_status": "executing",
            "assigned_executor": {
                "executor_type": "codex",
                "executor_id": "executor-e2e-1",
                "assignment_reason": "Manual dry-run overlay payload.",
            },
            "linked_artifacts": [
                {
                    "id": "artifact-pr-dryrun-1",
                    "type": "pull_request",
                    "title": "HARNESS-DRYRUN PR",
                    "description": None,
                    "location": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/pull/2",
                    "content_type": None,
                    "external_id": "PR-2",
                    "commit_sha": None,
                    "pull_request_number": 2,
                    "review_state": "approved",
                    "provenance": {
                        "source_system": "github",
                        "source_type": "api",
                        "source_id": "pull/2",
                        "captured_by": "github-sync",
                    },
                    "verification_status": "verified",
                    "repository": {
                        "host": "github.com",
                        "owner": "KnoxAnalytics",
                        "name": "HARNESS-DRYRUN",
                        "external_id": "repo-dryrun-1",
                    },
                    "branch": {
                        "name": "codex/e2e-test",
                        "base_branch": "main",
                        "head_commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                    },
                    "changed_files": [],
                    "external_refs": [],
                    "captured_at": "2026-03-31T14:31:00Z",
                    "metadata": {},
                },
                {
                    "id": "artifact-commit-dryrun-1",
                    "type": "commit",
                    "title": None,
                    "description": None,
                    "location": "https://github.com/KnoxAnalytics/HARNESS-DRYRUN/commit/8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                    "content_type": None,
                    "external_id": "commit-8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                    "commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                    "pull_request_number": None,
                    "review_state": None,
                    "provenance": {
                        "source_system": "github",
                        "source_type": "api",
                        "source_id": "commit/8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                        "captured_by": "github-sync",
                    },
                    "verification_status": "verified",
                    "repository": {
                        "host": "github.com",
                        "owner": "KnoxAnalytics",
                        "name": "HARNESS-DRYRUN",
                        "external_id": "repo-dryrun-1",
                    },
                    "branch": None,
                    "changed_files": [],
                    "external_refs": [],
                    "captured_at": "2026-03-31T14:31:10Z",
                    "metadata": {},
                },
            ],
            "completion_evidence": {
                "policy": "required",
                "status": "satisfied",
                "required_artifact_types": ["pull_request", "commit"],
                "validated_artifact_ids": ["artifact-pr-dryrun-1", "artifact-commit-dryrun-1"],
                "validation_method": "external_reconciliation",
                "validated_at": "2026-03-31T14:31:30Z",
                "validator": {
                    "source_system": "harness",
                    "source_type": "verification",
                    "source_id": "verification-dryrun-1",
                    "captured_by": "github-sync",
                },
            },
            "external_facts": {
                "expected_code_context": {
                    "repository_host": "github.com",
                    "repository_owner": "KnoxAnalytics",
                    "repository_name": "HARNESS-DRYRUN",
                    "branch_name": "codex/e2e-test",
                    "base_branch": "main",
                },
                "github_facts": {
                    "artifact_found": True,
                    "repository": {
                        "host": "github.com",
                        "owner": "KnoxAnalytics",
                        "name": "HARNESS-DRYRUN",
                        "external_id": "repo-dryrun-1",
                    },
                    "branch": {
                        "name": "codex/e2e-test",
                        "base_branch": "main",
                        "head_commit_sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                    },
                    "commit": {
                        "sha": "8a32c6f29d34bbdb80b5ec0b5a97415f8e66e705",
                    },
                    "pull_request": {
                        "number": 2,
                        "review_state": "approved",
                    },
                    "changed_files": {
                        "matches_expected_scope": True,
                        "files": [
                            {
                                "path": "modules/api.py",
                                "change_type": "modified",
                            }
                        ],
                    },
                    "reasons": [],
                },
                "linear_facts": {
                    "record_found": True,
                    "issue_id": "lin-dryrun-1",
                    "issue_key": "HAR-2",
                    "state": "completed",
                    "workflow": {
                        "workflow_id": "workflow-completed",
                        "workflow_name": "completed",
                        "state_type": "completed",
                    },
                    "reasons": [],
                },
            },
            "claimed_completion": True,
            "acceptance_criteria_satisfied": True,
            "runtime_facts": {
                "executor_reported_success": True,
                "attempt_count": 1,
            },
        }
    }


def _completion_claim_payload(*, claim_id: str = "claim-1") -> dict:
    return {
        "completion_claim": {
            "claim_id": claim_id,
            "reported_at": "2026-04-01T08:00:00Z",
            "reported_by": "stub-executor",
            "reason": "executor reported completion",
            "metadata": {"attempt_id": "attempt-1"},
        }
    }


def _execution_attempt_payload(*, attempt_id: str = "attempt-1") -> dict:
    return {
        "execution_attempt": {
            "attempt_id": attempt_id,
            "recorded_at": "2026-04-01T08:00:05Z",
            "status": "succeeded",
            "reported_by": "stub-executor",
            "artifact_references": [
                {
                    "reference_id": f"{attempt_id}:log",
                    "artifact_type": "execution_log",
                    "location": "stub://attempts/log",
                }
            ],
            "metadata": {"executor_run_id": f"stub-run-{attempt_id}"},
        }
    }


def _schema_invalid_submission_payload() -> dict:
    payload = _request_payload("accepted_completion")
    completion_evidence = payload["request"]["task_envelope"]["artifacts"]["completion_evidence"]
    del completion_evidence["validated_at"]
    del completion_evidence["validation_method"]
    del completion_evidence["validator"]
    return payload


def _linear_ingress_payload(case_name: str, *, task_id: str | None = None) -> dict:
    canonical_request = _request_payload(case_name)["request"]
    task = deepcopy(canonical_request["task_envelope"])
    external_facts = deepcopy(canonical_request.get("external_facts") or {})

    payload = {
        "issue": {
            "id": f"lin-{task['id']}",
            "identifier": f"HAR-{task['id']}",
            "title": task["title"],
            "description": task["description"],
        },
        "state": {
            "id": "workflow_in_progress" if case_name == "accepted_completion" else "workflow_completed",
            "name": "in_progress" if case_name == "accepted_completion" else "completed",
            "type": "started" if case_name == "accepted_completion" else "completed",
        },
        "project": {
            "id": "project-harness",
            "name": "Harness",
        },
        "task_reference": {
            "harness_task_id": task_id or task["id"],
            "external_ref": f"HAR-{task['id']}",
        },
        "labels": ["linear", "ingress"],
        "priority": task.get("priority", "normal"),
        "task_status": task["status"],
        "acceptance_criteria": deepcopy(task["acceptance_criteria"]),
        "linked_artifacts": deepcopy(task["artifacts"]["items"]),
        "completion_evidence": deepcopy(task["artifacts"]["completion_evidence"]),
        "external_facts": {},
        "claimed_completion": canonical_request.get("claimed_completion", False),
        "acceptance_criteria_satisfied": canonical_request.get("acceptance_criteria_satisfied", False),
        "runtime_facts": _to_jsonable(canonical_request.get("runtime_facts") or {}),
    }

    if task.get("assigned_executor") is not None:
        payload["assigned_executor"] = deepcopy(task["assigned_executor"])

    if external_facts.get("expected_code_context") is not None:
        payload["external_facts"]["expected_code_context"] = deepcopy(external_facts["expected_code_context"])
    if external_facts.get("github_facts") is not None:
        payload["external_facts"]["github_facts"] = deepcopy(external_facts["github_facts"])

    if case_name == "review_required":
        payload["state"] = {
            "id": "workflow_in_progress",
            "name": "in_progress",
            "type": "started",
        }

    return payload




def _manual_ingress_payload(*, task_id: str | None = None) -> dict:
    payload: dict[str, object] = {
        "task": {
            "title": "Manual canonical ingestion task",
            "description": "Create and persist a manual task through canonical submission.",
            "requested_by": "operator@example.com",
            "ingress_name": "Manual",
            "ingress_id": "KNO-162",
            "acceptance_criteria": [
                {
                    "id": "ac-1",
                    "description": "Task is persisted and queryable via canonical inspection surfaces.",
                    "required": True,
                }
            ],
        },
        "metadata": {"mode": "manual"},
    }
    if task_id is not None:
        payload["task_id"] = task_id
    return payload


def _openclaw_ingress_payload(*, task_id: str | None = None) -> dict:
    payload: dict[str, object] = {
        "context": {
            "conversation_id": "conv-kno-164",
            "message_id": "msg-kno-164-1",
            "channel": "cli",
            "workspace_id": "workspace-harness",
            "user_id": "operator@example.com",
            "agent_id": "openclaw-assistant",
        },
        "task": {
            "title": "OpenClaw canonical ingress task",
            "description": "Create a task through OpenClaw ingress that is persisted by canonical submission.",
            "acceptance_criteria": [
                "Task is persisted in Harness store.",
                "OpenClaw provenance is visible in canonical read surfaces.",
            ],
            "constraints": ["Keep OpenClaw request shape non-canonical."],
            "priority": "high",
        },
        "metadata": {"request_kind": "openclaw"},
        "runtime_facts": {"attempt_count": 1},
        "claimed_completion": False,
        "acceptance_criteria_satisfied": False,
    }
    if task_id is not None:
        payload["task_id"] = task_id
    return payload

def _review_note_artifact(artifact_id: str = "artifact-review-note-1") -> dict:
    return {
        "id": artifact_id,
        "type": "review_note",
        "title": "Manual evidence note",
        "description": "Evidence was manually confirmed during reevaluation.",
        "location": None,
        "content_type": "text/plain",
        "external_id": None,
        "commit_sha": None,
        "pull_request_number": None,
        "review_state": None,
        "provenance": {
            "source_system": "harness",
            "source_type": "manual_review",
            "source_id": f"review/{artifact_id}",
            "captured_by": "operator",
        },
        "verification_status": "verified",
        "repository": None,
        "branch": None,
        "changed_files": [],
        "external_refs": [],
        "captured_at": "2026-03-24T17:10:00Z",
        "metadata": {},
    }


def _progress_artifact(artifact_id: str = "artifact-progress-1") -> dict:
    return {
        "id": artifact_id,
        "type": "progress_artifact",
        "title": "Progress snapshot",
        "description": "Progress carried across reevaluations.",
        "location": None,
        "content_type": "application/json",
        "external_id": None,
        "commit_sha": None,
        "pull_request_number": None,
        "review_state": None,
        "provenance": {
            "source_system": "codex",
            "source_type": "executor_report",
            "source_id": f"progress/{artifact_id}",
            "captured_by": "harness-api",
        },
        "verification_status": "informational",
        "repository": None,
        "branch": None,
        "changed_files": [],
        "external_refs": [],
        "captured_at": "2026-03-24T17:15:00Z",
        "metadata": {
            "completed_items": "2",
            "remaining_items": "1",
        },
    }


def _handoff_artifact(artifact_id: str = "artifact-handoff-1") -> dict:
    return {
        "id": artifact_id,
        "type": "handoff_artifact",
        "title": "Session handoff",
        "description": "Resume from external reconciliation on the next session.",
        "location": None,
        "content_type": "application/json",
        "external_id": None,
        "commit_sha": None,
        "pull_request_number": None,
        "review_state": None,
        "provenance": {
            "source_system": "codex",
            "source_type": "executor_report",
            "source_id": f"handoff/{artifact_id}",
            "captured_by": "harness-api",
        },
        "verification_status": "informational",
        "repository": None,
        "branch": None,
        "changed_files": [],
        "external_refs": [],
        "captured_at": "2026-03-24T17:20:00Z",
        "metadata": {
            "from_session_id": "session-1",
            "resume_hint": "Continue verification after the next sync.",
        },
    }


def _review_decision_payload(task_id: str) -> dict:
    review_request = ReviewRequest(
        review_request_id="review-request-api-1",
        task_id=task_id,
        requested_at="2026-03-24T17:30:00Z",
        requested_by="verification",
        trigger=ReviewTrigger.VERIFICATION,
        summary="Manual confirmation is required before completion can be accepted.",
        presented_sections=("task_state", "evidence", "reconciliation"),
        allowed_outcomes=(ReviewOutcome.ACCEPT_COMPLETION,),
    )
    review_decision = resolve_review_request(
        review_request,
        review_id="review-api-1",
        reviewer=ReviewerIdentity(
            reviewer_id="operator-1",
            reviewer_name="Casey Reviewer",
            authority_role="operator",
        ),
        outcome=ReviewOutcome.ACCEPT_COMPLETION,
        reasoning="Additional evidence and manual review resolve the remaining uncertainty.",
    )
    return _to_jsonable(review_decision)


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

    def test_rejects_schema_invalid_payload(self) -> None:
        status, payload = evaluate_http_payload(_schema_invalid_submission_payload())

        self.assertEqual(status, 400)
        self.assertTrue(payload["invalid_input"])
        self.assertIn("Invalid TaskEnvelope:", payload["error"])


class HarnessApiCliTests(unittest.TestCase):
    def test_parser_defaults_to_render_safe_host_and_port(self) -> None:
        original_port = os.environ.pop("PORT", None)
        self.addCleanup(lambda: os.environ.__setitem__("PORT", original_port) if original_port is not None else os.environ.pop("PORT", None))

        args = build_parser().parse_args([])

        self.assertEqual(args.host, "0.0.0.0")
        self.assertEqual(args.port, 8000)

    def test_parser_uses_port_environment_variable_when_present(self) -> None:
        original_port = os.environ.get("PORT")
        os.environ["PORT"] = "10000"
        self.addCleanup(lambda: os.environ.__setitem__("PORT", original_port) if original_port is not None else os.environ.pop("PORT", None))

        args = build_parser().parse_args([])

        self.assertEqual(args.host, "0.0.0.0")
        self.assertEqual(args.port, 10000)

    def test_service_defaults_to_file_store_backend(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)

        with patch.dict(
            os.environ,
            {"HARNESS_STORE_BACKEND": "file", "HARNESS_STORE_ROOT": temp_dir.name},
            clear=False,
        ):
            service = HarnessApiService()

        self.assertIsInstance(service.store, FileBackedHarnessStore)

    @unittest.skipUnless(POSTGRES_TEST_DATABASE_URL, "HARNESS_TEST_DATABASE_URL is required for Postgres startup selection test")
    def test_service_uses_postgres_store_backend_from_environment(self) -> None:
        with patch.dict(
            os.environ,
            {
                "HARNESS_STORE_BACKEND": "postgres",
                "DATABASE_URL": POSTGRES_TEST_DATABASE_URL or "",
            },
            clear=False,
        ):
            service = HarnessApiService()

        self.assertIsInstance(service.store, PostgresHarnessStore)

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

    def test_service_lists_dashboard_tasks_from_read_model_surface(self) -> None:
        self.service.submit(_request_payload("accepted_completion"))
        self.service.submit(_request_payload("blocked_insufficient_evidence"))

        status, payload = self.service.list_tasks()

        self.assertEqual(status, 200)
        self.assertEqual(len(payload["tasks"]), 2)
        self.assertIn("verification_summary", payload["tasks"][0])
        self.assertIn("timeline", payload["tasks"][0])

    def test_service_submit_persists_new_task_and_initial_evaluation(self) -> None:
        status, payload = self.service.submit(_request_payload("accepted_completion"))

        task_status, task_payload = self.service.get_task(payload["task_envelope"]["id"])
        history_status, history_payload = self.service.get_evaluation_history(payload["task_envelope"]["id"])

        self.assertEqual(status, 200)
        self.assertEqual(payload["task_envelope"]["status"], "completed")
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["status"], "completed")
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 1)

    def test_service_submit_rejects_duplicate_task_id(self) -> None:
        initial_status, initial_payload = self.service.submit(_request_payload("accepted_completion"))
        duplicate_status, duplicate_payload = self.service.submit(_request_payload("accepted_completion"))
        history_status, history_payload = self.service.get_evaluation_history(initial_payload["task_envelope"]["id"])

        self.assertEqual(initial_status, 200)
        self.assertEqual(duplicate_status, 409)
        self.assertTrue(duplicate_payload["duplicate_task_id"])
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 1)

    def test_service_submit_rejects_missing_task_id_without_crashing(self) -> None:
        status, payload = self.service.submit({"request": {"task_envelope": {"title": "Missing id"}}})

        self.assertEqual(status, 400)
        self.assertTrue(payload["invalid_input"])
        self.assertIn("task_envelope.id is required", payload["error"])

    def test_service_submit_rejects_schema_invalid_task_envelope_without_crashing(self) -> None:
        status, payload = self.service.submit(_schema_invalid_submission_payload())

        self.assertEqual(status, 400)
        self.assertTrue(payload["invalid_input"])
        self.assertIn("Invalid TaskEnvelope:", payload["error"])

    def test_service_can_submit_linear_ingress_payload_via_canonical_submission_path(self) -> None:
        status, payload = self.service.submit_linear_ingress(_linear_ingress_payload("accepted_completion"))

        task_status, task_payload = self.service.get_task(payload["task_envelope"]["id"])
        history_status, history_payload = self.service.get_evaluation_history(payload["task_envelope"]["id"])

        self.assertEqual(status, 200)
        self.assertEqual(payload["task_envelope"]["origin"]["source_system"], "linear")
        self.assertEqual(payload["task_envelope"]["status"], "completed")
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["extensions"]["linear"]["issue_id"], f"lin-{payload['task_envelope']['id']}")
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 1)


    def test_service_can_submit_manual_ingress_payload_and_expose_canonical_read_surfaces(self) -> None:
        status, payload = self.service.submit_manual_ingress(_manual_ingress_payload())

        task_id = payload["task_envelope"]["id"]
        list_status, list_payload = self.service.list_tasks()
        read_status, read_payload = self.service.get_task_read_model(task_id)
        timeline_status, timeline_payload = self.service.get_task_timeline(task_id)
        history_status, history_payload = self.service.get_evaluation_history(task_id)

        self.assertEqual(status, 200)
        self.assertTrue(task_id)
        self.assertEqual(payload["task_envelope"]["origin"]["source_system"], "manual")
        self.assertEqual(list_status, 200)
        self.assertEqual(list_payload["tasks"][0]["task_id"], task_id)
        self.assertEqual(read_status, 200)
        self.assertEqual(read_payload["task"]["task_id"], task_id)
        self.assertEqual(timeline_status, 200)
        self.assertEqual(timeline_payload["task_id"], task_id)
        self.assertGreaterEqual(timeline_payload["event_count"], 1)
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 1)

    def test_service_can_submit_openclaw_ingress_payload_and_persist_openclaw_provenance(self) -> None:
        status, payload = self.service.submit_openclaw_ingress(_openclaw_ingress_payload())

        task_id = payload["task_envelope"]["id"]
        read_status, read_payload = self.service.get_task_read_model(task_id)
        history_status, history_payload = self.service.get_evaluation_history(task_id)

        self.assertEqual(status, 200)
        self.assertEqual(payload["task_envelope"]["origin"]["source_system"], "openclaw")
        self.assertEqual(payload["task_envelope"]["origin"]["source_id"], "msg-kno-164-1")
        self.assertEqual(payload["task_envelope"]["extensions"]["openclaw"]["conversation_id"], "conv-kno-164")
        self.assertEqual(read_status, 200)
        self.assertEqual(read_payload["task"]["extensions"]["openclaw"]["metadata"]["request_kind"], "openclaw")
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 1)

    def test_service_can_reevaluate_existing_blocked_task_to_completed(self) -> None:
        initial_payload = _request_payload("blocked_insufficient_evidence")
        initial_status, initial_response = self.service.evaluate(initial_payload)

        reevaluation_payload = {
            "request": {
                "new_artifacts": [_review_note_artifact()],
                "completion_evidence": {
                    "validated_artifact_ids": [
                        "artifact-pr-1",
                        "artifact-commit-1",
                        "artifact-review-note-1",
                    ]
                },
                "external_facts": deepcopy(_request_payload("accepted_completion")["request"]["external_facts"]),
                "claimed_completion": True,
                "acceptance_criteria_satisfied": True,
                "runtime_facts": deepcopy(initial_payload["request"]["runtime_facts"]),
            }
        }
        reevaluation_status, reevaluation_response = self.service.reevaluate(
            initial_response["task_envelope"]["id"],
            reevaluation_payload,
        )

        self.assertEqual(initial_status, 200)
        self.assertEqual(initial_response["task_envelope"]["status"], "blocked")
        self.assertEqual(reevaluation_status, 200)
        self.assertEqual(reevaluation_response["task_envelope"]["status"], "completed")
        self.assertEqual(reevaluation_response["action"], "transition_applied")

    def test_service_evaluate_existing_task_reapplies_top_level_overlays(self) -> None:
        payload = _manual_happy_path_overlay_payload()
        submit_payload = {"request": {"task_envelope": deepcopy(payload["request"]["task_envelope"])}}

        submit_status, submit_response = self.service.submit(submit_payload)
        evaluate_status, evaluate_response = self.service.evaluate(payload)

        self.assertEqual(submit_status, 200)
        self.assertEqual(submit_response["task_envelope"]["status"], "intake_ready")
        self.assertEqual(evaluate_status, 200)
        self.assertEqual(evaluate_response["action"], "transition_applied")
        self.assertTrue(evaluate_response["accepted_completion"])
        self.assertEqual(evaluate_response["task_envelope"]["status"], "completed")
        self.assertEqual(
            evaluate_response["enforcement_result"]["verification_result"]["evidence_is_sufficient"],
            True,
        )

    def test_service_can_reevaluate_intake_ready_task_to_completed_when_evidence_arrives(self) -> None:
        payload = _manual_happy_path_overlay_payload()
        submit_payload = {"request": {"task_envelope": deepcopy(payload["request"]["task_envelope"])}}

        submit_status, submit_response = self.service.submit(submit_payload)
        task_id = submit_response["task_envelope"]["id"]
        reevaluation_payload = {
            "request": {
                "new_artifacts": deepcopy(payload["request"]["linked_artifacts"]),
                "completion_evidence": deepcopy(payload["request"]["completion_evidence"]),
                "external_facts": deepcopy(payload["request"]["external_facts"]),
                "claimed_completion": True,
                "acceptance_criteria_satisfied": True,
                "runtime_facts": deepcopy(payload["request"]["runtime_facts"]),
            }
        }

        reevaluation_status, reevaluation_response = self.service.reevaluate(task_id, reevaluation_payload)

        self.assertEqual(submit_status, 200)
        self.assertEqual(submit_response["task_envelope"]["status"], "intake_ready")
        self.assertEqual(reevaluation_status, 200)
        self.assertEqual(reevaluation_response["action"], "transition_applied")
        self.assertTrue(reevaluation_response["accepted_completion"])
        self.assertEqual(reevaluation_response["task_envelope"]["status"], "completed")
        self.assertEqual(
            reevaluation_response["enforcement_result"]["verification_result"]["evidence_is_sufficient"],
            True,
        )

    def test_service_completion_claim_is_intercepted_and_cannot_directly_complete_task(self) -> None:
        payload = _manual_happy_path_overlay_payload()
        submit_payload = {"request": {"task_envelope": deepcopy(payload["request"]["task_envelope"])}}
        submit_status, submit_response = self.service.submit(submit_payload)
        task_id = submit_response["task_envelope"]["id"]

        claim_status, claim_response = self.service.submit_completion_claim(
            task_id,
            {
                "request": {
                    **_completion_claim_payload(claim_id="claim-intercepted-1"),
                    "runtime_facts": {"executor_reported_success": True, "attempt_count": 1},
                }
            },
        )

        self.assertEqual(submit_status, 200)
        self.assertEqual(claim_status, 200)
        self.assertFalse(claim_response["accepted_completion"])
        self.assertNotEqual(claim_response["task_envelope"]["status"], "completed")
        claims = claim_response["task_envelope"]["observability"]["execution_metadata"]["advisory_completion_claims"]
        self.assertEqual(claims[-1]["claim_id"], "claim-intercepted-1")

    def test_service_completion_claim_routes_into_canonical_evaluation_and_can_complete_when_evidence_aligns(self) -> None:
        payload = _manual_happy_path_overlay_payload()
        submit_payload = {"request": {"task_envelope": deepcopy(payload["request"]["task_envelope"])}}
        submit_status, submit_response = self.service.submit(submit_payload)
        task_id = submit_response["task_envelope"]["id"]

        claim_status, claim_response = self.service.submit_completion_claim(
            task_id,
            {
                "request": {
                    **_completion_claim_payload(claim_id="claim-complete-1"),
                    "new_artifacts": deepcopy(payload["request"]["linked_artifacts"]),
                    "completion_evidence": deepcopy(payload["request"]["completion_evidence"]),
                    "external_facts": deepcopy(payload["request"]["external_facts"]),
                    "acceptance_criteria_satisfied": True,
                    "runtime_facts": deepcopy(payload["request"]["runtime_facts"]),
                }
            },
        )
        history_status, history_payload = self.service.get_evaluation_history(task_id)
        latest_request = history_payload["evaluations"][-1]["request"]

        self.assertEqual(submit_status, 200)
        self.assertEqual(claim_status, 200)
        self.assertTrue(claim_response["accepted_completion"])
        self.assertEqual(claim_response["task_envelope"]["status"], "completed")
        self.assertEqual(history_status, 200)
        self.assertTrue(latest_request["claimed_completion"])
        claims = latest_request["task_envelope"]["observability"]["execution_metadata"]["advisory_completion_claims"]
        self.assertEqual(claims[-1]["claim_id"], "claim-complete-1")

    def test_service_completion_claim_can_attach_execution_attempt_and_link_reevaluation(self) -> None:
        payload = _manual_happy_path_overlay_payload()
        submit_payload = {"request": {"task_envelope": deepcopy(payload["request"]["task_envelope"])}}
        submit_status, submit_response = self.service.submit(submit_payload)
        task_id = submit_response["task_envelope"]["id"]

        claim_status, claim_response = self.service.submit_completion_claim(
            task_id,
            {
                "request": {
                    **_completion_claim_payload(claim_id="claim-with-attempt-1"),
                    **_execution_attempt_payload(attempt_id="attempt-linked-1"),
                    "new_artifacts": deepcopy(payload["request"]["linked_artifacts"]),
                    "completion_evidence": deepcopy(payload["request"]["completion_evidence"]),
                    "external_facts": deepcopy(payload["request"]["external_facts"]),
                    "acceptance_criteria_satisfied": True,
                    "runtime_facts": deepcopy(payload["request"]["runtime_facts"]),
                }
            },
        )
        timeline_status, timeline_payload = self.service.get_task_timeline(task_id)

        self.assertEqual(submit_status, 200)
        self.assertEqual(claim_status, 200)
        self.assertTrue(claim_response["accepted_completion"])
        execution_attempts = claim_response["task_envelope"]["observability"]["execution_metadata"]["execution_attempts"]
        latest_attempt = execution_attempts[-1]
        self.assertEqual(latest_attempt["attempt_id"], "attempt-linked-1")
        self.assertEqual(latest_attempt["completion_claim_id"], "claim-with-attempt-1")
        self.assertEqual(latest_attempt["reevaluation"]["evaluation_id"], claim_response["evaluation_record"]["evaluation_id"])
        self.assertEqual(timeline_status, 200)
        execution_events = [
            event for event in timeline_payload["timeline"] if event["event_type"] == "execution_attempt_recorded"
        ]
        self.assertTrue(execution_events)

    def test_service_dispatch_task_records_attempt_and_runs_reevaluation(self) -> None:
        payload = _manual_happy_path_overlay_payload()
        submit_payload = {"request": {"task_envelope": deepcopy(payload["request"]["task_envelope"])}}
        submit_status, submit_response = self.service.submit(submit_payload)
        task_id = submit_response["task_envelope"]["id"]

        dispatch_status, dispatch_response = self.service.dispatch_task(
            task_id,
            {
                "request": {
                    "executor": "codex",
                    "execution_parameters": {"mode": "manual"},
                    "artifact_references": [
                        {
                            "reference_id": "attempt-1:pr",
                            "artifact_type": "pull_request",
                            "location": "https://github.com/sfayka/Harness/pull/999",
                            "metadata": {
                                "branch_name": "codex/manual-task-dispatch",
                                "commit_sha": "abc123",
                            },
                        }
                    ],
                }
            },
        )
        timeline_status, timeline_payload = self.service.get_task_timeline(task_id)
        read_model_status, read_model_payload = self.service.get_task_read_model(task_id)

        self.assertEqual(submit_status, 200)
        self.assertEqual(dispatch_status, 200)
        self.assertEqual(dispatch_response["dispatch"]["attempt_id"], "attempt-1")
        self.assertEqual(dispatch_response["dispatch"]["executor"], "codex")
        self.assertIn(
            dispatch_response["dispatch"]["attempt_status"],
            {"started", "in_progress", "completed", "failed", "blocked"},
        )
        self.assertEqual(timeline_status, 200)
        self.assertTrue(any(event["event_type"] == "task_dispatched" for event in timeline_payload["timeline"]))
        self.assertTrue(any(event["event_type"] == "execution_event_recorded" for event in timeline_payload["timeline"]))
        self.assertTrue(any(event["event_type"] == "execution_artifact_attached" for event in timeline_payload["timeline"]))
        self.assertEqual(read_model_status, 200)
        self.assertEqual(read_model_payload["task"]["execution_summary"]["attempt_count"], 1)

    def test_service_dispatch_rejects_terminal_tasks(self) -> None:
        submit_status, submit_payload = self.service.submit(_request_payload("accepted_completion"))
        task_id = submit_payload["task_envelope"]["id"]

        dispatch_status, dispatch_response = self.service.dispatch_task(task_id, {"request": {"executor": "codex"}})

        self.assertEqual(submit_status, 200)
        self.assertEqual(dispatch_status, 409)
        self.assertIn("terminal", dispatch_response["error"])

    def test_service_evaluate_existing_review_required_task_cannot_be_overwritten_to_completed(self) -> None:
        initial_status, initial_response = self.service.evaluate(_request_payload("review_required"))
        task_id = initial_response["task_envelope"]["id"]

        overwrite_payload = _request_payload("accepted_completion")
        overwrite_payload["request"]["task_envelope"]["id"] = task_id
        overwrite_payload["request"]["task_envelope"]["status"] = "completed"
        overwrite_payload["request"]["task_envelope"]["timestamps"]["completed_at"] = "2026-03-24T18:00:00Z"

        overwrite_status, overwrite_response = self.service.evaluate(overwrite_payload)
        task_status, task_payload = self.service.get_task(task_id)
        history_status, history_payload = self.service.get_evaluation_history(task_id)

        self.assertEqual(initial_status, 200)
        self.assertEqual(initial_response["task_envelope"]["status"], "in_review")
        self.assertEqual(overwrite_status, 200)
        self.assertEqual(overwrite_response["action"], "review_required")
        self.assertEqual(overwrite_response["task_envelope"]["status"], "in_review")
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["status"], "in_review")
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 2)

    def test_service_can_resolve_legacy_completed_review_gate_via_manual_decision(self) -> None:
        initial_status, initial_response = self.service.evaluate(_request_payload("review_required"))
        task_id = initial_response["task_envelope"]["id"]
        stored_task = deepcopy(self.service.store.get_task(task_id))
        stored_task["status"] = "completed"
        stored_task["timestamps"]["completed_at"] = "2026-03-24T18:05:00Z"
        self.service.store.update_task(stored_task)

        resolution_status, resolution_response = self.service.reevaluate(
            task_id,
            {"request": {"review_decision": _review_decision_payload(task_id)}},
        )
        task_status, task_payload = self.service.get_task(task_id)
        history_status, history_payload = self.service.get_evaluation_history(task_id)

        self.assertEqual(initial_status, 200)
        self.assertEqual(resolution_status, 200)
        self.assertEqual(resolution_response["task_envelope"]["status"], "completed")
        self.assertEqual(resolution_response["target_status"], "completed")
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["status"], "completed")
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 2)

    def test_health_reports_file_store_without_database_configuration(self) -> None:
        status, payload = self.service.health()

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["store_backend"], "file")
        self.assertFalse(payload["database_configured"])
        self.assertIsNone(payload["database_host"])
        self.assertIsNone(payload["database_schema_ready"])

    def test_health_reports_postgres_schema_ready_without_exposing_credentials(self) -> None:
        store = PostgresHarnessStore("postgresql://worker:super-secret@db.internal.example:5432/harness")
        service = HarnessApiService(store=store)

        with patch.object(store, "_connect", return_value=_FakeConnection([(True,), (True,)])):
            status, payload = service.health()

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["store_backend"], "postgres")
        self.assertTrue(payload["database_configured"])
        self.assertEqual(payload["database_host"], "db.internal.example")
        self.assertTrue(payload["database_schema_ready"])
        self.assertNotIn("super-secret", json.dumps(payload))
        self.assertNotIn("worker", json.dumps(payload))

    def test_health_reports_postgres_schema_not_ready_when_expected_tables_are_missing(self) -> None:
        store = PostgresHarnessStore("postgresql://db.internal.example/harness")
        service = HarnessApiService(store=store)

        with patch.object(store, "_connect", return_value=_FakeConnection([(True,), (False,)])):
            status, payload = service.health()

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "degraded")
        self.assertEqual(payload["store_backend"], "postgres")
        self.assertTrue(payload["database_configured"])
        self.assertEqual(payload["database_host"], "db.internal.example")
        self.assertFalse(payload["database_schema_ready"])

    def test_health_reports_postgres_schema_not_ready_when_database_is_unreachable(self) -> None:
        store = PostgresHarnessStore("postgresql://db.internal.example/harness")
        service = HarnessApiService(store=store)

        with patch.object(store, "_connect", side_effect=RuntimeError("connection refused")):
            status, payload = service.health()

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "degraded")
        self.assertEqual(payload["store_backend"], "postgres")
        self.assertTrue(payload["database_configured"])
        self.assertEqual(payload["database_host"], "db.internal.example")
        self.assertFalse(payload["database_schema_ready"])

    def test_service_retries_retryable_transient_failure_with_bounded_budget(self) -> None:
        payload = _request_payload("accepted_completion")
        payload["request"]["runtime_facts"] = {
            "executor_reported_success": True,
            "executor_reported_failure": True,
            "terminal_failure": True,
            "attempt_count": 1,
            "latest_attempt_outcome": "failed",
        }

        with patch.dict(os.environ, {"HARNESS_CLASSIFIED_RETRY_BUDGET": "2"}):
            status, response = self.service.submit(payload)
        history_status, history = self.service.get_evaluation_history(response["task_envelope"]["id"])

        self.assertEqual(status, 200)
        self.assertEqual(response["failure_classification"]["category"], "executor_runtime_failure")
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history["evaluations"]), 3)
        retry_requests = [item["request"].get("retry_context") for item in history["evaluations"]]
        self.assertIsNone(retry_requests[0])
        self.assertEqual(retry_requests[1]["triggered_by_category"], "executor_runtime_failure")
        self.assertEqual(retry_requests[2]["triggered_by_category"], "executor_runtime_failure")

    def test_service_does_not_retry_non_retryable_contract_violation(self) -> None:
        payload = _request_payload("accepted_completion")
        payload["request"]["unresolved_conditions"] = ["Execution checkpoint is missing."]

        with patch.dict(os.environ, {"HARNESS_CLASSIFIED_RETRY_BUDGET": "2"}):
            status, response = self.service.submit(payload)
        history_status, history = self.service.get_evaluation_history(response["task_envelope"]["id"])

        self.assertEqual(status, 200)
        self.assertEqual(response["failure_classification"]["category"], "contract_violation")
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history["evaluations"]), 1)

    def test_service_does_not_retry_non_retryable_evidence_insufficiency(self) -> None:
        payload = _request_payload("blocked_insufficient_evidence")

        with patch.dict(os.environ, {"HARNESS_CLASSIFIED_RETRY_BUDGET": "2"}):
            status, response = self.service.submit(payload)
        history_status, history = self.service.get_evaluation_history(response["task_envelope"]["id"])

        self.assertEqual(status, 200)
        self.assertEqual(response["failure_classification"]["category"], "evidence_insufficiency")
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history["evaluations"]), 1)

    def test_service_does_not_retry_non_retryable_reconciliation_mismatch(self) -> None:
        payload = _request_payload("blocked_reconciliation_mismatch")

        with patch.dict(os.environ, {"HARNESS_CLASSIFIED_RETRY_BUDGET": "2"}):
            status, response = self.service.submit(payload)
        history_status, history = self.service.get_evaluation_history(response["task_envelope"]["id"])

        self.assertEqual(status, 200)
        self.assertEqual(response["failure_classification"]["category"], "reconciliation_mismatch")
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history["evaluations"]), 1)


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
        self.assertEqual(payload["store_backend"], "file")
        self.assertFalse(payload["database_configured"])
        self.assertIsNone(payload["database_host"])
        self.assertIsNone(payload["database_schema_ready"])

    def test_api_submit_accepts_new_task_and_persists_initial_result(self) -> None:
        status, payload = self._post_json("/tasks", _request_payload("accepted_completion"))
        task_id = payload["task_envelope"]["id"]

        task_status, task_payload = self._get_json(f"/tasks/{task_id}")
        history_status, history_payload = self._get_json(f"/tasks/{task_id}/evaluations")

        self.assertEqual(status, 200)
        self.assertEqual(payload["task_envelope"]["status"], "completed")
        self.assertIn("evaluation_record", payload)
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["status"], "completed")
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 1)

    def test_api_lists_dashboard_tasks(self) -> None:
        self._post_json("/tasks", _request_payload("accepted_completion"))
        self._post_json("/tasks", _request_payload("blocked_insufficient_evidence"))

        status, payload = self._get_json("/tasks")

        self.assertEqual(status, 200)
        self.assertEqual(len(payload["tasks"]), 2)
        self.assertIn("task_id", payload["tasks"][0])
        self.assertIn("review_summary", payload["tasks"][0])

    def test_api_submit_can_persist_initial_blocked_result(self) -> None:
        status, payload = self._post_json("/tasks", _request_payload("blocked_insufficient_evidence"))
        task_id = payload["task_envelope"]["id"]

        task_status, task_payload = self._get_json(f"/tasks/{task_id}")

        self.assertEqual(status, 200)
        self.assertEqual(payload["target_status"], "blocked")
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["status"], "blocked")

    def test_api_submit_can_persist_initial_review_required_result(self) -> None:
        status, payload = self._post_json("/tasks", _request_payload("review_required"))
        task_id = payload["task_envelope"]["id"]

        task_status, task_payload = self._get_json(f"/tasks/{task_id}")
        history_status, history_payload = self._get_json(f"/tasks/{task_id}/evaluations")

        self.assertEqual(status, 200)
        self.assertEqual(payload["action"], "review_required")
        self.assertEqual(payload["target_status"], "in_review")
        self.assertTrue(payload["requires_review"])
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["id"], task_id)
        self.assertEqual(task_payload["task"]["status"], "in_review")
        self.assertEqual(history_status, 200)
        self.assertEqual(history_payload["evaluations"][0]["result"]["action"], "review_required")

    def test_api_submit_rejects_invalid_input_without_persisting_state(self) -> None:
        invalid_payload = _request_payload("invalid_input")
        task_id = invalid_payload["request"]["task_envelope"]["id"]

        status, payload = self._post_json("/tasks", invalid_payload)
        task_status, task_payload = self._get_json(f"/tasks/{task_id}")

        self.assertEqual(status, 400)
        self.assertTrue(payload["invalid_input"])
        self.assertEqual(task_status, 404)
        self.assertIn("not found", task_payload["error"].lower())

    def test_api_submit_rejects_missing_task_id_with_structured_400(self) -> None:
        status, payload = self._post_json("/tasks", {"request": {"task_envelope": {"title": "Missing id"}}})

        self.assertEqual(status, 400)
        self.assertTrue(payload["invalid_input"])
        self.assertIn("task_envelope.id is required", payload["error"])

    def test_api_submit_rejects_schema_invalid_task_envelope_with_structured_400(self) -> None:
        status, payload = self._post_json("/tasks", _schema_invalid_submission_payload())

        self.assertEqual(status, 400)
        self.assertTrue(payload["invalid_input"])
        self.assertIn("Invalid TaskEnvelope:", payload["error"])

    def test_api_submit_rejects_duplicate_task_id_with_conflict(self) -> None:
        initial_status, initial_payload = self._post_json("/tasks", _request_payload("accepted_completion"))
        duplicate_status, duplicate_payload = self._post_json("/tasks", _request_payload("accepted_completion"))
        history_status, history_payload = self._get_json(
            f"/tasks/{initial_payload['task_envelope']['id']}/evaluations"
        )

        self.assertEqual(initial_status, 200)
        self.assertEqual(duplicate_status, 409)
        self.assertTrue(duplicate_payload["duplicate_task_id"])
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 1)

    def test_api_linear_ingress_can_submit_accepted_task(self) -> None:
        status, payload = self._post_json("/ingress/linear", _linear_ingress_payload("accepted_completion"))
        task_id = payload["task_envelope"]["id"]

        task_status, task_payload = self._get_json(f"/tasks/{task_id}")
        history_status, history_payload = self._get_json(f"/tasks/{task_id}/evaluations")

        self.assertEqual(status, 200)
        self.assertEqual(payload["task_envelope"]["origin"]["source_system"], "linear")
        self.assertEqual(payload["task_envelope"]["status"], "completed")
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["extensions"]["linear"]["issue_id"], f"lin-{task_id}")
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 1)

    def test_api_linear_ingress_can_submit_initial_blocked_task(self) -> None:
        status, payload = self._post_json("/ingress/linear", _linear_ingress_payload("blocked_insufficient_evidence"))
        task_id = payload["task_envelope"]["id"]

        task_status, task_payload = self._get_json(f"/tasks/{task_id}")

        self.assertEqual(status, 200)
        self.assertEqual(payload["target_status"], "blocked")
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["status"], "blocked")

    def test_api_linear_ingress_rejects_invalid_payload_without_persisting_state(self) -> None:
        payload = _linear_ingress_payload("accepted_completion", task_id="task-linear-invalid-1")
        del payload["issue"]["title"]

        status, response_payload = self._post_json("/ingress/linear", payload)
        task_status, task_payload = self._get_json("/tasks/task-linear-invalid-1")

        self.assertEqual(status, 400)
        self.assertTrue(response_payload["invalid_input"])
        self.assertEqual(task_status, 404)
        self.assertIn("not found", task_payload["error"].lower())

    def test_api_linear_ingress_rejects_duplicate_task_id_consistently(self) -> None:
        payload = _linear_ingress_payload("accepted_completion", task_id="task-linear-duplicate-1")

        initial_status, _ = self._post_json("/ingress/linear", payload)
        duplicate_status, duplicate_payload = self._post_json("/ingress/linear", payload)
        history_status, history_payload = self._get_json("/tasks/task-linear-duplicate-1/evaluations")

        self.assertEqual(initial_status, 200)
        self.assertEqual(duplicate_status, 409)
        self.assertTrue(duplicate_payload["duplicate_task_id"])
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 1)

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


    def test_api_accepts_manual_ingress_submission_endpoint(self) -> None:
        status, payload = self._post_json("/ingress/manual", _manual_ingress_payload())

        self.assertEqual(status, 200)
        self.assertIn("task_envelope", payload)
        self.assertEqual(payload["task_envelope"]["origin"]["source_system"], "manual")
        self.assertTrue(payload["task_envelope"]["id"])

    def test_api_accepts_openclaw_ingress_submission_endpoint(self) -> None:
        status, payload = self._post_json("/ingress/openclaw", _openclaw_ingress_payload())
        task_id = payload["task_envelope"]["id"]

        read_status, read_payload = self._get_json(f"/tasks/{task_id}/read-model")
        self.assertEqual(status, 200)
        self.assertEqual(payload["task_envelope"]["origin"]["source_system"], "openclaw")
        self.assertEqual(payload["task_envelope"]["origin"]["ingress_name"], "OpenClaw")
        self.assertEqual(read_status, 200)
        self.assertEqual(read_payload["task"]["extensions"]["openclaw"]["metadata"]["request_kind"], "openclaw")

    def test_api_openclaw_ingress_rejects_invalid_payload_without_persisting_state(self) -> None:
        payload = _openclaw_ingress_payload(task_id="task-openclaw-invalid-1")
        payload["context"] = "invalid"

        status, response_payload = self._post_json("/ingress/openclaw", payload)
        task_status, task_payload = self._get_json("/tasks/task-openclaw-invalid-1")

        self.assertEqual(status, 400)
        self.assertTrue(response_payload["invalid_input"])
        self.assertEqual(task_status, 404)
        self.assertIn("not found", task_payload["error"].lower())

    def test_api_accepts_manual_happy_path_overlay_payload(self) -> None:
        payload = _manual_happy_path_overlay_payload()

        status, response = self._post_json("/evaluate", payload)

        self.assertEqual(status, 200)
        self.assertEqual(response["action"], "transition_applied")
        self.assertEqual(response["target_status"], "completed")
        self.assertTrue(response["accepted_completion"])
        self.assertEqual(response["task_envelope"]["status"], "completed")
        self.assertEqual(
            response["enforcement_result"]["verification_result"]["outcome"],
            "accepted_completion",
        )

    def test_api_evaluate_existing_task_reapplies_top_level_overlays(self) -> None:
        payload = _manual_happy_path_overlay_payload()
        submit_payload = {"request": {"task_envelope": deepcopy(payload["request"]["task_envelope"])}}

        submit_status, submit_response = self._post_json("/tasks", submit_payload)
        evaluate_status, evaluate_response = self._post_json("/evaluate", payload)

        self.assertEqual(submit_status, 200)
        self.assertEqual(submit_response["task_envelope"]["status"], "intake_ready")
        self.assertEqual(evaluate_status, 200)
        self.assertEqual(evaluate_response["action"], "transition_applied")
        self.assertTrue(evaluate_response["accepted_completion"])
        self.assertEqual(evaluate_response["task_envelope"]["status"], "completed")
        self.assertEqual(
            evaluate_response["enforcement_result"]["verification_result"]["evidence_is_sufficient"],
            True,
        )

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
        self.assertEqual(payload["target_status"], "in_review")
        self.assertTrue(payload["requires_review"])
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["status"], "in_review")
        self.assertEqual(payload["task_envelope"]["status"], "in_review")
        self.assertEqual(history_status, 200)
        self.assertEqual(history_payload["evaluations"][0]["result"]["action"], "review_required")

    def test_api_review_required_intake_ready_request_does_not_reject_transition(self) -> None:
        payload = _request_payload("review_required")

        self.assertEqual(payload["request"]["task_envelope"]["status"], "intake_ready")

        status, response = self._post_json("/evaluate", payload)

        self.assertEqual(status, 200)
        self.assertEqual(response["action"], "review_required")
        self.assertEqual(response["target_status"], "in_review")
        self.assertEqual(response["task_envelope"]["status"], "in_review")
        self.assertNotEqual(response["action"], "transition_rejected")

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

    def test_api_sets_cors_headers_for_browser_clients(self) -> None:
        request = Request(self.base_url + "/tasks", method="OPTIONS")

        with urlopen(request) as response:
            self.assertEqual(response.status, 204)
            self.assertEqual(response.headers["Access-Control-Allow-Origin"], "*")
            self.assertIn("GET", response.headers["Access-Control-Allow-Methods"])

    def test_api_can_reevaluate_blocked_task_to_completed_when_new_evidence_arrives(self) -> None:
        initial_payload = _request_payload("blocked_insufficient_evidence")
        initial_status, initial_response = self._post_json("/evaluate", initial_payload)
        task_id = initial_response["task_envelope"]["id"]

        reevaluation_payload = {
            "request": {
                "new_artifacts": [_review_note_artifact()],
                "completion_evidence": {
                    "validated_artifact_ids": [
                        "artifact-pr-1",
                        "artifact-commit-1",
                        "artifact-review-note-1",
                    ]
                },
                "external_facts": deepcopy(_request_payload("accepted_completion")["request"]["external_facts"]),
                "claimed_completion": True,
                "acceptance_criteria_satisfied": True,
                "runtime_facts": deepcopy(initial_payload["request"]["runtime_facts"]),
            }
        }
        reevaluation_status, reevaluation_response = self._post_json(
            f"/tasks/{task_id}/reevaluate",
            reevaluation_payload,
        )
        history_status, history_payload = self._get_json(f"/tasks/{task_id}/evaluations")

        self.assertEqual(initial_status, 200)
        self.assertEqual(initial_response["task_envelope"]["status"], "blocked")
        self.assertEqual(reevaluation_status, 200)
        self.assertEqual(reevaluation_response["task_envelope"]["status"], "completed")
        self.assertEqual(history_status, 200)
        self.assertEqual(len(history_payload["evaluations"]), 2)

    def test_api_can_reevaluate_intake_ready_task_to_completed_when_evidence_arrives(self) -> None:
        payload = _manual_happy_path_overlay_payload()
        submit_payload = {"request": {"task_envelope": deepcopy(payload["request"]["task_envelope"])}}

        submit_status, submit_response = self._post_json("/tasks", submit_payload)
        task_id = submit_response["task_envelope"]["id"]
        reevaluation_payload = {
            "request": {
                "new_artifacts": deepcopy(payload["request"]["linked_artifacts"]),
                "completion_evidence": deepcopy(payload["request"]["completion_evidence"]),
                "external_facts": deepcopy(payload["request"]["external_facts"]),
                "claimed_completion": True,
                "acceptance_criteria_satisfied": True,
                "runtime_facts": deepcopy(payload["request"]["runtime_facts"]),
            }
        }

        reevaluation_status, reevaluation_response = self._post_json(
            f"/tasks/{task_id}/reevaluate",
            reevaluation_payload,
        )

        self.assertEqual(submit_status, 200)
        self.assertEqual(submit_response["task_envelope"]["status"], "intake_ready")
        self.assertEqual(reevaluation_status, 200)
        self.assertEqual(reevaluation_response["action"], "transition_applied")
        self.assertTrue(reevaluation_response["accepted_completion"])
        self.assertEqual(reevaluation_response["task_envelope"]["status"], "completed")

    def test_api_completion_claim_endpoint_intercepts_claim_and_routes_to_evaluation(self) -> None:
        payload = _manual_happy_path_overlay_payload()
        submit_payload = {"request": {"task_envelope": deepcopy(payload["request"]["task_envelope"])}}
        submit_status, submit_response = self._post_json("/tasks", submit_payload)
        task_id = submit_response["task_envelope"]["id"]

        claim_status, claim_response = self._post_json(
            f"/tasks/{task_id}/completion-claims",
            {
                "request": {
                    **_completion_claim_payload(claim_id="claim-api-1"),
                    "runtime_facts": {"executor_reported_success": True, "attempt_count": 1},
                }
            },
        )
        history_status, history_payload = self._get_json(f"/tasks/{task_id}/evaluations")

        self.assertEqual(submit_status, 200)
        self.assertEqual(claim_status, 200)
        self.assertFalse(claim_response["accepted_completion"])
        self.assertNotEqual(claim_response["task_envelope"]["status"], "completed")
        self.assertEqual(history_status, 200)
        claims = history_payload["evaluations"][-1]["request"]["task_envelope"]["observability"]["execution_metadata"][
            "advisory_completion_claims"
        ]
        self.assertEqual(claims[-1]["claim_id"], "claim-api-1")

    def test_api_dispatch_endpoint_records_execution_attempt(self) -> None:
        payload = _manual_happy_path_overlay_payload()
        submit_payload = {"request": {"task_envelope": deepcopy(payload["request"]["task_envelope"])}}
        submit_status, submit_response = self._post_json("/tasks", submit_payload)
        task_id = submit_response["task_envelope"]["id"]

        dispatch_status, dispatch_response = self._post_json(
            f"/tasks/{task_id}/dispatch",
            {"request": {"executor": "codex"}},
        )

        self.assertEqual(submit_status, 200)
        self.assertEqual(dispatch_status, 200)
        self.assertEqual(dispatch_response["dispatch"]["task_id"], task_id)

    def test_api_can_reevaluate_completed_task_back_to_blocked_for_contradictory_facts(self) -> None:
        initial_payload = _request_payload("accepted_completion")
        initial_status, initial_response = self._post_json("/evaluate", initial_payload)
        task_id = initial_response["task_envelope"]["id"]

        reevaluation_payload = {
            "request": {
                "external_facts": deepcopy(_request_payload("blocked_reconciliation_mismatch")["request"]["external_facts"]),
                "claimed_completion": True,
                "acceptance_criteria_satisfied": True,
                "runtime_facts": deepcopy(initial_payload["request"]["runtime_facts"]),
            }
        }
        reevaluation_status, reevaluation_response = self._post_json(
            f"/tasks/{task_id}/reevaluate",
            reevaluation_payload,
        )

        self.assertEqual(initial_status, 200)
        self.assertEqual(initial_response["task_envelope"]["status"], "completed")
        self.assertEqual(reevaluation_status, 200)
        self.assertEqual(reevaluation_response["task_envelope"]["status"], "blocked")
        self.assertEqual(
            reevaluation_response["enforcement_result"]["verification_result"]["outcome"],
            "external_mismatch",
        )

    def test_api_can_reevaluate_review_required_path_to_completed_after_manual_review(self) -> None:
        accepted_payload = _request_payload("accepted_completion")
        initial_payload = {
            "request": deepcopy(accepted_payload["request"]),
        }
        initial_payload["request"]["task_envelope"]["status"] = "blocked"
        initial_payload["request"]["task_envelope"]["timestamps"]["completed_at"] = None
        initial_payload["request"]["review_request"] = deepcopy(_request_payload("review_required")["request"]["review_request"])
        initial_payload["request"]["review_request"]["task_id"] = initial_payload["request"]["task_envelope"]["id"]
        initial_payload["request"]["external_facts"] = deepcopy(_request_payload("review_required")["request"]["external_facts"])

        initial_status, initial_response = self._post_json("/evaluate", initial_payload)
        task_id = initial_response["task_envelope"]["id"]

        reevaluation_payload = {
            "request": {
                "review_decision": _review_decision_payload(task_id),
            }
        }
        reevaluation_status, reevaluation_response = self._post_json(
            f"/tasks/{task_id}/reevaluate",
            reevaluation_payload,
        )

        self.assertEqual(initial_status, 200)
        self.assertEqual(initial_response["action"], "review_required")
        self.assertEqual(initial_response["task_envelope"]["status"], "in_review")
        self.assertEqual(reevaluation_status, 200)
        self.assertEqual(reevaluation_response["task_envelope"]["status"], "completed")
        self.assertIn(reevaluation_response["action"], {"transition_applied", "follow_up_authorized"})

    def test_api_cannot_reevaluate_in_review_task_to_completed_without_manual_decision(self) -> None:
        initial_status, initial_response = self._post_json("/evaluate", _request_payload("review_required"))
        task_id = initial_response["task_envelope"]["id"]

        reevaluation_status, reevaluation_response = self._post_json(
            f"/tasks/{task_id}/reevaluate",
            {
                "request": {
                    "external_facts": deepcopy(_request_payload("accepted_completion")["request"]["external_facts"]),
                    "claimed_completion": True,
                    "acceptance_criteria_satisfied": True,
                    "runtime_facts": deepcopy(_request_payload("accepted_completion")["request"]["runtime_facts"]),
                }
            },
        )
        task_status, task_payload = self._get_json(f"/tasks/{task_id}")

        self.assertEqual(initial_status, 200)
        self.assertEqual(initial_response["task_envelope"]["status"], "in_review")
        self.assertEqual(reevaluation_status, 200)
        self.assertEqual(reevaluation_response["action"], "review_required")
        self.assertEqual(reevaluation_response["task_envelope"]["status"], "in_review")
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["status"], "in_review")

    def test_api_cannot_bypass_active_review_gate_via_evaluate_upsert(self) -> None:
        initial_status, initial_response = self._post_json("/evaluate", _request_payload("review_required"))
        task_id = initial_response["task_envelope"]["id"]

        overwrite_payload = _request_payload("accepted_completion")
        overwrite_payload["request"]["task_envelope"]["id"] = task_id
        overwrite_payload["request"]["task_envelope"]["status"] = "completed"
        overwrite_payload["request"]["task_envelope"]["timestamps"]["completed_at"] = "2026-03-24T18:00:00Z"

        overwrite_status, overwrite_response = self._post_json("/evaluate", overwrite_payload)
        task_status, task_payload = self._get_json(f"/tasks/{task_id}")

        self.assertEqual(initial_status, 200)
        self.assertEqual(initial_response["task_envelope"]["status"], "in_review")
        self.assertEqual(overwrite_status, 200)
        self.assertEqual(overwrite_response["action"], "review_required")
        self.assertEqual(overwrite_response["task_envelope"]["status"], "in_review")
        self.assertEqual(task_status, 200)
        self.assertEqual(task_payload["task"]["status"], "in_review")

    def test_api_accepts_review_required_linear_facts_with_null_workflow_when_record_not_found(self) -> None:
        payload = _request_payload("review_required")

        status, response = self._post_json("/evaluate", payload)

        self.assertEqual(status, 200)
        self.assertEqual(response["action"], "review_required")

    def test_api_accepts_review_required_linear_facts_with_omitted_workflow_when_record_not_found(self) -> None:
        payload = _request_payload("review_required")
        del payload["request"]["external_facts"]["linear_facts"]["workflow"]

        status, response = self._post_json("/evaluate", payload)

        self.assertEqual(status, 200)
        self.assertEqual(response["action"], "review_required")

    def test_api_rejects_record_found_linear_facts_without_workflow(self) -> None:
        payload = _request_payload("accepted_completion")
        del payload["request"]["external_facts"]["linear_facts"]["workflow"]

        status, response = self._post_json("/evaluate", payload)

        self.assertEqual(status, 400)
        self.assertTrue(response["invalid_input"])
        self.assertEqual(
            response["error"],
            "Invalid external_facts.linear_facts.workflow: must be null/omitted when record_found=false, or an object with workflow_id and workflow_name when record_found=true",
        )

    def test_api_rejects_record_found_linear_facts_with_incomplete_workflow(self) -> None:
        payload = _request_payload("accepted_completion")
        payload["request"]["external_facts"]["linear_facts"]["workflow"] = {
            "workflow_id": "workflow-in-progress",
        }

        status, response = self._post_json("/evaluate", payload)

        self.assertEqual(status, 400)
        self.assertTrue(response["invalid_input"])
        self.assertEqual(
            response["error"],
            "Invalid external_facts.linear_facts.workflow: must be null/omitted when record_found=false, or an object with workflow_id and workflow_name when record_found=true",
        )

    def test_api_can_reevaluate_pending_task_to_completed_when_external_facts_arrive(self) -> None:
        initial_payload = _request_payload("accepted_completion")
        initial_payload["request"]["external_facts"] = None

        initial_status, initial_response = self._post_json("/evaluate", initial_payload)
        task_id = initial_payload["request"]["task_envelope"]["id"]

        reevaluation_payload = {
            "request": {
                "external_facts": deepcopy(_request_payload("accepted_completion")["request"]["external_facts"]),
                "claimed_completion": True,
                "acceptance_criteria_satisfied": True,
                "runtime_facts": deepcopy(initial_payload["request"]["runtime_facts"]),
            }
        }
        reevaluation_status, reevaluation_response = self._post_json(
            f"/tasks/{task_id}/reevaluate",
            reevaluation_payload,
        )

        self.assertEqual(initial_status, 200)
        self.assertEqual(initial_response["task_envelope"]["status"], "blocked")
        self.assertEqual(
            initial_response["enforcement_result"]["verification_result"]["outcome"],
            "blocked_unresolved_conditions",
        )
        self.assertEqual(reevaluation_status, 200)
        self.assertEqual(reevaluation_response["task_envelope"]["status"], "completed")
        self.assertEqual(
            reevaluation_response["task_envelope"]["coordination"]["linear"]["provenance"]["source"],
            "reevaluation_request.external_facts",
        )

    def test_api_persists_linear_coordination_when_record_not_found_and_when_conflicting(self) -> None:
        initial_payload = _request_payload("accepted_completion")
        initial_status, initial_response = self._post_json("/evaluate", initial_payload)
        task_id = initial_response["task_envelope"]["id"]

        missing_record_payload = {
            "request": {
                "external_facts": {
                    "linear_facts": {
                        "record_found": False,
                        "reasons": ["Linear record was not found during sync."],
                    }
                },
                "claimed_completion": True,
                "acceptance_criteria_satisfied": True,
                "runtime_facts": deepcopy(initial_payload["request"]["runtime_facts"]),
            }
        }
        missing_status, missing_response = self._post_json(f"/tasks/{task_id}/reevaluate", missing_record_payload)

        stale_record_payload = {
            "request": {
                "external_facts": deepcopy(_request_payload("blocked_reconciliation_mismatch")["request"]["external_facts"]),
                "claimed_completion": True,
                "acceptance_criteria_satisfied": True,
                "runtime_facts": deepcopy(initial_payload["request"]["runtime_facts"]),
            }
        }
        stale_status, stale_response = self._post_json(f"/tasks/{task_id}/reevaluate", stale_record_payload)

        self.assertEqual(initial_status, 200)
        self.assertEqual(missing_status, 200)
        self.assertFalse(missing_response["task_envelope"]["coordination"]["linear"]["record_found"])
        self.assertEqual(stale_status, 200)
        self.assertEqual(stale_response["task_envelope"]["coordination"]["linear"]["state"], "in_progress")

    def test_api_appends_long_running_support_artifacts_across_reevaluations(self) -> None:
        initial_payload = _request_payload("blocked_insufficient_evidence")
        initial_status, initial_response = self._post_json("/evaluate", initial_payload)
        task_id = initial_response["task_envelope"]["id"]

        first_reevaluation_status, _ = self._post_json(
            f"/tasks/{task_id}/reevaluate",
            {
                "request": {
                    "new_artifacts": [_progress_artifact()],
                    "external_facts": deepcopy(initial_payload["request"]["external_facts"]),
                    "claimed_completion": True,
                    "acceptance_criteria_satisfied": True,
                    "runtime_facts": deepcopy(initial_payload["request"]["runtime_facts"]),
                }
            },
        )
        second_reevaluation_status, _ = self._post_json(
            f"/tasks/{task_id}/reevaluate",
            {
                "request": {
                    "new_artifacts": [_handoff_artifact()],
                    "external_facts": deepcopy(initial_payload["request"]["external_facts"]),
                    "claimed_completion": True,
                    "acceptance_criteria_satisfied": True,
                    "runtime_facts": deepcopy(initial_payload["request"]["runtime_facts"]),
                }
            },
        )
        task_status, task_payload = self._get_json(f"/tasks/{task_id}")
        history_status, history_payload = self._get_json(f"/tasks/{task_id}/evaluations")

        artifact_types = [item["type"] for item in task_payload["task"]["artifacts"]["items"]]

        self.assertEqual(initial_status, 200)
        self.assertEqual(first_reevaluation_status, 200)
        self.assertEqual(second_reevaluation_status, 200)
        self.assertEqual(task_status, 200)
        self.assertEqual(history_status, 200)
        self.assertIn("progress_artifact", artifact_types)
        self.assertIn("handoff_artifact", artifact_types)
        self.assertEqual(len(history_payload["evaluations"]), 3)
        self.assertEqual(
            task_payload["task"]["artifacts"]["completion_evidence"]["validated_artifact_ids"],
            ["artifact-pr-1", "artifact-commit-1"],
        )

    def test_api_rejects_invalid_reevaluation_without_corrupting_store_state(self) -> None:
        initial_payload = _request_payload("accepted_completion")
        initial_status, initial_response = self._post_json("/evaluate", initial_payload)
        task_id = initial_response["task_envelope"]["id"]
        before_task_status, before_task_payload = self._get_json(f"/tasks/{task_id}")
        before_history_status, before_history_payload = self._get_json(f"/tasks/{task_id}/evaluations")

        invalid_status, invalid_payload = self._post_json(
            f"/tasks/{task_id}/reevaluate",
            {
                "request": {
                    "new_artifacts": [_review_note_artifact("artifact-pr-1")],
                    "claimed_completion": True,
                    "acceptance_criteria_satisfied": True,
                }
            },
        )
        after_task_status, after_task_payload = self._get_json(f"/tasks/{task_id}")
        after_history_status, after_history_payload = self._get_json(f"/tasks/{task_id}/evaluations")

        self.assertEqual(initial_status, 200)
        self.assertEqual(before_task_status, 200)
        self.assertEqual(before_history_status, 200)
        self.assertEqual(invalid_status, 400)
        self.assertTrue(invalid_payload["invalid_input"])
        self.assertEqual(after_task_status, 200)
        self.assertEqual(after_history_status, 200)
        self.assertEqual(before_task_payload["task"], after_task_payload["task"])
        self.assertEqual(before_history_payload["evaluations"], after_history_payload["evaluations"])


if __name__ == "__main__":
    unittest.main()
