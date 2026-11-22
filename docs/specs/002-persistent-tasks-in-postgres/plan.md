---
spec_id: 002-persistent-tasks-in-postgres
shape: service-python
spec_hash: a8fec80c270a
summary: Store tasks in Postgres (DATABASE_URL) with self-created schema, 503 on storage outage, DB-pinging readiness and contract rule ids in 422
tasks:
  - id: t1
    title: Add PostgresTaskStore, the TaskRepository protocol and the database dependencies
    files: [pyproject.toml, uv.lock, src/taskboard26_api/task_store.py, src/taskboard26_api/postgres_store.py, tests/test_postgres_store_unit.py, tests/test_task_store_unit.py]
    covers: [AC-002.1, AC-002.2, AC-002.3, AC-002.5, AC-002.6]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: Map title validation errors to the contract rule ids
    files: [src/taskboard26_api/task_schemas.py, tests/test_task_schemas_unit.py]
    covers: [AC-002.7]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t3
    title: Wire storage outages, readiness, startup schema and contract errors into the app
    files: [src/taskboard26_api/tasks_api.py, src/taskboard26_api/main.py]
    covers: [AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.5, AC-002.6, AC-002.7]
    parallel_safe: true
    depends_on: [t1, t2]
    done: true
---

# Plan — 002 Persistent tasks in Postgres

The contract, the Python interface the tests import, the table and the test hooks are in [design.md](design.md). t1 (storage) and t2 (422 rule ids) run in parallel. t3 wires both into the HTTP app and makes the acceptance tests and the contract check pass. The test fixtures (`postgres_url`, the TCP proxy, the `contract_send` override in `tests/conftest.py`) belong to the testers and exist before coding.

## t1 — Add PostgresTaskStore, the TaskRepository protocol and the database dependencies

**Files:** pyproject.toml, uv.lock, src/taskboard26_api/task_store.py, src/taskboard26_api/postgres_store.py, tests/test_postgres_store_unit.py, tests/test_task_store_unit.py
**Covers:** AC-002.1, AC-002.2, AC-002.3, AC-002.5, AC-002.6
**Goal:** Durable storage behind the interface in design.md "Python interface": the Postgres store with the contract's timeouts, the self-created table, the exact 10,000 limit, and the mapping of outages to `StorageUnavailableError`. `get_task_store()` now hands out the Postgres store.

**Implementation notes:**
- `pyproject.toml`: add runtime `sqlalchemy>=2.0` and `psycopg[binary]>=3.2`, and dev `testcontainers[postgres]>=4.8`. Then run any `devbox run …` (its init hook `uv sync --all-extras` re-locks) and commit the updated `uv.lock`; the Dockerfile builds with `uv sync --locked`. Never call `uv add` directly.
- `task_store.py`: add `StorageUnavailableError` and the `TaskRepository` Protocol (`ensure_schema`, `add`, `list_all`, `ping`). The in-memory `TaskStore` gains `ensure_schema()` as a no-op and `ping() -> True`; everything else stays, because spec 001's tests use it.
- `task_store.py`: `get_task_store() -> TaskRepository` builds `PostgresTaskStore(os.environ.get("DATABASE_URL"))` on its first call, under a `threading.Lock`. Use a function-local import, because `postgres_store` imports this module. `close_task_store()` calls `close()` on it and resets it to `None`. Nothing connects at import.
- `postgres_store.py`, engine: built in `__init__` without connecting (`create_engine` is lazy). Use `make_url(url).set(drivername="postgresql+psycopg")` and the pool and `connect_args` from design.md "Timeouts", plus `application_name=taskboard26-api`. With `database_url` `None` or empty, no engine: every operation raises `StorageUnavailableError` and `ping()` returns `False`.
- `postgres_store.py`, `ensure_schema()`: in `engine.begin()`, `SELECT pg_advisory_xact_lock(SCHEMA_LOCK_KEY)`, then the DDL in design.md "Data". It sets the flag `_schema_ready` (guarded by a lock) and logs `schema_ready` once. `add` and `list_all` call the same helper on their own connection while the flag is unset.
- `add(title, due_date)`: one `engine.begin()` transaction: lock `INSERT_LOCK_KEY`, `count(*)`, raise `TaskLimitReachedError` at `limit`, then `INSERT … RETURNING id, title, due_date, created_at` with `id=uuid4()`. Return a `Task`; `created_at` comes from the database (`clock_timestamp()`).
- `list_all()`: `SELECT id, title, due_date, created_at FROM tasks ORDER BY created_at, seq`, returned as `list[Task]`.
- `ping()`: `SET LOCAL statement_timeout = '2s'; SELECT 1` in a transaction. It returns `True` or `False` and never raises.
- Error mapping: wrap every database call. `sqlalchemy.exc.OperationalError`, `InterfaceError` and `TimeoutError` become `StorageUnavailableError` (chained). Log `storage_unavailable` (warning, `operation`, `error` = class name only; never the URL). `close()` calls `engine.dispose()`.
- Constants: `SCHEMA_LOCK_KEY`, `INSERT_LOCK_KEY` (two distinct fixed bigints), `TABLE = "tasks"`. Fully typed; `mypy --strict` passes.
- Tests in `tests/test_postgres_store_unit.py` use conftest's `postgres_url`:
  - `ensure_schema` twice is harmless and keeps the rows.
  - add and list round-trip with microsecond `created_at` in UTC.
  - A new store instance sees the same rows.
  - The limit (small `limit`) raises and stores nothing.
  - `PostgresTaskStore(None)` and a closed-port URL raise `StorageUnavailableError` within 5 s, and `ping()` returns `False` for them.
  - `get_task_store()` / `close_task_store()` rebuild from the environment.
- `tests/test_task_store_unit.py`: add a test that the in-memory `ping()` is `True` and `ensure_schema()` is a no-op.

**Done when:** `tests/test_postgres_store_unit.py` and `tests/test_task_store_unit.py` pass and `devbox run quality` is green. The HTTP acceptance tests pass only after t3.

## t2 — Map title validation errors to the contract rule ids

**Files:** src/taskboard26_api/task_schemas.py, tests/test_task_schemas_unit.py
**Covers:** AC-002.7
**Goal:** A pure function that gives the validation errors of `POST /tasks` the contract's rule ids as `type`, as design.md "Contract error types" specifies. t3 registers it as the 422 handler.

**Implementation notes:**
- `TITLE_RULE_TYPES: Final[Mapping[str, str]] = {"missing": "title-required", "string_too_short": "title-min", "string_too_long": "title-max"}`.
- `with_contract_types(errors: Sequence[Any]) -> list[Any]` returns a new list of shallow-copied entries. An entry whose `tuple(loc) == ("body", "title")` and whose `type` is a key of the mapping gets the mapped `type`. Every other key and every other entry stays unchanged, including `string_type` and the `due_date` errors.
- Leave `TaskCreate` and `TaskOut` unchanged: trimming then `min_length=1` already turns `""` and `"   "` into `string_too_short`.
- Unit tests: validate real `TaskCreate` payloads (`{}`, `""`, `"   "`, 201 characters, `None`, `123`, a bad `due_date`), run `with_contract_types` over `exc.errors()` with the `("body",)` prefix FastAPI adds, and assert the resulting types. Also assert that the input list is not mutated.

**Done when:** `tests/test_task_schemas_unit.py` passes and `devbox run quality` is green. The contract check passes only after t3.

## t3 — Wire storage outages, readiness, startup schema and contract errors into the app

**Files:** src/taskboard26_api/tasks_api.py, src/taskboard26_api/main.py
**Covers:** AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.5, AC-002.6, AC-002.7
**Goal:** The HTTP behaviour of design.md "Contract": `503` on storage outages, `/ready` backed by `store.ping()`, the schema created at startup without ever failing the start, and the contract's 422 types.

**Implementation notes:**
- `tasks_api.py`: `StoreDep = Annotated[TaskRepository, Depends(get_task_store)]`. Both endpoints catch `StorageUnavailableError` and raise `HTTPException(503, detail="storage unavailable")`, and document `503` in `responses`. Keep the `409` path. `task_created` logs `task_id` only; drop `len(store)`.
- `tasks_api.py`: `async def validation_exception_handler(request: Request, exc: Exception) -> Response`. Type the parameter as `Exception` with an `isinstance(exc, RequestValidationError)` assert, so Starlette's handler type checks under mypy. For `POST /tasks` it applies `with_contract_types(exc.errors())`, then delegates to `fastapi.exception_handlers.request_validation_exception_handler(request, RequestValidationError(errors, body=exc.body))`.
- `main.py`: `app.add_exception_handler(RequestValidationError, validation_exception_handler)`.
- `main.py`: add a `lifespan` async context manager, passed to `FastAPI(lifespan=...)`.
  - Startup: when `DATABASE_URL` is unset or empty, log `database_url_missing` (error). Call `get_task_store().ensure_schema()`; on `StorageUnavailableError`, log `storage_unavailable_at_startup` (warning) and continue. Never raise.
  - Shutdown: `close_task_store()`.
- `main.py`: `/ready` takes `store: StoreDep` and returns `HealthResponse(status="ready")` when `store.ping()` is true, else `JSONResponse(status_code=503, content={"status": "unavailable"})`, with `503` documented in `responses`.
- `main.py`: leave `/health`, `/ping` and `/metrics` unchanged; `/health` must not touch the store.
- Keep the middleware and router order as is.

**Done when:** every acceptance test for AC-002.1 to AC-002.7, spec 001's acceptance tests and `tests/test_contract.py` pass, and `devbox run ci` is green.
