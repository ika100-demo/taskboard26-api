"""Durable task store on PostgreSQL (SQLAlchemy Core + psycopg 3)."""

import threading
from collections.abc import Callable
from datetime import date
from typing import Any, TypeVar
from uuid import uuid4

import structlog
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from .task_store import MAX_TASKS, StorageUnavailableError, Task, TaskLimitReachedError

SCHEMA_LOCK_KEY: int = 7_002_000_000_001
INSERT_LOCK_KEY: int = 7_002_000_000_002
TABLE = "tasks"

_DDL = (
    f"""CREATE TABLE IF NOT EXISTS {TABLE} (
    id         uuid        PRIMARY KEY,
    seq        bigint      GENERATED ALWAYS AS IDENTITY UNIQUE,
    title      text        NOT NULL CHECK (char_length(title) BETWEEN 1 AND 200),
    due_date   date        NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
)""",
    f"CREATE INDEX IF NOT EXISTS tasks_created_at_seq_idx ON {TABLE} (created_at, seq)",
)

_CONNECT_ARGS: dict[str, Any] = {
    "connect_timeout": 2,
    "options": "-c statement_timeout=3000 -c TimeZone=UTC",
    "keepalives": 1,
    "keepalives_idle": 5,
    "keepalives_interval": 2,
    "keepalives_count": 2,
    "tcp_user_timeout": 2000,
    "application_name": "taskboard26-api",
}

_T = TypeVar("_T")
_log = structlog.get_logger(__name__)


class PostgresTaskStore:
    def __init__(self, database_url: str | None, limit: int = MAX_TASKS) -> None:
        self._limit = limit
        self._schema_ready = False
        self._schema_lock = threading.Lock()
        self._engine: Engine | None = None
        if database_url:
            url = make_url(database_url).set(drivername="postgresql+psycopg")
            self._engine = create_engine(
                url,
                connect_args=_CONNECT_ARGS,
                pool_size=5,
                max_overflow=5,
                pool_timeout=2,
                pool_pre_ping=True,
            )

    def _run(self, operation: str, fn: Callable[[Engine], _T]) -> _T:
        try:
            if self._engine is None:
                raise StorageUnavailableError("storage not configured")
            return fn(self._engine)
        except (OperationalError, InterfaceError, PoolTimeoutError) as exc:
            _log.warning("storage_unavailable", operation=operation, error=type(exc).__name__)
            raise StorageUnavailableError("storage unavailable") from exc
        except StorageUnavailableError as exc:
            _log.warning("storage_unavailable", operation=operation, error=type(exc).__name__)
            raise

    def _ensure_schema(self, engine: Engine) -> None:
        if self._schema_ready:
            return
        with engine.begin() as conn:
            conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": SCHEMA_LOCK_KEY})
            for statement in _DDL:
                conn.execute(text(statement))
        with self._schema_lock:
            first = not self._schema_ready
            self._schema_ready = True
        if first:
            _log.info("schema_ready")

    def ensure_schema(self) -> None:
        self._run("ensure_schema", self._ensure_schema)

    def add(self, title: str, due_date: date | None) -> Task:
        def op(engine: Engine) -> Task:
            self._ensure_schema(engine)
            with engine.begin() as conn:
                conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": INSERT_LOCK_KEY})
                count = conn.execute(text(f"SELECT count(*) FROM {TABLE}")).scalar_one()
                if count >= self._limit:
                    raise TaskLimitReachedError(f"task limit of {self._limit} reached")
                row = conn.execute(
                    text(
                        f"INSERT INTO {TABLE} (id, title, due_date) "
                        "VALUES (:id, :title, :due_date) "
                        "RETURNING id, title, due_date, created_at"
                    ),
                    {"id": uuid4(), "title": title, "due_date": due_date},
                ).one()
            return Task(row.id, row.title, row.due_date, row.created_at)

        return self._run("add", op)

    def list_all(self) -> list[Task]:
        def op(engine: Engine) -> list[Task]:
            self._ensure_schema(engine)
            with engine.begin() as conn:
                rows = conn.execute(
                    text(
                        f"SELECT id, title, due_date, created_at FROM {TABLE} "
                        "ORDER BY created_at, seq"
                    )
                ).all()
            return [Task(r.id, r.title, r.due_date, r.created_at) for r in rows]

        return self._run("list_all", op)

    def ping(self) -> bool:
        if self._engine is None:
            return False
        try:
            with self._engine.begin() as conn:
                conn.execute(text("SET LOCAL statement_timeout = '2s'"))
                conn.execute(text("SELECT 1"))
        except Exception as exc:  # ping never raises
            _log.warning("storage_unavailable", operation="ping", error=type(exc).__name__)
            return False
        return True

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
