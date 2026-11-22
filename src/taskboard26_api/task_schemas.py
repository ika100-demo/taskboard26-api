"""Request and response schemas for tasks."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Annotated, Any, Protocol
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    StringConstraints,
    field_serializer,
)

_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_DATE_ERROR = "due_date must be a calendar date in YYYY-MM-DD form"


def _parse_calendar_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, str) and _DATE_RE.fullmatch(value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise ValueError(_DATE_ERROR)


class TaskLike(Protocol):
    id: UUID
    title: str
    due_date: date | None
    created_at: datetime


class TaskCreate(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    due_date: Annotated[date | None, BeforeValidator(_parse_calendar_date)] = None


class TaskOut(BaseModel):
    id: UUID
    title: str
    due_date: date | None
    created_at: datetime

    @field_serializer("created_at")
    def _serialize_created_at(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        utc = value.astimezone(UTC)
        return utc.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    @classmethod
    def from_task(cls, task: TaskLike) -> TaskOut:
        return cls(
            id=task.id,
            title=task.title,
            due_date=task.due_date,
            created_at=task.created_at,
        )
