from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from taskboard26_api.task_schemas import TaskCreate, TaskOut


def test_title_is_trimmed() -> None:
    assert TaskCreate(title="  hi  ").title == "hi"


def test_title_length_limits() -> None:
    assert len(TaskCreate(title=" " + "a" * 200 + " ").title) == 200
    with pytest.raises(ValidationError):
        TaskCreate(title="a" * 201)


@pytest.mark.parametrize("title", ["", "   ", 123, True, None])
def test_bad_titles(title: object) -> None:
    with pytest.raises(ValidationError) as exc:
        TaskCreate.model_validate({"title": title})
    assert exc.value.errors()[0]["loc"] == ("title",)


def test_missing_title() -> None:
    with pytest.raises(ValidationError):
        TaskCreate.model_validate({})


@pytest.mark.parametrize(
    "value",
    [
        "2026-02-30",
        "24.12.2026",
        "tomorrow",
        "2026-12-24T10:00:00Z",
        "2026-12-24T00:00:00Z",
        20261224,
    ],
)
def test_bad_due_dates(value: object) -> None:
    with pytest.raises(ValidationError) as exc:
        TaskCreate.model_validate({"title": "x", "due_date": value})
    assert exc.value.errors()[0]["loc"] == ("due_date",)


def test_due_date_optional() -> None:
    assert TaskCreate(title="x").due_date is None
    assert TaskCreate.model_validate({"title": "x", "due_date": None}).due_date is None
    got = TaskCreate.model_validate({"title": "x", "due_date": "2020-01-02"})
    assert got.due_date == date(2020, 1, 2)


def test_unknown_fields_ignored() -> None:
    assert not hasattr(TaskCreate.model_validate({"title": "x", "foo": 1}), "foo")


def test_task_out_json() -> None:
    task = SimpleNamespace(
        id=uuid4(),
        title="t",
        due_date=None,
        created_at=datetime(2026, 11, 22, 10, 15, 30, 123456, tzinfo=UTC),
    )
    data = TaskOut.from_task(task).model_dump(mode="json")
    assert data["due_date"] is None
    assert data["created_at"] == "2026-11-22T10:15:30.123456Z"
    task.due_date = date(2026, 12, 24)
    assert TaskOut.from_task(task).model_dump(mode="json")["due_date"] == "2026-12-24"
