from datetime import UTC, date

import pytest

from taskboard26_api.task_store import TaskLimitReachedError, TaskStore


def test_fresh_store_is_empty() -> None:
    store = TaskStore()
    assert len(store) == 0
    assert store.list_all() == []


def test_insertion_order_kept() -> None:
    store = TaskStore()
    titles = ["a", "b", "c"]
    for t in titles:
        store.add(t, None)
    assert [t.title for t in store.list_all()] == titles


def test_list_all_returns_copy() -> None:
    store = TaskStore()
    store.add("a", date(2030, 1, 1))
    listed = store.list_all()
    listed.clear()
    assert len(store.list_all()) == 1


def test_limit_raises_and_count_unchanged() -> None:
    store = TaskStore(limit=2)
    store.add("a", None)
    store.add("b", None)
    with pytest.raises(TaskLimitReachedError):
        store.add("c", None)
    assert len(store) == 2
    assert [t.title for t in store.list_all()] == ["a", "b"]


def test_created_at_is_utc_aware() -> None:
    task = TaskStore().add("a", None)
    assert task.created_at.tzinfo is not None
    assert task.created_at.utcoffset() == UTC.utcoffset(None)


def test_ids_unique() -> None:
    store = TaskStore()
    ids = {store.add("a", None).id for _ in range(50)}
    assert len(ids) == 50


def test_in_memory_ping_true_and_ensure_schema_noop() -> None:
    store = TaskStore()
    assert store.ping() is True
    assert store.ensure_schema() is None
    assert len(store) == 0
