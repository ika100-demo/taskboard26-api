import time
from datetime import UTC, date

import pytest

from taskboard26_api.postgres_store import PostgresTaskStore
from taskboard26_api.task_store import (
    StorageUnavailableError,
    TaskLimitReachedError,
    close_task_store,
    get_task_store,
)

CLOSED_PORT_URL = "postgresql://u:p@127.0.0.1:1/db"


def test_ensure_schema_twice_keeps_rows(clean_db: str) -> None:
    store = PostgresTaskStore(clean_db)
    try:
        store.ensure_schema()
        store.add("a", None)
        store.ensure_schema()
        assert [t.title for t in store.list_all()] == ["a"]
    finally:
        store.close()


def test_add_list_round_trip(clean_db: str) -> None:
    store = PostgresTaskStore(clean_db)
    try:
        first = store.add("a", date(2030, 1, 2))
        second = store.add("b", None)
        listed = store.list_all()
    finally:
        store.close()
    assert listed == [first, second]
    assert first.due_date == date(2030, 1, 2)
    assert first.created_at.utcoffset() == UTC.utcoffset(None)
    assert first.created_at <= second.created_at


def test_new_instance_sees_same_rows(clean_db: str) -> None:
    one = PostgresTaskStore(clean_db)
    added = one.add("a", None)
    one.close()
    two = PostgresTaskStore(clean_db)
    try:
        assert two.list_all() == [added]
    finally:
        two.close()


def test_limit_raises_and_stores_nothing(clean_db: str) -> None:
    store = PostgresTaskStore(clean_db, limit=2)
    try:
        store.add("a", None)
        store.add("b", None)
        with pytest.raises(TaskLimitReachedError):
            store.add("c", None)
        assert [t.title for t in store.list_all()] == ["a", "b"]
    finally:
        store.close()


@pytest.mark.parametrize("url", [None, "", CLOSED_PORT_URL])
def test_unreachable_raises_within_5s(url: str | None) -> None:
    store = PostgresTaskStore(url)
    start = time.monotonic()
    with pytest.raises(StorageUnavailableError):
        store.list_all()
    with pytest.raises(StorageUnavailableError):
        store.add("a", None)
    assert store.ping() is False
    assert time.monotonic() - start < 5 * 3
    store.close()


def test_get_task_store_rebuilds_from_environment(
    clean_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", clean_db)
    store = get_task_store()
    assert get_task_store() is store
    assert store.ping() is True
    close_task_store()
    assert get_task_store() is not store
    close_task_store()
