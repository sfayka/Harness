from __future__ import annotations

import unittest
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from enum import Enum

from modules.connectors import LinearIngressInputError, translate_linear_submission_payload
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


def _linear_ingress_payload() -> dict:
    canonical_request = build_demo_request("review_required")
    task = deepcopy(canonical_request.task_envelope)
    external_facts = deepcopy(canonical_request.external_facts)

    return {
        "issue": {
            "id": "lin-ingress-1",
            "identifier": "HAR-901",
            "title": task["title"],
            "description": task["description"],
        },
        "state": {
            "id": "workflow_in_progress",
            "name": "in_progress",
            "type": "started",
        },
        "project": {
            "id": "project-harness",
            "name": "Harness",
        },
        "task_reference": {
            "harness_task_id": "task-linear-ingress-1",
            "external_ref": "HAR-901",
        },
        "labels": ["feature", "ai-workflow"],
        "priority": "high",
        "task_status": "intake_ready",
        "assigned_executor": deepcopy(task["assigned_executor"]),
        "acceptance_criteria": deepcopy(task["acceptance_criteria"]),
        "external_facts": {
            "expected_code_context": deepcopy(external_facts.expected_code_context),
            "github_facts": deepcopy(external_facts.github_facts),
        },
        "claimed_completion": False,
        "acceptance_criteria_satisfied": False,
    }


class LinearIngressTranslationTests(unittest.TestCase):
    def test_translates_linear_payload_into_canonical_submission_request(self) -> None:
        submission_payload = translate_linear_submission_payload(_linear_ingress_payload())

        task = submission_payload["request"]["task_envelope"]
        linear_facts = submission_payload["request"]["external_facts"]["linear_facts"]

        self.assertEqual(task["id"], "task-linear-ingress-1")
        self.assertEqual(task["origin"]["source_system"], "linear")
        self.assertEqual(task["origin"]["source_id"], "lin-ingress-1")
        self.assertEqual(task["priority"], "high")
        self.assertTrue(task["coordination"]["linear"]["record_found"])
        self.assertEqual(task["coordination"]["linear"]["provenance"]["source"], "linear_ingress_payload")
        self.assertEqual(task["extensions"]["linear"]["issue_identifier"], "HAR-901")
        self.assertEqual(task["status"], "intake_ready")
        self.assertEqual(len(task["artifacts"]["items"]), 0)
        self.assertEqual(linear_facts["issue_id"], "lin-ingress-1")
        self.assertEqual(linear_facts["issue_key"], "HAR-901")
        self.assertEqual(linear_facts["state"], "in_progress")
        self.assertEqual(linear_facts["task_reference"]["harness_task_id"], "task-linear-ingress-1")

    def test_rejects_missing_required_issue_fields(self) -> None:
        payload = _linear_ingress_payload()
        del payload["issue"]["title"]

        with self.assertRaises(LinearIngressInputError):
            translate_linear_submission_payload(payload)

    def test_rejects_completion_shaped_fields(self) -> None:
        payload = _linear_ingress_payload()
        payload["claimed_completion"] = True
        with self.assertRaisesRegex(LinearIngressInputError, "cannot claim completion"):
            translate_linear_submission_payload(payload)

        payload = _linear_ingress_payload()
        payload["acceptance_criteria_satisfied"] = True
        with self.assertRaisesRegex(LinearIngressInputError, "cannot assert acceptance_criteria_satisfied"):
            translate_linear_submission_payload(payload)

        payload = _linear_ingress_payload()
        payload["runtime_facts"] = {"attempt_count": 1}
        with self.assertRaisesRegex(LinearIngressInputError, "cannot submit runtime_facts"):
            translate_linear_submission_payload(payload)

    def test_rejects_execution_artifacts_completion_evidence_and_runtime_status(self) -> None:
        payload = _linear_ingress_payload()
        payload["linked_artifacts"] = [{"id": "artifact-pr-1", "type": "pull_request"}]
        with self.assertRaisesRegex(LinearIngressInputError, "cannot attach repository execution artifacts"):
            translate_linear_submission_payload(payload)

        payload = _linear_ingress_payload()
        payload["completion_evidence"] = {"status": "satisfied"}
        with self.assertRaisesRegex(LinearIngressInputError, "cannot submit completion_evidence"):
            translate_linear_submission_payload(payload)

        payload = _linear_ingress_payload()
        payload["task_status"] = "completed"
        with self.assertRaisesRegex(LinearIngressInputError, "task_status must be one of"):
            translate_linear_submission_payload(payload)


if __name__ == "__main__":
    unittest.main()
