"""Smoke tests for spec 002 (AC-002.1, AC-002.2, AC-002.5): base URL only."""

from __future__ import annotations

import re
import uuid
from uuid import UUID

import httpx
import pytest


@pytest.mark.smoke
@pytest.mark.writes
def test_smoke_ac_002_1_created_task_is_listed(smoke_base_url: str) -> None:  # AC-002.1
    title = f"smoke-{uuid.uuid4()}"
    created = httpx.post(smoke_base_url + "/tasks", json={"title": title}, timeout=10)
    assert created.status_code == 201
    task = created.json()
    listed = httpx.get(smoke_base_url + "/tasks", timeout=10)
    assert listed.status_code == 200
    assert task in listed.json()


@pytest.mark.smoke
def test_smoke_ac_002_2_list_is_task_shaped_read_only(smoke_base_url: str) -> None:  # AC-002.2
    r = httpx.get(smoke_base_url + "/tasks", timeout=10)
    assert r.status_code == 200
    items = r.json()
    assert isinstance(items, list)
    for item in items:
        assert set(item) == {"id", "title", "due_date", "created_at"}
        UUID(item["id"])
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$", item["created_at"])
    stamps = [item["created_at"] for item in items]
    assert stamps == sorted(stamps)  # oldest first


@pytest.mark.smoke
def test_smoke_ac_002_5_ready_read_only(smoke_base_url: str) -> None:  # AC-002.5
    r = httpx.get(smoke_base_url + "/ready", timeout=10)
    assert r.status_code == 200
    assert r.json() == {"status": "ready"}
