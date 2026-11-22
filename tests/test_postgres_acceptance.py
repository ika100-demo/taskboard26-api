"""Acceptance tests for spec 002 (persistent tasks in Postgres), AC-002.1 to AC-002.7."""

from __future__ import annotations

import time

import pytest

from tests.conftest import ApiStarter, TcpProxy, closed_local_url, run_sql

UNAVAILABLE = {"detail": "storage unavailable"}


def _create(client, title: str, due_date: str | None = None) -> dict:  # type: ignore[no-untyped-def]
    body: dict = {"title": title}
    if due_date is not None:
        body["due_date"] = due_date
    r = client.post("/tasks", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_ac_002_1_restart_keeps_tasks(clean_db: str, start_api: ApiStarter) -> None:  # AC-002.1
    with start_api(clean_db) as api:
        created = [
            _create(api, "first", "2026-12-24"),
            _create(api, "second"),
            _create(api, "third", "2020-01-01"),
        ]
        before = api.get("/tasks")
        assert before.status_code == 200
        assert before.json() == created
    # the tasks are in the database, not only in the memory of the process
    stored = run_sql(clean_db, "SELECT id::text, title FROM tasks ORDER BY seq", fetch=True)
    assert stored == [(t["id"], t["title"]) for t in created]
    # restart: the process is gone, the database keeps running
    with start_api(clean_db) as api:
        after = api.get("/tasks")
        assert after.status_code == 200
        assert after.json() == created
        assert [t["title"] for t in after.json()] == ["first", "second", "third"]
    # and a replacement by a new version
    with start_api(clean_db) as api:
        assert api.get("/tasks").json() == created
        fourth = _create(api, "fourth")
        assert [t["id"] for t in api.get("/tasks").json()] == [t["id"] for t in created] + [
            fourth["id"]
        ]


def test_ac_002_2_empty_db_table_created_and_empty_list(  # AC-002.2
    clean_db: str, start_api: ApiStarter
) -> None:
    with start_api(clean_db) as api:
        # the table exists at start, before any request
        rows = run_sql(clean_db, "SELECT to_regclass('tasks')::text", fetch=True)
        assert rows == [("tasks",)], "the API did not create its table at start"
        r = api.get("/tasks")
        assert r.status_code == 200
        assert r.json() == []


def test_ac_002_2_existing_rows_kept_unchanged(  # AC-002.2
    clean_db: str, start_api: ApiStarter
) -> None:
    with start_api(clean_db) as api:
        assert api.get("/tasks").json() == []
    rows = run_sql(clean_db, "SELECT to_regclass('tasks')::text", fetch=True)
    assert rows == [("tasks",)], "the API did not create its table at start"
    run_sql(
        clean_db,
        "INSERT INTO tasks (id, title, due_date, created_at) VALUES "
        "('00000000-0000-4000-8000-000000000002', 'later', NULL, '2026-01-02 10:00:00.250000+00'),"
        "('00000000-0000-4000-8000-000000000001', 'earlier', '2026-03-04',"
        " '2026-01-01 10:00:00.123456+00')",
    )
    expected = [
        {
            "id": "00000000-0000-4000-8000-000000000001",
            "title": "earlier",
            "due_date": "2026-03-04",
            "created_at": "2026-01-01T10:00:00.123456Z",
        },
        {
            "id": "00000000-0000-4000-8000-000000000002",
            "title": "later",
            "due_date": None,
            "created_at": "2026-01-02T10:00:00.250000Z",
        },
    ]
    with start_api(clean_db) as api:
        r = api.get("/tasks")
        assert r.status_code == 200
        assert r.json() == expected
    after = run_sql(clean_db, "SELECT count(*) FROM tasks", fetch=True)
    assert after == [(2,)]


def test_ac_002_3_db_unreachable_gives_503(  # AC-002.3
    db_proxy: tuple[TcpProxy, str], start_api: ApiStarter
) -> None:
    proxy, url = db_proxy
    with start_api(url) as api:
        stored = _create(api, "before outage")
        assert api.get("/ready").status_code == 200
        proxy.cut()

        started = time.monotonic()
        listed = api.get("/tasks")
        assert time.monotonic() - started < 5
        assert listed.status_code == 503
        assert listed.json() == UNAVAILABLE

        started = time.monotonic()
        posted = api.post("/tasks", json={"title": "during outage"})
        assert time.monotonic() - started < 5
        assert posted.status_code == 503
        assert posted.json() == UNAVAILABLE

        assert api.get("/ready").status_code == 503
        assert api.get("/health").status_code == 200
        assert api.get("/health").json() == {"status": "ok"}

        proxy.restore()
        deadline = time.monotonic() + 60
        while api.get("/ready").status_code != 200 and time.monotonic() < deadline:
            time.sleep(0.5)
        # nothing was created during the outage
        assert api.get("/tasks").json() == [stored]

        # a stalled database: connections stay open (pooled ones too) but nothing is answered
        proxy.stall()
        started = time.monotonic()
        listed = api.get("/tasks")
        assert time.monotonic() - started < 5
        assert listed.status_code == 503
        assert listed.json() == UNAVAILABLE
        started = time.monotonic()
        posted = api.post("/tasks", json={"title": "during stall"})
        assert time.monotonic() - started < 5
        assert posted.status_code == 503
        assert posted.json() == UNAVAILABLE
        proxy.restore()
        deadline = time.monotonic() + 60
        while api.get("/ready").status_code != 200 and time.monotonic() < deadline:
            time.sleep(0.5)
        assert api.get("/tasks").json() == [stored]


def test_ac_002_3_unreachable_from_the_start_gives_503(  # AC-002.3
    db_proxy: tuple[TcpProxy, str], start_api: ApiStarter
) -> None:
    proxy, stalled_url = db_proxy
    proxy.stall()
    with start_api(stalled_url) as api:  # a stalled database at start must not block it
        for call in (lambda: api.get("/tasks"), lambda: api.post("/tasks", json={"title": "v"})):
            started = time.monotonic()
            r = call()
            assert time.monotonic() - started < 5
            assert r.status_code == 503
            assert r.json() == UNAVAILABLE
    with start_api(closed_local_url()) as api:
        started = time.monotonic()
        r = api.get("/tasks")
        assert time.monotonic() - started < 5
        assert r.status_code == 503
        assert r.json() == UNAVAILABLE
        started = time.monotonic()
        r = api.post("/tasks", json={"title": "valid"})
        assert time.monotonic() - started < 5
        assert r.status_code == 503
        assert r.json() == UNAVAILABLE


def test_ac_002_4_db_unreachable_at_start(start_api: ApiStarter) -> None:  # AC-002.4
    with start_api(closed_local_url()) as api:  # entering must not raise
        health = api.get("/health")
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}
        ready = api.get("/ready")
        assert ready.status_code == 503
        assert ready.json() == {"status": "unavailable"}


def test_ac_002_4_database_url_unset_is_unready(  # AC-002.4
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    from taskboard26_api.main import app

    monkeypatch.delenv("DATABASE_URL", raising=False)
    try:
        from taskboard26_api.task_store import close_task_store

        close_task_store()
    except ImportError:
        pass
    with TestClient(app, raise_server_exceptions=False) as api:
        assert api.get("/health").status_code == 200
        assert api.get("/ready").status_code == 503


def test_ac_002_5_db_back_after_outage_without_restart(  # AC-002.5
    db_proxy: tuple[TcpProxy, str], start_api: ApiStarter
) -> None:
    proxy, url = db_proxy
    with start_api(url) as api:
        earlier = [_create(api, "one"), _create(api, "two", "2026-05-06")]
        proxy.cut()
        outage_end = time.monotonic() + 6  # an outage of several seconds, not milliseconds
        while time.monotonic() < outage_end:
            assert api.get("/ready").status_code == 503
            assert api.get("/tasks").status_code == 503
            time.sleep(0.5)
        proxy.restore()

        deadline = time.monotonic() + 60
        ready = api.get("/ready")
        while ready.status_code != 200 and time.monotonic() < deadline:
            time.sleep(0.5)
            ready = api.get("/ready")
        assert ready.status_code == 200
        assert ready.json() == {"status": "ready"}

        listed = api.get("/tasks")
        assert listed.status_code == 200
        assert listed.json() == earlier
        created = api.post("/tasks", json={"title": "after outage"})
        assert created.status_code == 201
        assert [t["title"] for t in api.get("/tasks").json()] == ["one", "two", "after outage"]


def test_ac_002_6_limit_reached_gives_409(  # AC-002.6
    clean_db: str, start_api: ApiStarter
) -> None:
    with start_api(clean_db) as api:
        assert api.get("/tasks").json() == []
        rows = run_sql(clean_db, "SELECT to_regclass('tasks')::text", fetch=True)
        assert rows == [("tasks",)], "the API did not create its table at start"
        run_sql(
            clean_db,
            "INSERT INTO tasks (id, title) "
            "SELECT gen_random_uuid(), 't' || g FROM generate_series(1, 9999) AS g",
        )
        last = api.post("/tasks", json={"title": "the 10000th"})
        assert last.status_code == 201
        r = api.post("/tasks", json={"title": "one too many"})
        assert r.status_code == 409
        assert r.json() == {"detail": "task limit reached"}
        assert len(api.get("/tasks").json()) == 10000
    with start_api(clean_db) as api:
        assert len(api.get("/tasks").json()) == 10000
        r = api.post("/tasks", json={"title": "still too many"})
        assert r.status_code == 409
        assert r.json() == {"detail": "task limit reached"}
        assert len(api.get("/tasks").json()) == 10000
    assert run_sql(clean_db, "SELECT count(*) FROM tasks", fetch=True) == [(10000,)]


@pytest.mark.parametrize(
    ("body", "rule"),
    [
        ({}, "title-required"),
        ({"due_date": "2026-12-24"}, "title-required"),
        ({"title": ""}, "title-min"),
        ({"title": "   \t "}, "title-min"),
        ({"title": "x" * 201}, "title-max"),
        ({"title": "  " + "x" * 201 + "  "}, "title-max"),
    ],
    ids=["missing", "missing-with-date", "empty", "whitespace", "too-long", "too-long-padded"],
)
def test_ac_002_7_invalid_title_is_422_and_not_stored(  # AC-002.7
    clean_db: str, start_api: ApiStarter, body: dict, rule: str
) -> None:
    with start_api(clean_db) as api:
        r = api.post("/tasks", json=body)
        assert r.status_code == 422
        detail = r.json()["detail"]
        assert isinstance(detail, list)
        title_entries = [e for e in detail if e["loc"][-1] == "title"]
        assert title_entries, detail
        assert [e["type"] for e in title_entries] == [rule]
        assert api.get("/tasks").json() == []
    with start_api(clean_db) as api:
        assert api.get("/tasks").json() == []


def test_ac_002_7_title_of_200_after_trimming_is_accepted(  # AC-002.7
    clean_db: str, start_api: ApiStarter
) -> None:
    with start_api(clean_db) as api:
        r = api.post("/tasks", json={"title": "  " + "x" * 200 + "  "})
        assert r.status_code == 201
        assert r.json()["title"] == "x" * 200
        assert len(api.get("/tasks").json()) == 1
