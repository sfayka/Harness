"""Persistence implementations for canonical TaskEnvelope and evaluation records."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, cast

from modules.evaluation import HarnessEvaluationRequest, HarnessEvaluationResult

try:
    import psycopg
    from psycopg.errors import UniqueViolation
    from psycopg.types.json import Jsonb
except ImportError:  # pragma: no cover - exercised when postgres backend is requested without dependency.
    psycopg = None
    UniqueViolation = None
    Jsonb = None

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

    def list_tasks(self) -> tuple[TaskEnvelope, ...]: ...

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


class HarnessStore(TaskEnvelopeStore, EvaluationRecordStore, Protocol):
    """Combined persistence boundary for canonical task and evaluation state."""


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
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def _read_json(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def put_task(self, task_envelope: TaskEnvelope) -> TaskEnvelope:
        task_id = str(task_envelope["id"])
        self._write_json(self._task_path(task_id), _jsonable(task_envelope))
        return task_envelope

    def list_tasks(self) -> tuple[TaskEnvelope, ...]:
        tasks: list[TaskEnvelope] = []
        for path in self.tasks_dir.glob("*.json"):
            tasks.append(self._read_json(path))
        tasks.sort(
            key=lambda task: (
                str((task.get("timestamps") or {}).get("updated_at") or ""),
                str(task.get("id") or ""),
            ),
            reverse=True,
        )
        return tuple(tasks)

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
        for path in task_dir.glob("*.json"):
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
        records.sort(key=lambda record: (record.recorded_at, record.evaluation_id))
        return tuple(records)


def _parse_iso_timestamp(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


class PostgresHarnessStore(HarnessStore):
    """Postgres-backed store for canonical tasks and append-only evaluation history."""

    def __init__(self, database_url: str) -> None:
        if psycopg is None or Jsonb is None or UniqueViolation is None:
            raise StoreError("psycopg is required for HARNESS_STORE_BACKEND=postgres")
        if not database_url.strip():
            raise StoreError("DATABASE_URL is required for HARNESS_STORE_BACKEND=postgres")
        self.database_url = database_url

    def _connect(self):
        return psycopg.connect(self.database_url)

    def create_task(self, task_envelope: TaskEnvelope) -> TaskEnvelope:
        task_id = str(task_envelope["id"])
        task_payload = cast(dict[str, Any], _jsonable(task_envelope))
        timestamps = dict(task_payload.get("timestamps") or {})
        created_at = _parse_iso_timestamp(cast(str | None, timestamps.get("created_at")))
        updated_at = _parse_iso_timestamp(cast(str | None, timestamps.get("updated_at")))

        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO tasks (task_id, task_json, created_at, updated_at)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (task_id, Jsonb(task_payload), created_at, updated_at),
                    )
        except UniqueViolation as error:
            raise TaskEnvelopeAlreadyExistsError(f"TaskEnvelope {task_id!r} already exists") from error
        return task_envelope

    def list_tasks(self) -> tuple[TaskEnvelope, ...]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT task_json
                    FROM tasks
                    ORDER BY updated_at DESC, task_id DESC
                    """
                )
                return tuple(cast(TaskEnvelope, row[0]) for row in cursor.fetchall())

    def put_task(self, task_envelope: TaskEnvelope) -> TaskEnvelope:
        task_id = str(task_envelope["id"])
        task_payload = cast(dict[str, Any], _jsonable(task_envelope))
        timestamps = dict(task_payload.get("timestamps") or {})
        created_at = _parse_iso_timestamp(cast(str | None, timestamps.get("created_at")))
        updated_at = _parse_iso_timestamp(cast(str | None, timestamps.get("updated_at")))

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO tasks (task_id, task_json, created_at, updated_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (task_id) DO UPDATE
                    SET task_json = EXCLUDED.task_json,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (task_id, Jsonb(task_payload), created_at, updated_at),
                )
        return task_envelope

    def get_task(self, task_id: str) -> TaskEnvelope:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT task_json FROM tasks WHERE task_id = %s", (task_id,))
                row = cursor.fetchone()
        if row is None:
            raise TaskEnvelopeNotFoundError(f"TaskEnvelope {task_id!r} was not found")
        return cast(TaskEnvelope, row[0])

    def update_task(self, task_envelope: TaskEnvelope) -> TaskEnvelope:
        task_id = str(task_envelope["id"])
        task_payload = cast(dict[str, Any], _jsonable(task_envelope))
        timestamps = dict(task_payload.get("timestamps") or {})
        updated_at = _parse_iso_timestamp(cast(str | None, timestamps.get("updated_at")))

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE tasks
                    SET task_json = %s,
                        updated_at = %s
                    WHERE task_id = %s
                    """,
                    (Jsonb(task_payload), updated_at, task_id),
                )
                if cursor.rowcount == 0:
                    raise TaskEnvelopeNotFoundError(f"TaskEnvelope {task_id!r} was not found")
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
            request=cast(dict[str, Any], _jsonable(request)),
            result=cast(dict[str, Any], _jsonable(result)),
        )

        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO evaluation_records (
                            evaluation_id,
                            task_id,
                            recorded_at,
                            request_json,
                            result_json
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            record.evaluation_id,
                            record.task_id,
                            _parse_iso_timestamp(record.recorded_at),
                            Jsonb(record.request),
                            Jsonb(record.result),
                        ),
                    )
        except UniqueViolation as error:
            raise StoreError(f"EvaluationRecord {record.evaluation_id!r} already exists") from error
        return record

    def list_evaluation_records(self, task_id: str) -> tuple[EvaluationRecord, ...]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT evaluation_id, task_id, recorded_at, request_json, result_json
                    FROM evaluation_records
                    WHERE task_id = %s
                    ORDER BY recorded_at ASC, evaluation_id ASC
                    """,
                    (task_id,),
                )
                rows = cursor.fetchall()

        return tuple(
            EvaluationRecord(
                evaluation_id=str(row[0]),
                task_id=str(row[1]),
                recorded_at=cast(datetime, row[2]).astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                request=cast(dict[str, Any], row[3]),
                result=cast(dict[str, Any], row[4]),
            )
            for row in rows
        )


def build_harness_store(
    *,
    store_backend: str | None = None,
    store_root: str | Path | None = None,
    database_url: str | None = None,
) -> HarnessStore:
    """Construct the configured persistence backend for the API process."""

    backend = (store_backend or os.environ.get("HARNESS_STORE_BACKEND") or "file").strip().lower()
    if backend == "file":
        resolved_store_root = Path(store_root or os.environ.get("HARNESS_STORE_ROOT") or ".harness-store")
        return FileBackedHarnessStore(resolved_store_root)
    if backend == "postgres":
        resolved_database_url = database_url or os.environ.get("DATABASE_URL") or ""
        return PostgresHarnessStore(resolved_database_url)
    raise StoreError(f"Unsupported HARNESS_STORE_BACKEND {backend!r}; expected 'file' or 'postgres'")


__all__ = [
    "EvaluationRecord",
    "EvaluationRecordNotFoundError",
    "EvaluationRecordStore",
    "FileBackedHarnessStore",
    "HarnessStore",
    "PostgresHarnessStore",
    "StoreError",
    "TaskEnvelopeAlreadyExistsError",
    "TaskEnvelopeNotFoundError",
    "TaskEnvelopeStore",
    "build_harness_store",
]
