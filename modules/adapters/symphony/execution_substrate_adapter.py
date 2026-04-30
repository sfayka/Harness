"""Symphony-compatible execution substrate handoff adapter.

This module deliberately renders a handoff payload only. It does not start
Symphony, poll Linear, mutate GitHub, or claim Harness lifecycle completion.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from modules.contracts.execution_substrate import (
    ExecutionSubstrateIntent,
    execution_substrate_intent_to_dict,
    validate_execution_substrate_intent,
)


@dataclass(frozen=True)
class SymphonyHandoffPayload:
    """Local representation of the payload Harness can hand to Symphony."""

    adapter: str
    mode: str
    intent: dict[str, Any]
    harness_boundary: dict[str, Any]
    runner_policy: dict[str, Any]
    callback: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the handoff payload for tests, logs, and future transports."""

        return asdict(self)


@dataclass(frozen=True)
class SymphonyExecutionSubstrateAdapter:
    """Render validated Harness intents into Symphony-compatible handoff payloads."""

    harness_base_url: str
    adapter_name: str = "symphony-execution-substrate"

    def render_handoff(self, intent: ExecutionSubstrateIntent) -> SymphonyHandoffPayload:
        """Render an inert runner handoff for a validated execution-substrate intent."""

        validated = validate_execution_substrate_intent(intent)
        intent_payload = execution_substrate_intent_to_dict(validated)
        events_endpoint = intent_payload["events_endpoint"]
        return SymphonyHandoffPayload(
            adapter=self.adapter_name,
            mode="render_only",
            intent=intent_payload,
            harness_boundary={
                "completion_authority": "harness_verification",
                "advisory_only": True,
                "runner_completion_is_truth": False,
                "artifact_verification_required": True,
            },
            runner_policy={
                "substrate_kind": intent_payload["substrate_kind"],
                "allowed_intent_type": intent_payload["intent_type"],
                "prohibited_actions": list(intent_payload["prohibited_actions"]),
            },
            callback={
                "events_endpoint": events_endpoint,
                "events_url": f"{self.harness_base_url.rstrip('/')}{events_endpoint}",
                "event_contract": "execution_substrate_event.v1",
            },
            metadata={
                "task_id": intent_payload["task_id"],
                "source": intent_payload["source"],
                "safe_to_execute_live": False,
            },
        )


__all__ = [
    "SymphonyExecutionSubstrateAdapter",
    "SymphonyHandoffPayload",
]
