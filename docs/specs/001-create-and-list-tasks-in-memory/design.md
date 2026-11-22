# Design — 001 Create and list tasks (in memory)

## Decisions

- Three flat modules next to the existing `metrics.py` / `logging_config.py` (the repo's layout is flat): `task_store.py` (storage), `task_schemas.py` (wire format and validation), `tasks_api.py` (an `APIRouter` that `main.py` includes). Storage and validation have no dependency on each other, so they are built in parallel.
- The store is one process-wide `TaskStore` instance created at import and handed to the endpoints through the FastAPI dependency `get_task_store`. That makes AC-001.8 true by construction (a new process builds an empty store; there is no persistence path: no file, no env var, no external call) and gives tests one override point (`app.dependency_overrides[get_task_store]`).
- The endpoints are plain `def` (run in FastAPI's threadpool), so `TaskStore.add` takes a `threading.Lock` around the limit check and the append: the 10,000 limit (AC-001.7) holds under concurrent requests.
- `due_date` is validated by our own before-validator (`^[0-9]{4}-[0-9]{2}-[0-9]{2}$`, then `date.fromisoformat`), not by pydantic's `date` parsing alone: pydantic's lax mode also accepts Unix timestamps and datetime strings with zero time (`"2026-12-24T00:00:00Z"`), which AC-001.5 rejects.
- Validation runs before the limit check: an invalid body at the limit answers `422`, a valid one `409`.
- No ADR: in-memory storage is explicitly temporary (A10, durable storage is a later spec), and the router-per-feature module follows FastAPI's standard pattern; nothing here outlives the feature.
- No new dependency, no new environment variable, no gitops change: port, probes and image stay as they are.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `src/taskboard26_api/task_store.py` | `Task` record, `TaskStore` (bounded, ordered, thread-safe), `get_task_store` dependency | new |
| `src/taskboard26_api/task_schemas.py` | `TaskCreate` (request, trimming + validation), `TaskOut` (response) | new |
| `src/taskboard26_api/tasks_api.py` | `router`: `POST /tasks`, `GET /tasks`, structured logging | new |
| `src/taskboard26_api/main.py` | `app.include_router(tasks_api.router)` | changed |

## Contract

No authentication on either endpoint (spec non-goal). Both consume and produce `application/json`.

### Task object (response)

| Field | Type | Notes |
|---|---|---|
| `id` | string | UUID (version 4), canonical lowercase hyphenated form, server-generated (AC-001.1, A2) |
| `title` | string | trimmed, 1..200 characters (AC-001.6) |
| `due_date` | string \| null | `YYYY-MM-DD`; always present, `null` when the task has none (AC-001.2, A5) |
| `created_at` | string | UTC, ISO 8601 with `Z` suffix and microseconds, e.g. `"2026-11-22T10:15:30.123456Z"` (AC-001.1, A3) |

No other fields. Unknown fields in a request are ignored and never echoed (A8).

### `POST /tasks`

Request body (JSON object):

| Field | Required | Rule | Violation |
|---|---|---|---|
| `title` | yes | JSON string; leading/trailing whitespace (Python `str.strip()`) removed; then 1..200 characters | `422`, `loc == ["body", "title"]` (AC-001.4) |
| `due_date` | no | absent or `null` → no due date; otherwise a JSON string matching `^[0-9]{4}-[0-9]{2}-[0-9]{2}$` that is a real calendar date; past dates allowed | `422`, `loc == ["body", "due_date"]` (AC-001.5) |

Responses:

- `201` — the created Task object (AC-001.1, AC-001.2, AC-001.6).
- `422` — FastAPI's standard validation body: `{"detail": [{"type": str, "loc": ["body", "<field>"], "msg": str, "input": any, ...}]}`. One entry per failing field; an entry for `title` has `loc` `["body", "title"]`, for `due_date` `["body", "due_date"]`. Examples that answer 422 on `title`: missing, `null`, `123`, `true`, `""`, `"   "`, a 201-character string after trimming. On `due_date`: `"2026-02-30"`, `"24.12.2026"`, `"tomorrow"`, `"2026-12-24T10:00:00Z"`, `"2026-12-24T00:00:00Z"`, `20261224`. A body that is not a JSON object answers 422 as well (FastAPI default). Nothing is stored (AC-001.4, AC-001.5).
- `409` — `{"detail": "task limit reached"}` when 10,000 tasks exist and the body is valid. Nothing is stored (AC-001.7).

### `GET /tasks`

- `200` — JSON array of every stored Task object, in creation order (oldest first), each exactly as returned by its `POST`; `[]` when none exist (AC-001.3, AC-001.8). No query parameters, no pagination.

### Python interface (what acceptance tests may import)

```python
# taskboard26_api.task_store
MAX_TASKS: int = 10_000

@dataclass(frozen=True, slots=True)
class Task:
    id: UUID
    title: str              # already trimmed
    due_date: date | None
    created_at: datetime    # timezone-aware, UTC

class TaskLimitReachedError(Exception): ...

class TaskStore:
    def __init__(self, limit: int = MAX_TASKS) -> None: ...
    def add(self, title: str, due_date: date | None) -> Task: ...  # uuid4 id, created_at=now(UTC); raises TaskLimitReachedError at limit
    def list_all(self) -> list[Task]: ...                          # a copy, creation order
    def __len__(self) -> int: ...

def get_task_store() -> TaskStore: ...  # returns the process-wide instance
```

Test hooks: a test gets an isolated, empty store with `app.dependency_overrides[get_task_store] = lambda: store` where `store = TaskStore()` (clear the override afterwards). AC-001.7 can prefill that store with `store.add(...)` 10,000 times instead of 10,000 HTTP calls. A restart (AC-001.8) is what a new process does: build a new, empty `TaskStore`; the module keeps no state anywhere else.

### Logging

`tasks_api` logs through structlog: `task_created` (info; `task_id`, `task_count`) and `task_limit_reached` (warning; `limit`). Titles are user content and are not logged.

### Smoke tests (for the testers)

AC-001.1, .3 and .4 are marked smoke. The deployment may run several replicas, each with its own tasks (A10), so a smoke test must not assume a task it created appears in a later `GET /tasks`: the create check (AC-001.1, `writes`) asserts the `POST` response only; the list check (AC-001.3) asserts `200` with a JSON array of Task-shaped objects and stays read-only so it runs in staging and prod; the invalid-title check (AC-001.4) asserts the `422` and its `loc`.

## Data

In memory only: a `list[Task]` inside `TaskStore`, bounded at `MAX_TASKS` (10,000), guarded by a `threading.Lock`. No migration.
