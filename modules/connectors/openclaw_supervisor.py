"""Thin OpenClaw-side supervision loop over canonical Harness APIs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from .openclaw_harness_spike import OpenClawHarnessSpikeClient


@dataclass(frozen=True)
class OpenClawSupervisionDecision:
    """One canonical attention item enriched with inspection context."""

    task_id: str
    title: str
    current_status: str
    attention_type: str
    suggested_action: str
    reason: str
    stale: bool
    last_activity_at: str | None
    read_model_status: int
    timeline_status: int
    evaluation_history_count: int
    timeline_event_count: int
    can_autonomously_dispatch: bool
    proposed_dispatch_payload: dict[str, Any] | None
    can_request_execution_substrate: bool
    proposed_execution_substrate_intent: dict[str, Any] | None
    can_autonomously_sync: bool
    proposed_sync_payload: dict[str, Any] | None
    read_model: dict[str, Any]
    timeline: dict[str, Any]
    evaluations: dict[str, Any]


@dataclass(frozen=True)
class OpenClawSupervisionActionResult:
    """Outcome of one supervisor decision during a cycle."""

    task_id: str
    attention_type: str
    action_status: str
    http_status: int | None
    action: str | None
    resulting_task_status: str | None


@dataclass(frozen=True)
class OpenClawSupervisionCycleResult:
    """Structured result of one supervision polling cycle."""

    queue_status: int
    generated_at: str | None
    decision_count: int
    decisions: tuple[OpenClawSupervisionDecision, ...]
    action_results: tuple[OpenClawSupervisionActionResult, ...]


class OpenClawHarnessSupervisor:
    """OpenClaw-side supervisor that polls canonical Harness attention state."""

    def __init__(self, base_url: str) -> None:
        self.client = OpenClawHarnessSpikeClient(base_url)

    def _can_autonomously_dispatch(self, entry: dict[str, Any]) -> bool:
        attention_type = str(entry.get("attention_type") or "")
        suggested_action = str(entry.get("suggested_action") or "")
        dispatchable_attention = (
            (attention_type == "retryable_failure" and suggested_action == "retry_or_redispatch")
            or (attention_type == "stale_active_task" and suggested_action == "investigate_staleness")
        )
        dispatchable_statuses = {"dispatch_ready", "assigned"} if attention_type == "stale_active_task" else {
            "dispatch_ready",
            "assigned",
            "blocked",
        }
        return (
            dispatchable_attention
            and str(entry.get("current_status") or "") in dispatchable_statuses
            and str(entry.get("clarification_status") or "") != "required"
            and str(entry.get("review_status") or "") != "requested"
        )

    @staticmethod
    def _parse_repository_from_location(location: Any) -> tuple[str | None, str | None, str | None]:
        if not isinstance(location, str) or not location.strip():
            return None, None, None
        parsed = urlparse(location)
        if parsed.netloc not in {"github.com", "www.github.com"}:
            return None, None, None
        path_parts = [part for part in parsed.path.split("/") if part]
        if len(path_parts) < 2:
            return None, None, None
        return "github.com", path_parts[0], path_parts[1]

    def _sync_payload(self, *, task_id: str, read_model: dict[str, Any]) -> dict[str, Any] | None:
        execution_summary = read_model.get("execution_summary") if isinstance(read_model.get("execution_summary"), dict) else {}
        references = (
            execution_summary.get("latest_artifact_references")
            if isinstance(execution_summary.get("latest_artifact_references"), list)
            else []
        )
        repository_host = repository_owner = repository_name = None
        branch_name = commit_sha = None
        pull_request_url = None
        pull_request_number = None
        pull_request_state = None

        for reference in references:
            if not isinstance(reference, dict):
                continue
            metadata = reference.get("metadata") if isinstance(reference.get("metadata"), dict) else {}
            if metadata.get("repository_host") is not None and repository_host is None:
                repository_host = str(metadata["repository_host"])
            if metadata.get("repository_owner") is not None and repository_owner is None:
                repository_owner = str(metadata["repository_owner"])
            if metadata.get("repository_name") is not None and repository_name is None:
                repository_name = str(metadata["repository_name"])
            parsed_host, parsed_owner, parsed_name = self._parse_repository_from_location(reference.get("location"))
            repository_host = repository_host or parsed_host
            repository_owner = repository_owner or parsed_owner
            repository_name = repository_name or parsed_name
            if metadata.get("branch_name") is not None and branch_name is None:
                branch_name = str(metadata["branch_name"])
            if reference.get("commit_sha") is not None and commit_sha is None:
                commit_sha = str(reference["commit_sha"])
            if metadata.get("commit_sha") is not None and commit_sha is None:
                commit_sha = str(metadata["commit_sha"])
            if str(reference.get("artifact_type") or "") == "pull_request":
                if reference.get("location") is not None and pull_request_url is None:
                    pull_request_url = str(reference["location"])
                if metadata.get("pull_request_number") is not None and pull_request_number is None:
                    pull_request_number = int(metadata["pull_request_number"])
                if metadata.get("state") is not None and pull_request_state is None:
                    pull_request_state = str(metadata["state"])

        if not repository_owner or not repository_name or not branch_name:
            return None

        github_payload: dict[str, Any] = {
            "repository": {
                "host": repository_host or "github.com",
                "owner": repository_owner,
                "name": repository_name,
            },
            "branch": {
                "name": branch_name,
                "head_commit_sha": commit_sha,
            },
        }
        if commit_sha:
            github_payload["commit"] = {"sha": commit_sha}
        if pull_request_url or pull_request_number is not None:
            github_payload["pull_request"] = {
                "number": pull_request_number,
                "url": pull_request_url,
                "state": pull_request_state or "open",
            }

        return {
            "task_id": task_id,
            "github": github_payload,
        }

    @staticmethod
    def _dispatch_payload(*, attention_type: str, executor: str) -> dict[str, Any]:
        return {
            "request": {
                "executor": executor,
                "dispatch_mode": "manual",
                "dispatch_trigger": "openclaw_supervision_loop",
                "dispatch_reason": f"OpenClaw supervision loop redispatch for {attention_type}.",
                "execution_parameters": {
                    "initiator": "openclaw_supervision_loop",
                    "attention_type": attention_type,
                },
            }
        }

    def _build_decision(self, entry: dict[str, Any], *, executor: str) -> OpenClawSupervisionDecision:
        task_id = str(entry.get("task_id") or "")
        read_model_status, read_model_payload = self.client.get_task_read_model(task_id)
        timeline_status, timeline_payload = self.client.get_task_timeline(task_id)
        evaluations_status, evaluations_payload = self.client.get_evaluation_history(task_id)
        if read_model_status >= 400 or timeline_status >= 400 or evaluations_status >= 400:
            raise RuntimeError(f"OpenClaw supervision inspection failed for {task_id}")

        can_dispatch = self._can_autonomously_dispatch(entry)
        sync_payload = None
        can_sync = False
        if str(entry.get("attention_type") or "") == "github_sync_required":
            sync_payload = self._sync_payload(task_id=task_id, read_model=read_model_payload.get("task") or {})
            can_sync = sync_payload is not None
        return OpenClawSupervisionDecision(
            task_id=task_id,
            title=str(entry.get("title") or ""),
            current_status=str(entry.get("current_status") or ""),
            attention_type=str(entry.get("attention_type") or ""),
            suggested_action=str(entry.get("suggested_action") or ""),
            reason=str(entry.get("reason") or ""),
            stale=bool(entry.get("stale")),
            last_activity_at=str(entry.get("last_activity_at")) if entry.get("last_activity_at") is not None else None,
            read_model_status=read_model_status,
            timeline_status=timeline_status,
            evaluation_history_count=len(evaluations_payload.get("evaluations", ())),
            timeline_event_count=int(timeline_payload.get("event_count") or 0),
            can_autonomously_dispatch=can_dispatch,
            proposed_dispatch_payload=(
                self._dispatch_payload(attention_type=str(entry.get("attention_type") or ""), executor=executor)
                if can_dispatch
                else None
            ),
            can_request_execution_substrate=can_dispatch
            and isinstance(entry.get("execution_substrate_intent"), dict),
            proposed_execution_substrate_intent=(
                dict(entry["execution_substrate_intent"])
                if can_dispatch and isinstance(entry.get("execution_substrate_intent"), dict)
                else None
            ),
            can_autonomously_sync=can_sync,
            proposed_sync_payload=sync_payload,
            read_model=read_model_payload,
            timeline=timeline_payload,
            evaluations=evaluations_payload,
        )

    @staticmethod
    def _non_dispatch_action_status(attention_type: str) -> str:
        return {
            "review_required": "manual_review_required",
            "clarification_required": "clarification_required",
            "invalid_execution_attempt": "fresh_proof_or_rework_required",
            "github_sync_required": "github_sync_required",
            "retryable_failure": "retryable_failure_observed",
            "stale_active_task": "staleness_investigation_required",
        }.get(attention_type, "attention_observed")

    def run_cycle(
        self,
        *,
        allow_redispatch: bool = False,
        allow_sync: bool = False,
        executor: str = "codex",
        allow_legacy_direct_dispatch: bool = False,
    ) -> OpenClawSupervisionCycleResult:
        queue_status, queue_payload = self.client.get_supervision_queue()
        if queue_status >= 400:
            raise RuntimeError(f"OpenClaw supervision queue fetch failed: {queue_payload}")
        queue = queue_payload.get("queue")
        if not isinstance(queue, list):
            raise RuntimeError("OpenClaw supervision queue payload is malformed")

        decisions = tuple(self._build_decision(entry, executor=executor) for entry in queue if isinstance(entry, dict))
        action_results: list[OpenClawSupervisionActionResult] = []
        for decision in decisions:
            if allow_sync and decision.can_autonomously_sync and decision.proposed_sync_payload is not None:
                sync_status, sync_payload = self.client.sync_github(decision.proposed_sync_payload)
                action_results.append(
                    OpenClawSupervisionActionResult(
                        task_id=decision.task_id,
                        attention_type=decision.attention_type,
                        action_status="github_sync_triggered" if sync_status < 400 else "github_sync_failed",
                        http_status=sync_status,
                        action=(
                            str(sync_payload.get("action"))
                            if isinstance(sync_payload, dict) and sync_payload.get("action") is not None
                            else None
                        ),
                        resulting_task_status=(
                            str((sync_payload.get("task_envelope") or {}).get("status"))
                            if isinstance(sync_payload, dict)
                            and isinstance(sync_payload.get("task_envelope"), dict)
                            and (sync_payload.get("task_envelope") or {}).get("status") is not None
                            else None
                        ),
                    )
                )
                continue
            if (
                allow_redispatch
                and decision.can_request_execution_substrate
                and decision.proposed_execution_substrate_intent is not None
                and not allow_legacy_direct_dispatch
            ):
                action_results.append(
                    OpenClawSupervisionActionResult(
                        task_id=decision.task_id,
                        attention_type=decision.attention_type,
                        action_status="execution_substrate_dispatch_intent",
                        http_status=None,
                        action="submit_to_execution_substrate",
                        resulting_task_status=decision.current_status,
                    )
                )
                continue

            if (
                allow_redispatch
                and allow_legacy_direct_dispatch
                and decision.can_autonomously_dispatch
                and decision.proposed_dispatch_payload is not None
            ):
                dispatch_status, dispatch_payload = self.client.dispatch_task(
                    decision.task_id,
                    payload=decision.proposed_dispatch_payload,
                )
                action_results.append(
                    OpenClawSupervisionActionResult(
                        task_id=decision.task_id,
                        attention_type=decision.attention_type,
                        action_status="redispatch_triggered" if dispatch_status < 400 else "redispatch_failed",
                        http_status=dispatch_status,
                        action=(
                            str(dispatch_payload.get("action"))
                            if isinstance(dispatch_payload, dict) and dispatch_payload.get("action") is not None
                            else None
                        ),
                        resulting_task_status=(
                            str((dispatch_payload.get("task_envelope") or {}).get("status"))
                            if isinstance(dispatch_payload, dict)
                            and isinstance(dispatch_payload.get("task_envelope"), dict)
                            and (dispatch_payload.get("task_envelope") or {}).get("status") is not None
                            else None
                        ),
                    )
                )
                continue

            action_results.append(
                OpenClawSupervisionActionResult(
                    task_id=decision.task_id,
                    attention_type=decision.attention_type,
                    action_status=self._non_dispatch_action_status(decision.attention_type),
                    http_status=None,
                    action=None,
                    resulting_task_status=decision.current_status,
                )
            )

        return OpenClawSupervisionCycleResult(
            queue_status=queue_status,
            generated_at=(
                str(queue_payload.get("generated_at"))
                if queue_payload.get("generated_at") is not None
                else None
            ),
            decision_count=len(decisions),
            decisions=decisions,
            action_results=tuple(action_results),
        )


__all__ = [
    "OpenClawHarnessSupervisor",
    "OpenClawSupervisionActionResult",
    "OpenClawSupervisionCycleResult",
    "OpenClawSupervisionDecision",
]
