"""Smoke tests for spec 001 (AC-001.1, AC-001.3, AC-001.4): base URL only."""

from __future__ import annotations

import re
import uuid
from uuid import UUID

import httpx
import pytest


@pytest.mark.smoke
@pytest.mark.writes
def test_smoke_ac_001_1_create_task(smoke_base_url: str) -> None:  # AC-001.1
    title = f"smoke-{uuid.uuid4()}"
    r = httpx.post(
        smoke_base_url + "/tasks", json={"title": title, "due_date": "2026-12-24"}, timeout=10
    )
    assert r.status_code == 201
    body = r.json()
    assert str(UUID(body["id"])) == body["id"]
    assert body["title"] == title
    assert body["due_date"] == "2026-12-24"
    assert re.match(r"^\d{4}-\d{2}-\d{2}T[\d:.]+Z$", body["created_at"])


@pytest.mark.smoke
def test_smoke_ac_001_3_list_tasks_read_only(smoke_base_url: str) -> None:  # AC-001.3
    r = httpx.get(smoke_base_url + "/tasks", timeout=10)
    assert r.status_code == 200
    items = r.json()
    assert isinstance(items, list)
    for item in items:
        assert set(item) == {"id", "title", "due_date", "created_at"}
        UUID(item["id"])


@pytest.mark.smoke
def test_smoke_ac_001_4_invalid_title_is_422(smoke_base_url: str) -> None:  # AC-001.4
    r = httpx.post(smoke_base_url + "/tasks", json={"title": "   "}, timeout=10)
    assert r.status_code == 422
    assert ["body", "title"] in [item["loc"] for item in r.json()["detail"]]
