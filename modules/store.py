"""Minimal persistence scaffolding for TaskEnvelope and evaluation records."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from modules.evaluation import HarnessEvaluationRequest, HarnessEvaluationResult

TaskEnvelope = dict[str, object]


class StoreError(ValueError):
    """Base error for Harness persistence operations."""


class TaskEnvelopeNotFoundError(StoreError):
    """Raised when a requested TaskEnvelope does not exist in the store."""


class TaskEnvelopeAlreadyExistsError(StoreError):
    """Raised when a task create is attempted with an existing TaskEnvelope id."""


class EvaluationRecordNotFoundError(StoreError):
    """Raised when a requested evaluation record does not exist in the store."""


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _jsonable(val) for key, val in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _jsonable(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


@dataclass(frozen=True)
class EvaluationRecord:
    """Append-only persisted evaluation record associated with one task."""

    evaluation_id: str
    task_id: str
    recorded_at: str
    request: dict[str, Any]
    result: dict[str, Any]


class TaskEnvelopeStore(Protocol):
    """Storage boundary for canonical TaskEnvelope records."""

    def create_task(self, task_envelope: TaskEnvelope) -> TaskEnvelope: ...

    def put_task(self, task_envelope: TaskEnvelope) -> TaskEnvelope: ...

    def get_task(self, task_id: str) -> TaskEnvelope: ...

    def update_task(self, task_envelope: TaskEnvelope) -> TaskEnvelope: ...


class EvaluationRecordStore(Protocol):
    """Storage boundary for persisted evaluation records."""

    def put_evaluation_record(
        self,
        *,
        request: HarnessEvaluationRequest,
        result: HarnessEvaluationResult,
        evaluation_id: str | None = None,
        recorded_at: str | None = None,
    ) -> EvaluationRecord: ...

    def list_evaluation_records(self, task_id: str) -> tuple[EvaluationRecord, ...]: ...


class FileBackedHarnessStore(TaskEnvelopeStore, EvaluationRecordStore):
    """JSON-file local store for canonical tasks and evaluation records.

    This is local-development scaffolding, not the final production storage strategy.
    """

    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)
        self.tasks_dir = self.root_dir / "tasks"
        self.evaluations_dir = self.root_dir / "evaluations"
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.evaluations_dir.mkdir(parents=True, exist_ok=True)

    def _task_path(self, task_id: str) -> Path:
        return self.tasks_dir / f"{task_id}.json"

    def _evaluation_task_dir(self, task_id: str) -> Path:
        task_dir = self.evaluations_dir / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        return task_dir

    def _evaluation_path(self, task_id: str, evaluation_id: str) -> Path:
        return self._evaluation_task_dir(task_id) / f"{evaluation_id}.json"

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def _read_json(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def put_task(self, task_envelope: TaskEnvelope) -> TaskEnvelope:
        task_id = str(task_envelope["id"])
        self._write_json(self._task_path(task_id), _jsonable(task_envelope))
        return task_envelope

    def create_task(self, task_envelope: TaskEnvelope) -> TaskEnvelope:
        task_id = str(task_envelope["id"])
        path = self._task_path(task_id)
        if path.exists():
            raise TaskEnvelopeAlreadyExistsError(f"TaskEnvelope {task_id!r} already exists")
        self._write_json(path, _jsonable(task_envelope))
        return task_envelope

    def get_task(self, task_id: str) -> TaskEnvelope:
        path = self._task_path(task_id)
        if not path.exists():
            raise TaskEnvelopeNotFoundError(f"TaskEnvelope {task_id!r} was not found")
        return self._read_json(path)

    def update_task(self, task_envelope: TaskEnvelope) -> TaskEnvelope:
        task_id = str(task_envelope["id"])
        if not self._task_path(task_id).exists():
            raise TaskEnvelopeNotFoundError(f"TaskEnvelope {task_id!r} was not found")
        self._write_json(self._task_path(task_id), _jsonable(task_envelope))
        return task_envelope

    def put_evaluation_record(
        self,
        *,
        request: HarnessEvaluationRequest,
        result: HarnessEvaluationResult,
        evaluation_id: str | None = None,
        recorded_at: str | None = None,
    ) -> EvaluationRecord:
        task_id = str(request.task_envelope["id"])
        record = EvaluationRecord(
            evaluation_id=evaluation_id or str(uuid.uuid4()),
            task_id=task_id,
            recorded_at=recorded_at or _iso_now(),
            request=_jsonable(request),
            result=_jsonable(result),
        )
        self._write_json(self._evaluation_path(task_id, record.evaluation_id), _jsonable(record))
        return record

    def list_evaluation_records(self, task_id: str) -> tuple[EvaluationRecord, ...]:
        task_dir = self.evaluations_dir / task_id
        if not task_dir.exists():
            return ()

        records: list[EvaluationRecord] = []
        for path in sorted(task_dir.glob("*.json")):
            payload = self._read_json(path)
            records.append(
                EvaluationRecord(
                    evaluation_id=payload["evaluation_id"],
                    task_id=payload["task_id"],
                    recorded_at=payload["recorded_at"],
                    request=payload["request"],
                    result=payload["result"],
                )
            )
        return tuple(records)


__all__ = [
    "EvaluationRecord",
    "EvaluationRecordNotFoundError",
    "EvaluationRecordStore",
    "FileBackedHarnessStore",
    "StoreError",
    "TaskEnvelopeAlreadyExistsError",
    "TaskEnvelopeNotFoundError",
    "TaskEnvelopeStore",
]
