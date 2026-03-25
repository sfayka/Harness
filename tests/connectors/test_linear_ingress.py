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
    canonical_request = build_demo_request("accepted_completion")
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
            "id": "workflow_done",
            "name": "completed",
            "type": "completed",
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
        "task_status": task["status"],
        "assigned_executor": deepcopy(task["assigned_executor"]),
        "acceptance_criteria": deepcopy(task["acceptance_criteria"]),
        "linked_artifacts": deepcopy(task["artifacts"]["items"]),
        "completion_evidence": deepcopy(task["artifacts"]["completion_evidence"]),
        "external_facts": {
            "expected_code_context": deepcopy(external_facts.expected_code_context),
            "github_facts": deepcopy(external_facts.github_facts),
        },
        "claimed_completion": True,
        "acceptance_criteria_satisfied": True,
        "runtime_facts": _to_jsonable(canonical_request.runtime_facts),
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
        self.assertEqual(task["extensions"]["linear"]["issue_identifier"], "HAR-901")
        self.assertEqual(len(task["artifacts"]["items"]), 2)
        self.assertEqual(linear_facts["issue_id"], "lin-ingress-1")
        self.assertEqual(linear_facts["issue_key"], "HAR-901")
        self.assertEqual(linear_facts["state"], "completed")
        self.assertEqual(linear_facts["task_reference"]["harness_task_id"], "task-linear-ingress-1")

    def test_rejects_missing_required_issue_fields(self) -> None:
        payload = _linear_ingress_payload()
        del payload["issue"]["title"]

        with self.assertRaises(LinearIngressInputError):
            translate_linear_submission_payload(payload)


if __name__ == "__main__":
    unittest.main()
