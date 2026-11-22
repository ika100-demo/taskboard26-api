"""Bounded, thread-safe, in-memory task store (no persistence)."""

import threading
from dataclasses import dataclass
from datetime import UTC, date, datetime
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

    def __len__(self) -> int:
        with self._lock:
            return len(self._tasks)


_store = TaskStore()


def get_task_store() -> TaskStore:
    return _store
