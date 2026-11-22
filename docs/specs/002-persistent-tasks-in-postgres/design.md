# Design — 002 Persistent tasks in Postgres

## Decisions

- **Driver and pool: SQLAlchemy 2 Core (no ORM) over psycopg 3 (`psycopg[binary]`).** SQLAlchemy's `QueuePool` opens connections synchronously on checkout and has `pool_pre_ping`. So a broken pooled connection is thrown away and replaced in the same request, with no background reconnect backoff that could delay recovery past AC-002.5's 60 s. `psycopg_pool` retries in the background with exponential backoff (1, 2, 4 … 64 s), and after a long outage the next attempt can come more than 60 s after the database returns. The `binary` extra brings libpq inside the wheel, so the skeleton `Dockerfile` (python:3.12-slim, no libpq) stays unchanged. The endpoints stay plain `def`, as in spec 001. ADR pending (see report): `postgres-storage-sqlalchemy-psycopg`.
- **The API creates its own schema; no migration tool yet** (AC-002.2). `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` runs inside a transaction that holds `pg_advisory_xact_lock(SCHEMA_LOCK_KEY)`, so replicas that start together do not race. It runs at startup (lifespan) and, if that failed, again before the first storage operation that reaches the database. It never drops, alters or rewrites anything, so stored tasks stay unchanged. A migration tool (Alembic) comes with the first spec that changes the table. This is part of the same ADR.
- **The 10,000 limit stays exact across replicas** (AC-002.6). A create takes `pg_advisory_xact_lock(INSERT_LOCK_KEY)`, counts, inserts and commits in one transaction. Creates are serialized, which is fine at taskboard volume, and the count cannot be outrun by a parallel insert on another replica.
- **The database sets `created_at`**: `DEFAULT clock_timestamp()` (microseconds), taken while the insert lock is held. That makes it monotonic in insertion order across replicas, because there is a single clock. Rows are ordered by `(created_at, seq)`, where `seq` is a `GENERATED ALWAYS AS IDENTITY` tie-breaker (note "order by it with an insertion sequence as tie-breaker"). `id` stays an app-side `uuid4()`.
- **Timeouts** (contract "Timeouts"), set as libpq connect parameters on every connection:
  - `connect_timeout=2`.
  - `options=-c statement_timeout=3000 -c TimeZone=UTC`.
  - `keepalives=1, keepalives_idle=5, keepalives_interval=2, keepalives_count=2, tcp_user_timeout=2000`.
  - Pool: `pool_size=5, max_overflow=5, pool_timeout=2, pool_pre_ping=True`.
  - Worst case for a dead peer: pre-ping on a stale connection (≤ 2 s, `tcp_user_timeout`) plus one reconnect (≤ 2 s, `connect_timeout`), about 4 s. That is under AC-002.3's 5 s. A refused connection fails at once, and a slow but live server is cut off by `statement_timeout` at 3 s.
  - Residual risk, accepted: a frozen server whose kernel still ACKs (e.g. `docker pause`) is caught by none of these, because libpq has no client-side read timeout. A database pod that dies or is cut off sends RST or stops ACKing, and both are caught.
- **Which errors mean "storage unavailable"**: `sqlalchemy.exc.OperationalError` (connection refused or reset, auth failure, timeouts, `QueryCanceled`), `InterfaceError`, and the pool's `sqlalchemy.exc.TimeoutError`. The store maps them to `StorageUnavailableError`, and the router answers `503 {"detail": "storage unavailable"}`. Any other database error is a bug and stays a 500.
- **Configuration**: only `DATABASE_URL` is read (CloudNativePG `uri`, `postgresql://…` or `postgres://…`); the driver name is rewritten to `postgresql+psycopg`. The `PG*` variables that the gitops entry also provides are not read. When `DATABASE_URL` is unset or empty, the store acts as permanently unreachable: `503` on `/tasks`, `503` on `/ready`, and an `error` log `database_url_missing` at startup. A missing secret then looks like an outage: the pod stays unready and the rollout stalls visibly. The app itself keeps running, and the app can still be imported in tests without a database. The URL holds the password and is never logged.
- **Liveness and readiness**: `/health` is unchanged and never touches the store. `/ready` calls `store.ping()`, which runs `SELECT 1` with `SET LOCAL statement_timeout = '2s'` (connect timeout 2 s). It answers `200 {"status": "ready"}` on success, else `503 {"status": "unavailable"}`. `/ready` gets the store through the same `get_task_store` dependency as `/tasks`, so tests override both together.
- **Start with the database down** (AC-002.4): the lifespan calls `store.ensure_schema()`. On `StorageUnavailableError` it logs `storage_unavailable_at_startup` (warning) and continues. It never raises, so uvicorn finishes starting and `/health` answers.
- **Contract error types** (AC-002.7, contract check `tests/test_contract.py`): the contract demands `type` equal to the failed rule's id. A `RequestValidationError` handler rewrites only the `POST /tasks` errors whose `loc == ["body","title"]`:
  - `missing` becomes `title-required`.
  - `string_too_short` becomes `title-min`. Empty and whitespace-only titles land here after trimming.
  - `string_too_long` becomes `title-max`.
  - Every other entry, including `string_type` for a `null`, number or boolean title and all `due_date` errors, keeps FastAPI's type.
  - Everything else about the body (status 422, `detail` list, `loc`, `msg`, `input`, `ctx`) stays FastAPI's default, so spec 001's contract (`type: str`) still holds.
- **The in-memory `TaskStore` stays** as the store implementation that tests inject: spec 001's acceptance tests and the contract check override `get_task_store` with it. Production never builds it; `get_task_store()` now returns the Postgres store. Superseded AC-001.8's test still passes against it. Retiring that test is up to the testers.
- **No data carry-over** (system A3). No gitops change: the system plan already wires `DATABASE_URL` and `PG*`, and the port and probe paths stay the same.
- **Tests run against a real Postgres via testcontainers** (`postgres:17-alpine`), or against `TEST_DATABASE_URL` when it is set (self-hosted runners or machines without Docker). An in-memory fake cannot prove restart, unreachability or the timeouts. ADR pending: `postgres-integration-tests-testcontainers`.
- Unattended planning: the spec has no open questions, so there was nothing to answer by default.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `src/taskboard26_api/task_store.py` | `Task`, `TaskLimitReachedError`, new `StorageUnavailableError`, new `TaskRepository` protocol, in-memory `TaskStore` (gains `ping`, `ensure_schema`), provider `get_task_store()` (now the process-wide Postgres store) and new `close_task_store()` | changed |
| `src/taskboard26_api/postgres_store.py` | `PostgresTaskStore`: engine and timeouts, DDL, `ensure_schema`, `add` (limit under advisory lock), `list_all`, `ping`, `close`, error mapping | new |
| `src/taskboard26_api/task_schemas.py` | new `TITLE_RULE_TYPES` and `with_contract_types(errors)` | changed |
| `src/taskboard26_api/tasks_api.py` | `503` on `StorageUnavailableError`; `validation_exception_handler`; store typed as `TaskRepository` | changed |
| `src/taskboard26_api/main.py` | lifespan (ensure schema, non-fatal; close on shutdown), `/ready` pings the store, registers the validation handler | changed |
| `pyproject.toml`, `uv.lock` | runtime `sqlalchemy>=2.0`, `psycopg[binary]>=3.2`; dev `testcontainers[postgres]>=4.8` | changed |

## Contract

Spec 001's contract (fields, 201/422/409 bodies, ordering, trimming, `due_date` rules) is unchanged except for the points below. See [../001-create-and-list-tasks-in-memory/design.md](../001-create-and-list-tasks-in-memory/design.md).

### `GET /tasks`

- `200`: every stored task, ordered by `created_at`, then `seq` (oldest first), each exactly as its `POST` returned it, including after a restart or redeploy (AC-002.1). `[]` for an empty table (AC-002.2).
- `503`: `{"detail": "storage unavailable"}` when the database cannot be reached or the statement times out, within 5 s (AC-002.3).

### `POST /tasks`

- Validation runs first, then the limit check, then storage. An invalid body is `422` even while the database is down.
- `201`: the stored task, committed before the answer (AC-002.1).
- `422`: FastAPI's body, `{"detail": [{"type", "loc", "msg", "input", ...}]}`. For `loc == ["body","title"]`, `type` is `title-required` (field missing), `title-min` (empty or whitespace-only after trimming) or `title-max` (more than 200 characters after trimming). `null`, number and boolean titles keep `string_type`. Nothing is stored (AC-002.7).
- `409`: `{"detail": "task limit reached"}` when 10,000 rows exist (AC-002.6).
- `503`: `{"detail": "storage unavailable"}`, nothing stored, within 5 s (AC-002.3).

### Probes

- `GET /health`: always `200 {"status": "ok"}`, never touches the database (AC-002.3, AC-002.4).
- `GET /ready`: `200 {"status": "ready"}` when `SELECT 1` succeeds within 2 s. Otherwise, including when `DATABASE_URL` is unset, `503 {"status": "unavailable"}` (AC-002.3, .4, .5).

### Configuration

| Env | Required | Meaning |
|---|---|---|
| `DATABASE_URL` | yes (else permanently unavailable, see Decisions) | `postgresql://user:pass@host:port/db`; wired by the gitops entry from the CloudNativePG secret |

### Python interface (what tests may import)

```python
# taskboard26_api.task_store  (existing names unchanged)
class StorageUnavailableError(Exception): ...        # the database is unreachable / timed out / not configured

class TaskRepository(Protocol):
    def ensure_schema(self) -> None: ...             # idempotent; raises StorageUnavailableError
    def add(self, title: str, due_date: date | None) -> Task: ...  # raises TaskLimitReachedError, StorageUnavailableError
    def list_all(self) -> list[Task]: ...            # ordered oldest first; raises StorageUnavailableError
    def ping(self) -> bool: ...                      # never raises

class TaskStore:                                     # in-memory; ensure_schema() no-op, ping() -> True
    ...

def get_task_store() -> TaskRepository: ...          # process-wide PostgresTaskStore(os.environ.get("DATABASE_URL")),
                                                     # built on first call (thread-safe), not at import
def close_task_store() -> None: ...                  # closes it (engine.dispose) and forgets it; the next
                                                     # get_task_store() builds a new one from the current env

# taskboard26_api.postgres_store
SCHEMA_LOCK_KEY: int
INSERT_LOCK_KEY: int

class PostgresTaskStore:                             # implements TaskRepository
    def __init__(self, database_url: str | None, limit: int = MAX_TASKS) -> None: ...  # never connects
    def ensure_schema(self) -> None: ...
    def add(self, title: str, due_date: date | None) -> Task: ...
    def list_all(self) -> list[Task]: ...
    def ping(self) -> bool: ...
    def close(self) -> None: ...
```

`add` and `list_all` run `ensure_schema` on the same connection the first time (a flag guarded by a lock) and then the operation, so a request opens at most one connection.

### Logging

structlog events; never log the URL, the password or titles:
- `schema_ready` (info, once per store).
- `storage_unavailable` (warning, `operation`, `error` = exception class name).
- `storage_unavailable_at_startup` (warning).
- `database_url_missing` (error, at startup).
- `task_created` (info, `task_id`). `task_count` is dropped because it would cost a query.
- `task_limit_reached` (warning, `limit`).

### Test hooks (tester-owned, in `tests/conftest.py`, written with the acceptance tests)

- `postgres_url` (session): `TEST_DATABASE_URL` when set, else a `testcontainers.postgres.PostgresContainer("postgres:17-alpine")`. It yields a `postgresql://` URL. Import `testcontainers` inside the fixture: t1 adds the dependency, and a top-level import would break collection of every test until then.
- Per-test clean database: `DROP TABLE IF EXISTS tasks` before each test that uses `postgres_url`, then `close_task_store()`.
- Running and restarting the API: `monkeypatch.setenv("DATABASE_URL", url)`, `close_task_store()`, then `with TestClient(app) as client:` (runs the lifespan: schema at startup). A restart or new version is leaving that block (shutdown closes the store) and entering a new one (AC-002.1, .2, .6).
- Unreachable database:
  - At start (AC-002.4): `DATABASE_URL` pointing at a closed local port (`127.0.0.1:<free port>`).
  - During an outage and back (AC-002.3, .5): a TCP proxy fixture between the app and `postgres_url`. `cut()` closes its listener and every open connection; `restore()` listens on the same port again. That also exercises stale pooled connections. Do not use `docker pause` (see the residual risk in Decisions).
- 10,000 rows (AC-002.6): after the API created the table, `INSERT INTO tasks (id, title) SELECT gen_random_uuid(), 't' || g FROM generate_series(1, 10000) AS g`.
- Contract check: override `contract_send` so that it sends through `TestClient(app)` with `app.dependency_overrides[get_task_store] = lambda: TaskStore()` (cleared afterwards). Otherwise its accept cases need a live database.

### Smoke tests (for the testers)

Tasks are now shared by all replicas and survive deploys:
- Read-only, for staging and prod: `GET /ready` → `200 {"status": "ready"}`, and `GET /tasks` → `200` with a list of task-shaped objects.
- Writing (dev only): create `smoke-<uuid>`, then `GET /tasks` contains it.
- Restart, outage and limit criteria are not smoke-testable.

## Data

Table `tasks` in the database of `DATABASE_URL` (default schema), created by `ensure_schema`:

```sql
CREATE TABLE IF NOT EXISTS tasks (
    id         uuid        PRIMARY KEY,
    seq        bigint      GENERATED ALWAYS AS IDENTITY UNIQUE,
    title      text        NOT NULL CHECK (char_length(title) BETWEEN 1 AND 200),
    due_date   date        NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS tasks_created_at_seq_idx ON tasks (created_at, seq);
```

Create, in one transaction:

```text
SELECT pg_advisory_xact_lock(:INSERT_LOCK_KEY)
SELECT count(*) FROM tasks                                  -- >= limit → rollback, TaskLimitReachedError
INSERT INTO tasks (id, title, due_date) VALUES (...) RETURNING id, title, due_date, created_at
COMMIT
```

List: `SELECT id, title, due_date, created_at FROM tasks ORDER BY created_at, seq`. No migration of in-memory data (system A3).
