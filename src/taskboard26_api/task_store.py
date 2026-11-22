"""Task repository protocol, the in-memory store and the process-wide store accessor."""

import os
import threading
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Protocol
from uuid import UUID, uuid4

MAX_TASKS: int = 10_000


@dataclass(frozen=True, slots=True)
class Task:
    id: UUID
    title: str
    due_date: date | None
    created_at: datetime


class TaskLimitReachedError(Exception):
    """Raised when the store already holds its maximum number of tasks."""


class StorageUnavailableError(Exception):
    """Raised when the task storage cannot be reached in time."""


class TaskRepository(Protocol):
    def ensure_schema(self) -> None: ...

    def add(self, title: str, due_date: date | None) -> Task: ...

    def list_all(self) -> list[Task]: ...

    def ping(self) -> bool: ...


class TaskStore:
    def __init__(self, limit: int = MAX_TASKS) -> None:
        self._limit = limit
        self._tasks: list[Task] = []
        self._lock = threading.Lock()

    def add(self, title: str, due_date: date | None) -> Task:
        with self._lock:
            if len(self._tasks) >= self._limit:
                raise TaskLimitReachedError(f"task limit of {self._limit} reached")
            task = Task(uuid4(), title, due_date, datetime.now(UTC))
            self._tasks.append(task)
            return task

    def list_all(self) -> list[Task]:
        with self._lock:
            return list(self._tasks)

    def ensure_schema(self) -> None:
        return None

    def ping(self) -> bool:
        return True

    def __len__(self) -> int:
        with self._lock:
            return len(self._tasks)


_store: TaskRepository | None = None
_store_lock = threading.Lock()


def get_task_store() -> TaskRepository:
    global _store
    with _store_lock:
        if _store is None:
            from taskboard26_api.postgres_store import PostgresTaskStore

            _store = PostgresTaskStore(os.environ.get("DATABASE_URL"))
        return _store


def close_task_store() -> None:
    global _store
    with _store_lock:
        store, _store = _store, None
    close = getattr(store, "close", None)
    if close is not None:
        close()
