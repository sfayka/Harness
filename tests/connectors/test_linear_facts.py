from __future__ import annotations

import unittest

from modules.connectors import LinearConnectorInputError, translate_linear_facts
from modules.contracts.task_envelope_external_facts import LinearFacts
from modules.contracts.task_envelope_reconciliation import (
    ReconciliationEvaluationInput,
    ReconciliationInputError,
    ReconciliationOutcome,
    evaluate_reconciliation,
)


def _base_task_envelope() -> dict:
    return {
        "id": "task-linear-1",
        "title": "Reconcile Linear facts",
        "description": "Task used to validate Linear connector scaffolding.",
        "origin": {
            "source_system": "openclaw",
            "source_type": "ingress_request",
            "source_id": "req-linear-1",
            "ingress_id": None,
            "ingress_name": "OpenClaw",
            "requested_by": None,
        },
        "status": "completed",
        "timestamps": {
            "created_at": "2026-03-24T17:00:00Z",
            "updated_at": "2026-03-24T17:10:00Z",
            "completed_at": "2026-03-24T17:10:00Z",
        },
        "status_history": [],
        "objective": {
            "summary": "Validate Linear connector translation behavior.",
            "deliverable_type": "code_change",
            "success_signal": "Linear connector outputs normalized facts consumed by reconciliation.",
        },
        "constraints": [],
        "acceptance_criteria": [
            {
                "id": "ac-1",
                "description": "Linear task facts are available for reconciliation.",
                "required": True,
            }
        ],
        "parent_task_id": None,
        "child_task_ids": [],
        "dependencies": [],
        "assigned_executor": None,
        "required_capabilities": [],
        "priority": "normal",
        "artifacts": {
            "items": [],
            "completion_evidence": {
                "policy": "required",
                "status": "satisfied",
                "required_artifact_types": ["pull_request"],
                "validated_artifact_ids": ["artifact-pr-1"],
                "validation_method": "external_reconciliation",
                "validated_at": "2026-03-24T17:09:00Z",
                "validator": {
                    "source_system": "harness",
                    "source_type": "verification",
                    "source_id": "verification-run-linear-1",
                    "captured_by": "linear-sync",
                },
            },
        },
        "observability": {
            "errors": [],
            "retries": {
                "attempt_count": 0,
                "max_attempts": 0,
                "last_retry_at": None,
            },
            "execution_metadata": {},
        },
    }


class LinearConnectorTranslationTests(unittest.TestCase):
    def test_translates_linear_payload_into_normalized_facts(self) -> None:
        facts = translate_linear_facts(
            {
                "issue": {
                    "id": "lin_123",
                    "identifier": "HAR-14",
                },
                "state": {
                    "id": "workflow_done",
                    "name": "completed",
                    "type": "completed",
                },
                "project": {
                    "id": "project_1",
                    "name": "Harness rollout",
                },
                "task_reference": {
                    "harness_task_id": "task-linear-1",
                    "external_ref": "HAR-14",
                },
                "reasons": ["Linear sync succeeded"],
            }
        )

        self.assertEqual(
            facts,
            LinearFacts(
                record_found=True,
                issue_id="lin_123",
                issue_key="HAR-14",
                state="completed",
                workflow=facts.workflow,
                project=facts.project,
                task_reference=facts.task_reference,
                reasons=("Linear sync succeeded",),
            ),
        )
        self.assertEqual(facts.workflow.workflow_id, "workflow_done")
        self.assertEqual(facts.workflow.workflow_name, "completed")
        self.assertEqual(facts.workflow.state_type, "completed")
        self.assertEqual(facts.project.project_id, "project_1")
        self.assertEqual(facts.task_reference.harness_task_id, "task-linear-1")

    def test_rejects_string_state_without_workflow_object(self) -> None:
        with self.assertRaisesRegex(LinearConnectorInputError, "record_found=true requires workflow/state"):
            translate_linear_facts(
                {
                    "issue": {"id": "lin_124"},
                    "state": "in_progress",
                }
            )

    def test_rejects_missing_issue_identity(self) -> None:
        with self.assertRaises(LinearConnectorInputError):
            translate_linear_facts(
                {
                    "state": {
                        "id": "workflow_todo",
                        "name": "planned",
                    }
                }
            )

    def test_rejects_non_sequence_reasons(self) -> None:
        with self.assertRaises(LinearConnectorInputError):
            translate_linear_facts(
                {
                    "issue": {"id": "lin_125"},
                    "state": "planned",
                    "reasons": "sync complete",
                }
            )

    def test_rejects_record_not_found_with_resolved_record_fields(self) -> None:
        with self.assertRaises(LinearConnectorInputError):
            translate_linear_facts(
                {
                    "record_found": False,
                    "issue": {"id": "lin_126"},
                    "state": "completed",
                }
            )

    def test_reconciliation_consumes_translated_linear_facts_directly(self) -> None:
        result = evaluate_reconciliation(
            _base_task_envelope(),
            reconciliation_input=ReconciliationEvaluationInput(
                claimed_completion=True,
                evidence_policy="required",
                evidence_status="satisfied",
                linear_facts=translate_linear_facts(
                    {
                        "issue": {
                            "id": "lin_127",
                            "identifier": "HAR-15",
                        },
                        "state": {
                            "id": "workflow_done",
                            "name": "completed",
                            "type": "completed",
                        },
                    }
                ),
            ),
        )

        self.assertEqual(result.outcome, ReconciliationOutcome.NO_MISMATCH)

    def test_reconciliation_rejects_malformed_normalized_linear_facts_at_boundary(self) -> None:
        with self.assertRaises(ReconciliationInputError):
            evaluate_reconciliation(
                _base_task_envelope(),
                reconciliation_input=ReconciliationEvaluationInput(
                    claimed_completion=True,
                    evidence_policy="required",
                    evidence_status="satisfied",
                    linear_facts=LinearFacts(
                        record_found=True,
                        issue_id="lin_128",
                        state=None,
                        workflow=None,
                    ),
                ),
            )


if __name__ == "__main__":
    unittest.main()
