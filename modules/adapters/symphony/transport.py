"""Disabled live transport boundary for Symphony-compatible execution.

Harness can render Symphony-compatible handoffs today, but live execution
transport is not enabled from this repository yet. This module gives future
transport work an explicit integration point without letting preview code grow
side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from modules.adapters.symphony.execution_substrate_adapter import (
    SymphonyExecutionSubstrateAdapter,
)
from modules.contracts.execution_substrate import ExecutionSubstrateIntent


class SymphonyTransportDisabledError(RuntimeError):
    """Raised when code tries to dispatch live Symphony work before enablement."""


@dataclass(frozen=True)
class SymphonyTransportResult:
    """Result shape for a Symphony transport attempt."""

    status: str
    dispatch_enabled: bool
    live_dispatch_enabled: bool
    completion_authority: str
    runner_completion_is_truth: bool
    handoff: dict[str, Any]
    message: str


@dataclass(frozen=True)
class DisabledSymphonyExecutionTransport:
    """Render handoffs but refuse live Symphony dispatch."""

    harness_base_url: str
    dispatch_enabled: bool = False
    live_dispatch_enabled: bool = False

    def preview(self, intent: ExecutionSubstrateIntent) -> SymphonyTransportResult:
        """Render the handoff that would be submitted to a live transport later."""

        handoff = SymphonyExecutionSubstrateAdapter(
            harness_base_url=self.harness_base_url,
        ).render_handoff(intent).to_dict()
        return SymphonyTransportResult(
            status="disabled",
            dispatch_enabled=False,
            live_dispatch_enabled=False,
            completion_authority="harness_verification",
            runner_completion_is_truth=False,
            handoff=handoff,
            message=(
                "Symphony live dispatch is disabled. Harness may render handoffs, "
                "but it must not start Symphony or trust runner completion."
            ),
        )

    def dispatch(self, intent: ExecutionSubstrateIntent) -> SymphonyTransportResult:
        """Reject live dispatch until Harness has an explicit transport policy."""

        preview = self.preview(intent)
        raise SymphonyTransportDisabledError(preview.message)


__all__ = [
    "DisabledSymphonyExecutionTransport",
    "SymphonyTransportDisabledError",
    "SymphonyTransportResult",
]
