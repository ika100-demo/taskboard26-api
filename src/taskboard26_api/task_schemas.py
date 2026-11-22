"""Request and response schemas for tasks."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Annotated, Any, Final, Protocol
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


TITLE_RULE_TYPES: Final[Mapping[str, str]] = {
    "missing": "title-required",
    "string_too_short": "title-min",
    "string_too_long": "title-max",
}


def with_contract_types(errors: Sequence[Any]) -> list[Any]:
    """Return copies of validation errors with title errors typed by contract rule id."""
    result: list[Any] = []
    for error in errors:
        entry = dict(error)
        is_title = tuple(entry.get("loc", ())) == ("body", "title")
        if is_title and entry.get("type") in TITLE_RULE_TYPES:
            entry["type"] = TITLE_RULE_TYPES[entry["type"]]
        result.append(entry)
    return result


class TaskLike(Protocol):
    @property
    def id(self) -> UUID: ...
    @property
    def title(self) -> str: ...
    @property
    def due_date(self) -> date | None: ...
    @property
    def created_at(self) -> datetime: ...


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
