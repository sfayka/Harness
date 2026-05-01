"""Persistence implementations for canonical TaskEnvelope and evaluation records."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterator, Protocol, cast

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

POSTGRES_DATABASE_URL_ENV_VARS = (
    "DATABASE_URL",
    "POSTGRES_URL",
    "POSTGRES_URL_NON_POOLING",
    "POSTGRES_PRISMA_URL",
    "POSTGRES_URL_NO_SSL",
)
STORE_BACKEND_ENV_VARS = ("PROOFLINE_STORE_BACKEND", "HARNESS_STORE_BACKEND")
STORE_ROOT_ENV_VARS = ("PROOFLINE_STORE_ROOT", "HARNESS_STORE_ROOT")
SQLITE_DATABASE_PATH_ENV_VAR = "HARNESS_SQLITE_PATH"
SQLITE_DATABASE_PATH_ENV_VARS = ("PROOFLINE_SQLITE_PATH", SQLITE_DATABASE_PATH_ENV_VAR)
SQLITE_SCHEMA_VERSION = 1
SQLITE_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS harness_schema_version (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        version INTEGER NOT NULL,
        applied_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tasks (
        task_id TEXT PRIMARY KEY,
        task_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_tasks_updated_at_desc
        ON tasks (updated_at DESC, task_id DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS evaluation_records (
        evaluation_id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
        recorded_at TEXT NOT NULL,
        request_json TEXT NOT NULL,
        result_json TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_evaluation_records_task_recorded_at
        ON evaluation_records (task_id, recorded_at, evaluation_id)
    """,
)


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


def _json_dump(value: Any) -> str:
    return json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"))


def _json_load_dict(value: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(value))


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

    def list_evaluation_records_for_tasks(
        self, task_ids: tuple[str, ...]
    ) -> dict[str, tuple[EvaluationRecord, ...]]: ...


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

    def list_evaluation_records_for_tasks(self, task_ids: tuple[str, ...]) -> dict[str, tuple[EvaluationRecord, ...]]:
        grouped_records: dict[str, tuple[EvaluationRecord, ...]] = {}
        for task_id in task_ids:
            grouped_records[task_id] = self.list_evaluation_records(task_id)
        return grouped_records


def _parse_iso_timestamp(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _normalized_timestamp(value: str | None) -> str:
    return _parse_iso_timestamp(value).isoformat().replace("+00:00", "Z")


def resolve_postgres_database_url(database_url: str | None = None) -> str:
    """Resolve a Postgres connection string from explicit input or supported env vars."""

    if database_url is not None and database_url.strip():
        return database_url
    for env_var in POSTGRES_DATABASE_URL_ENV_VARS:
        value = os.environ.get(env_var)
        if value and value.strip():
            return value
    return ""


def _first_configured_env(env_vars: tuple[str, ...]) -> str:
    for env_var in env_vars:
        value = os.environ.get(env_var)
        if value and value.strip():
            return value
    return ""


def resolve_sqlite_database_path(
    database_path: str | Path | None = None,
    *,
    store_root: str | Path | None = None,
    platform_name: str | None = None,
    home: str | Path | None = None,
) -> Path:
    """Resolve the SQLite DB path used by local runtime persistence."""

    if database_path is not None and str(database_path).strip():
        return Path(database_path).expanduser()

    env_path = _first_configured_env(SQLITE_DATABASE_PATH_ENV_VARS)
    if env_path and env_path.strip():
        return Path(env_path).expanduser()

    root = store_root or _first_configured_env(STORE_ROOT_ENV_VARS)
    if root is not None and str(root).strip():
        return Path(root).expanduser() / "harness.db"

    home_path = Path(home).expanduser() if home is not None else Path.home()
    current_platform = platform_name or sys.platform
    if current_platform == "darwin":
        return home_path / "Library" / "Application Support" / "Harness" / "harness.db"

    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home and xdg_data_home.strip():
        return Path(xdg_data_home).expanduser() / "harness" / "harness.db"

    return home_path / ".local" / "share" / "harness" / "harness.db"


def _is_vercel_runtime() -> bool:
    return any(
        (
            os.environ.get("VERCEL_URL"),
            os.environ.get("VERCEL_ENV"),
            os.environ.get("VERCEL_REGION"),
        )
    )


class PostgresHarnessStore(HarnessStore):
    """Postgres-backed store for canonical tasks and append-only evaluation history."""

    def __init__(self, database_url: str) -> None:
        if psycopg is None or Jsonb is None or UniqueViolation is None:
            raise StoreError("psycopg is required for PROOFLINE_STORE_BACKEND=postgres")
        if not database_url.strip():
            supported_envs = ", ".join(POSTGRES_DATABASE_URL_ENV_VARS)
            raise StoreError(
                "A Postgres connection string is required for PROOFLINE_STORE_BACKEND=postgres "
                f"(checked: {supported_envs})"
            )
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

    def list_evaluation_records_for_tasks(self, task_ids: tuple[str, ...]) -> dict[str, tuple[EvaluationRecord, ...]]:
        if not task_ids:
            return {}

        grouped_records: dict[str, list[EvaluationRecord]] = {task_id: [] for task_id in task_ids}

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT evaluation_id, task_id, recorded_at, request_json, result_json
                    FROM evaluation_records
                    WHERE task_id = ANY(%s)
                    ORDER BY task_id ASC, recorded_at ASC, evaluation_id ASC
                    """,
                    (list(task_ids),),
                )
                rows = cursor.fetchall()

        for row in rows:
            task_id = str(row[1])
            grouped_records.setdefault(task_id, []).append(
                EvaluationRecord(
                    evaluation_id=str(row[0]),
                    task_id=task_id,
                    recorded_at=cast(datetime, row[2]).astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                    request=cast(dict[str, Any], row[3]),
                    result=cast(dict[str, Any], row[4]),
                )
            )

        return {task_id: tuple(records) for task_id, records in grouped_records.items()}


class SQLiteHarnessStore(HarnessStore):
    """SQLite-backed local store for canonical tasks and append-only evaluation history."""

    def __init__(self, database_path: str | Path) -> None:
        if not str(database_path).strip():
            raise StoreError("A SQLite database path is required for PROOFLINE_STORE_BACKEND=sqlite")
        self.database_path = Path(database_path).expanduser()
        try:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            self._ensure_schema()
        except sqlite3.Error as error:
            raise StoreError(
                f"SQLite store at {self.database_path} could not be opened or migrated: {error}"
            ) from error
        except OSError as error:
            raise StoreError(
                f"SQLite store directory for {self.database_path} could not be prepared: {error}"
            ) from error

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self.database_path))
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            for statement in SQLITE_SCHEMA_STATEMENTS:
                connection.execute(statement)
            connection.execute(
                """
                INSERT INTO harness_schema_version (id, version, applied_at)
                VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE
                SET version = excluded.version,
                    applied_at = excluded.applied_at
                """,
                (SQLITE_SCHEMA_VERSION, _iso_now()),
            )

    def schema_ready(self) -> bool:
        try:
            with self._connect() as connection:
                table_rows = connection.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table'
                      AND name IN ('tasks', 'evaluation_records', 'harness_schema_version')
                    """
                ).fetchall()
                version_row = connection.execute(
                    "SELECT version FROM harness_schema_version WHERE id = 1"
                ).fetchone()
        except sqlite3.Error:
            return False
        table_names = {str(row["name"]) for row in table_rows}
        return table_names == {"tasks", "evaluation_records", "harness_schema_version"} and bool(
            version_row and int(version_row["version"]) == SQLITE_SCHEMA_VERSION
        )

    def create_task(self, task_envelope: TaskEnvelope) -> TaskEnvelope:
        task_id = str(task_envelope["id"])
        task_payload = cast(dict[str, Any], _jsonable(task_envelope))
        timestamps = dict(task_payload.get("timestamps") or {})
        created_at = _normalized_timestamp(cast(str | None, timestamps.get("created_at")))
        updated_at = _normalized_timestamp(cast(str | None, timestamps.get("updated_at")))
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO tasks (task_id, task_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (task_id, _json_dump(task_payload), created_at, updated_at),
                )
        except sqlite3.IntegrityError as error:
            raise TaskEnvelopeAlreadyExistsError(f"TaskEnvelope {task_id!r} already exists") from error
        return task_envelope

    def list_tasks(self) -> tuple[TaskEnvelope, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT task_json
                FROM tasks
                ORDER BY updated_at DESC, task_id DESC
                """
            ).fetchall()
        return tuple(cast(TaskEnvelope, _json_load_dict(str(row["task_json"]))) for row in rows)

    def put_task(self, task_envelope: TaskEnvelope) -> TaskEnvelope:
        task_id = str(task_envelope["id"])
        task_payload = cast(dict[str, Any], _jsonable(task_envelope))
        timestamps = dict(task_payload.get("timestamps") or {})
        created_at = _normalized_timestamp(cast(str | None, timestamps.get("created_at")))
        updated_at = _normalized_timestamp(cast(str | None, timestamps.get("updated_at")))
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO tasks (task_id, task_json, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE
                SET task_json = excluded.task_json,
                    updated_at = excluded.updated_at
                """,
                (task_id, _json_dump(task_payload), created_at, updated_at),
            )
        return task_envelope

    def get_task(self, task_id: str) -> TaskEnvelope:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT task_json FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        if row is None:
            raise TaskEnvelopeNotFoundError(f"TaskEnvelope {task_id!r} was not found")
        return cast(TaskEnvelope, _json_load_dict(str(row["task_json"])))

    def update_task(self, task_envelope: TaskEnvelope) -> TaskEnvelope:
        task_id = str(task_envelope["id"])
        task_payload = cast(dict[str, Any], _jsonable(task_envelope))
        timestamps = dict(task_payload.get("timestamps") or {})
        updated_at = _normalized_timestamp(cast(str | None, timestamps.get("updated_at")))
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE tasks
                SET task_json = ?,
                    updated_at = ?
                WHERE task_id = ?
                """,
                (_json_dump(task_payload), updated_at, task_id),
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
                connection.execute(
                    """
                    INSERT INTO evaluation_records (
                        evaluation_id,
                        task_id,
                        recorded_at,
                        request_json,
                        result_json
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        record.evaluation_id,
                        record.task_id,
                        _normalized_timestamp(record.recorded_at),
                        _json_dump(record.request),
                        _json_dump(record.result),
                    ),
                )
        except sqlite3.IntegrityError as error:
            if "FOREIGN KEY constraint failed" in str(error):
                raise TaskEnvelopeNotFoundError(f"TaskEnvelope {task_id!r} was not found") from error
            raise StoreError(f"EvaluationRecord {record.evaluation_id!r} already exists") from error
        return record

    def list_evaluation_records(self, task_id: str) -> tuple[EvaluationRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT evaluation_id, task_id, recorded_at, request_json, result_json
                FROM evaluation_records
                WHERE task_id = ?
                ORDER BY recorded_at ASC, evaluation_id ASC
                """,
                (task_id,),
            ).fetchall()
        return tuple(
            EvaluationRecord(
                evaluation_id=str(row["evaluation_id"]),
                task_id=str(row["task_id"]),
                recorded_at=_normalized_timestamp(str(row["recorded_at"])),
                request=_json_load_dict(str(row["request_json"])),
                result=_json_load_dict(str(row["result_json"])),
            )
            for row in rows
        )

    def list_evaluation_records_for_tasks(self, task_ids: tuple[str, ...]) -> dict[str, tuple[EvaluationRecord, ...]]:
        if not task_ids:
            return {}

        grouped_records: dict[str, list[EvaluationRecord]] = {task_id: [] for task_id in task_ids}
        placeholders = ", ".join("?" for _ in task_ids)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT evaluation_id, task_id, recorded_at, request_json, result_json
                FROM evaluation_records
                WHERE task_id IN ({placeholders})
                ORDER BY task_id ASC, recorded_at ASC, evaluation_id ASC
                """,
                task_ids,
            ).fetchall()

        for row in rows:
            task_id = str(row["task_id"])
            grouped_records.setdefault(task_id, []).append(
                EvaluationRecord(
                    evaluation_id=str(row["evaluation_id"]),
                    task_id=task_id,
                    recorded_at=_normalized_timestamp(str(row["recorded_at"])),
                    request=_json_load_dict(str(row["request_json"])),
                    result=_json_load_dict(str(row["result_json"])),
                )
            )

        return {task_id: tuple(records) for task_id, records in grouped_records.items()}


def build_harness_store(
    *,
    store_backend: str | None = None,
    store_root: str | Path | None = None,
    database_url: str | None = None,
    sqlite_path: str | Path | None = None,
) -> HarnessStore:
    """Construct the configured persistence backend for the API process."""

    resolved_database_url = resolve_postgres_database_url(database_url)
    configured_backend = (store_backend or _first_configured_env(STORE_BACKEND_ENV_VARS) or "").strip().lower()
    if configured_backend:
        backend = configured_backend
    elif database_url and database_url.strip():
        backend = "postgres"
    elif _is_vercel_runtime() and resolved_database_url:
        backend = "postgres"
    else:
        backend = "file"

    if backend == "file":
        resolved_store_root = Path(store_root or _first_configured_env(STORE_ROOT_ENV_VARS) or ".harness-store")
        return FileBackedHarnessStore(resolved_store_root)
    if backend == "postgres":
        return PostgresHarnessStore(resolved_database_url)
    if backend == "sqlite":
        return SQLiteHarnessStore(resolve_sqlite_database_path(sqlite_path, store_root=store_root))
    raise StoreError(f"Unsupported store backend {backend!r}; expected 'file', 'postgres', or 'sqlite'")


__all__ = [
    "EvaluationRecord",
    "EvaluationRecordNotFoundError",
    "EvaluationRecordStore",
    "FileBackedHarnessStore",
    "HarnessStore",
    "PostgresHarnessStore",
    "POSTGRES_DATABASE_URL_ENV_VARS",
    "STORE_BACKEND_ENV_VARS",
    "STORE_ROOT_ENV_VARS",
    "SQLiteHarnessStore",
    "SQLITE_DATABASE_PATH_ENV_VAR",
    "SQLITE_DATABASE_PATH_ENV_VARS",
    "SQLITE_SCHEMA_VERSION",
    "StoreError",
    "TaskEnvelopeAlreadyExistsError",
    "TaskEnvelopeNotFoundError",
    "TaskEnvelopeStore",
    "build_harness_store",
    "resolve_postgres_database_url",
    "resolve_sqlite_database_path",
]
