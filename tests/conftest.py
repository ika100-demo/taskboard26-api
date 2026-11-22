"""Shared pytest fixtures, including the Postgres test hooks of spec 002."""

from __future__ import annotations

import os
import re
import socket
import threading
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import pytest
from fastapi.testclient import TestClient

from taskboard26_api.main import app

# A URL that no server listens on; used when the Postgres test dependencies are not installed yet,
# so that tests fail on missing behaviour instead of erroring in a fixture.
_UNREACHABLE_FALLBACK = "postgresql://test:test@127.0.0.1:9/test"


@pytest.fixture()
def client() -> TestClient:
    """A TestClient for the FastAPI application."""
    return TestClient(app)


# ---------------------------------------------------------------------------
# Postgres hooks (spec 002)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """`postgresql://` URL of a real Postgres: TEST_DATABASE_URL, else a testcontainer."""
    given = os.environ.get("TEST_DATABASE_URL")
    if given:
        yield given
        return
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        yield _UNREACHABLE_FALLBACK
        return
    container = PostgresContainer("postgres:17-alpine")
    container.start()
    try:
        yield re.sub(r"^postgresql\+\w+://", "postgresql://", container.get_connection_url())
    finally:
        container.stop()


def run_sql(url: str, statement: str, *, fetch: bool = False) -> list[tuple[Any, ...]]:
    """Run one statement on a fresh connection (autocommit) and close it."""
    try:
        import psycopg
    except ImportError:
        pytest.fail("psycopg is not installed (dependency of spec 002 task t1)")
    with psycopg.connect(url, autocommit=True, connect_timeout=5) as conn:
        cur = conn.execute(statement)  # type: ignore[arg-type]
        return cur.fetchall() if fetch else []


def _close_store() -> None:
    try:
        from taskboard26_api.task_store import close_task_store
    except ImportError:
        return
    close_task_store()


@pytest.fixture()
def clean_db(postgres_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """The Postgres URL with the `tasks` table dropped and no process-wide store."""
    try:
        run_sql(postgres_url, "DROP TABLE IF EXISTS tasks")
    except BaseException:  # noqa: BLE001 - dependency missing or no server: tests fail themselves
        pass
    monkeypatch.delenv("DATABASE_URL", raising=False)
    _close_store()
    yield postgres_url
    _close_store()


ApiStarter = Callable[[str], AbstractContextManager[TestClient]]


@pytest.fixture()
def start_api(monkeypatch: pytest.MonkeyPatch) -> ApiStarter:
    """`with start_api(url) as client:` runs the app (lifespan included) against `url`.

    Leaving the block is a process shutdown; entering a new one is a restart.
    """

    @contextmanager
    def starter(url: str) -> Iterator[TestClient]:
        monkeypatch.setenv("DATABASE_URL", url)
        _close_store()
        app.dependency_overrides.pop(_get_task_store(), None)
        try:
            with TestClient(app, raise_server_exceptions=False) as api_client:
                yield api_client
        finally:
            _close_store()

    return starter


def _get_task_store() -> Any:
    from taskboard26_api.task_store import get_task_store

    return get_task_store


def closed_local_url() -> str:
    """A `postgresql://` URL pointing at a local port nothing listens on."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"postgresql://test:test@127.0.0.1:{port}/test"


class TcpProxy:
    """A TCP proxy in front of a Postgres: cut() drops everything, restore() listens again."""

    def __init__(self, target_host: str, target_port: int) -> None:
        self._target = (target_host, target_port)
        self._lock = threading.Lock()
        self._conns: list[socket.socket] = []
        self._listener: socket.socket | None = None
        self._stalled = False
        self._held: list[socket.socket] = []
        self.port = 0
        self._listen(0)

    def _listen(self, port: int) -> None:
        last: OSError | None = None
        for _ in range(50):
            sock = socket.socket()
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError as exc:
                sock.close()
                last = exc
                threading.Event().wait(0.1)
                continue
            sock.listen(16)
            self.port = sock.getsockname()[1]
            with self._lock:
                self._listener = sock
            threading.Thread(target=self._accept, args=(sock,), daemon=True).start()
            return
        raise RuntimeError(f"proxy cannot listen on port {port}: {last}")

    def _accept(self, listener: socket.socket) -> None:
        while True:
            try:
                client, _ = listener.accept()
            except OSError:
                return
            if self._stalled:  # accept and keep open, forward nothing
                with self._lock:
                    self._held.append(client)
                continue
            try:
                upstream = socket.create_connection(self._target, timeout=5)
                upstream.settimeout(None)
            except OSError:
                client.close()
                continue
            with self._lock:
                self._conns.extend([client, upstream])
            threading.Thread(target=self._pump, args=(client, upstream), daemon=True).start()
            threading.Thread(target=self._pump, args=(upstream, client), daemon=True).start()

    def _pump(self, src: socket.socket, dst: socket.socket) -> None:
        try:
            while data := src.recv(65536):
                while self._stalled:
                    threading.Event().wait(0.05)
                dst.sendall(data)
        except OSError:
            pass
        finally:
            for sock in (src, dst):
                try:
                    sock.close()
                except OSError:
                    pass

    def cut(self) -> None:
        """Close the listener and every open connection."""
        with self._lock:
            listener, self._listener = self._listener, None
            conns, self._conns = self._conns, []
        if listener is not None:
            listener.close()
        for sock in conns:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()

    def stall(self) -> None:
        """Keep every connection open (old and new) but forward nothing."""
        self._stalled = True

    def restore(self) -> None:
        """Listen on the same port again and forward again."""
        self._stalled = False
        with self._lock:
            held, self._held = self._held, []
        for sock in held:
            sock.close()
        if self._listener is None:
            self._listen(self.port)

    def url_for(self, url: str) -> str:
        """`url` with its host and port replaced by the proxy's."""
        parts = urlsplit(url)
        userinfo = parts.netloc.rsplit("@", 1)[0] + "@" if "@" in parts.netloc else ""
        return urlunsplit(parts._replace(netloc=f"{userinfo}127.0.0.1:{self.port}"))


@pytest.fixture()
def db_proxy(clean_db: str) -> Iterator[tuple[TcpProxy, str]]:
    """(proxy, URL through the proxy) in front of the clean test database."""
    parts = urlsplit(clean_db)
    proxy = TcpProxy(parts.hostname or "127.0.0.1", parts.port or 5432)
    try:
        yield proxy, proxy.url_for(clean_db)
    finally:
        proxy.cut()


# ---------------------------------------------------------------------------
# Contract check (spec 110): the accept cases must not need a live database
# ---------------------------------------------------------------------------


@pytest.fixture()
def contract_send() -> Iterator[Callable[[str, dict[str, Any]], tuple[int, Any]]]:
    from taskboard26_api.task_store import TaskStore, get_task_store

    app.dependency_overrides[get_task_store] = lambda: TaskStore()
    api_client = TestClient(app)

    def send(endpoint: str, body: dict[str, Any]) -> tuple[int, Any]:
        method, path = endpoint.split(" ", 1)
        response = api_client.request(method, path, json=body)
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, response.text

    try:
        yield send
    finally:
        app.dependency_overrides.pop(get_task_store, None)
