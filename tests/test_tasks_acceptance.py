"""Acceptance tests for spec 001 (create and list tasks in memory), AC-001.1 to AC-001.8."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from taskboard26_api.main import app

CREATED_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


@contextmanager
def isolated_store(limit: int | None = None) -> Iterator[object]:
    """Override get_task_store with an empty TaskStore; imports happen here, at test time."""
    from taskboard26_api.task_store import TaskStore, get_task_store

    store = TaskStore() if limit is None else TaskStore(limit=limit)
    app.dependency_overrides[get_task_store] = lambda: store
    try:
        yield store
    finally:
        app.dependency_overrides.pop(get_task_store, None)


def _locs(response) -> list[list]:  # type: ignore[no-untyped-def]
    return [item["loc"] for item in response.json()["detail"]]


def test_ac_001_1_create_task_returns_201_and_task_object() -> None:  # AC-001.1
    with isolated_store():
        client = TestClient(app)
        r = client.post("/tasks", json={"title": "Buy milk", "due_date": "2026-12-24"})
        assert r.status_code == 201
        body = r.json()
        assert set(body) == {"id", "title", "due_date", "created_at"}
        assert str(UUID(body["id"])) == body["id"]
        assert body["title"] == "Buy milk"
        assert body["due_date"] == "2026-12-24"
        assert CREATED_AT_RE.match(body["created_at"])
        parsed = datetime.fromisoformat(body["created_at"].replace("Z", "+00:00"))
        assert parsed.utcoffset() is not None


@pytest.mark.parametrize("body", [{"title": "Call Bob"}, {"title": "Call Bob", "due_date": None}])
def test_ac_001_2_no_due_date_is_null(body: dict) -> None:  # AC-001.2
    with isolated_store():
        r = TestClient(app).post("/tasks", json=body)
        assert r.status_code == 201
        assert "due_date" in r.json()
        assert r.json()["due_date"] is None


def test_ac_001_3_list_returns_tasks_oldest_first() -> None:  # AC-001.3
    with isolated_store():
        client = TestClient(app)
        assert client.get("/tasks").status_code == 200
        assert client.get("/tasks").json() == []
        created = [client.post("/tasks", json={"title": t}).json() for t in ("A", "B", "C")]
        r = client.get("/tasks")
        assert r.status_code == 200
        assert r.json() == created
        assert [t["title"] for t in r.json()] == ["A", "B", "C"]


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"title": None},
        {"title": 123},
        {"title": True},
        {"title": ""},
        {"title": "   "},
        {"title": "x" * 201},
        {"title": "  " + "x" * 201 + "  "},
    ],
)
def test_ac_001_4_invalid_title_is_422(body: dict) -> None:  # AC-001.4
    with isolated_store():
        client = TestClient(app)
        r = client.post("/tasks", json=body)
        assert r.status_code == 422
        assert ["body", "title"] in _locs(r)
        assert client.get("/tasks").json() == []


def test_ac_001_4_title_of_200_chars_after_trim_is_accepted() -> None:  # AC-001.4
    with isolated_store():
        r = TestClient(app).post("/tasks", json={"title": "  " + "x" * 200 + "  "})
        assert r.status_code == 201
        assert r.json()["title"] == "x" * 200


@pytest.mark.parametrize(
    "due",
    [
        "2026-02-30",
        "24.12.2026",
        "tomorrow",
        "2026-12-24T10:00:00Z",
        "2026-12-24T00:00:00Z",
        20261224,
    ],
)
def test_ac_001_5_invalid_due_date_is_422(due: object) -> None:  # AC-001.5
    with isolated_store():
        client = TestClient(app)
        r = client.post("/tasks", json={"title": "x", "due_date": due})
        assert r.status_code == 422
        assert ["body", "due_date"] in _locs(r)
        assert client.get("/tasks").json() == []


def test_ac_001_6_title_is_trimmed() -> None:  # AC-001.6
    with isolated_store():
        client = TestClient(app)
        r = client.post("/tasks", json={"title": "  Buy milk  "})
        assert r.status_code == 201
        assert r.json()["title"] == "Buy milk"
        assert client.get("/tasks").json()[0]["title"] == "Buy milk"


def test_ac_001_7_task_limit_gives_409() -> None:  # AC-001.7
    with isolated_store() as store:
        for i in range(10_000):
            store.add(f"t{i}", None)  # type: ignore[attr-defined]
        client = TestClient(app)
        r = client.post("/tasks", json={"title": "one too many"})
        assert r.status_code == 409
        assert r.json()["detail"] == "task limit reached"
        listed = client.get("/tasks")
        assert listed.status_code == 200
        assert len(listed.json()) == 10_000


def test_ac_001_8_restart_gives_empty_list() -> None:  # AC-001.8
    with isolated_store():
        client = TestClient(app)
        assert client.post("/tasks", json={"title": "before restart"}).status_code == 201
        assert len(client.get("/tasks").json()) == 1
    # A restart is a new process: a new, empty store (the module keeps no other state).
    with isolated_store():
        r = TestClient(app).get("/tasks")
        assert r.status_code == 200
        assert r.json() == []
