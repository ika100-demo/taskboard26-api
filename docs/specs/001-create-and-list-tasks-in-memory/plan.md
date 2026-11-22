---
spec_id: 001-create-and-list-tasks-in-memory
shape: service-python
spec_hash: 436cee3e5ca7
summary: In-memory POST /tasks and GET /tasks with title/due_date validation and a 10,000-task limit
tasks:
  - id: t1
    title: Add bounded, thread-safe in-memory TaskStore
    files: [src/taskboard26_api/task_store.py, tests/test_task_store_unit.py]
    covers: [AC-001.3, AC-001.7, AC-001.8]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: Add TaskCreate and TaskOut schemas with title and due_date validation
    files: [src/taskboard26_api/task_schemas.py, tests/test_task_schemas_unit.py]
    covers: [AC-001.1, AC-001.2, AC-001.4, AC-001.5, AC-001.6]
    parallel_safe: true
    depends_on: []
  - id: t3
    title: Expose POST /tasks and GET /tasks and include the router in the app
    files: [src/taskboard26_api/tasks_api.py, src/taskboard26_api/main.py]
    covers: [AC-001.1, AC-001.2, AC-001.3, AC-001.4, AC-001.5, AC-001.6, AC-001.7, AC-001.8]
    parallel_safe: true
    depends_on: [t1, t2]
---

# Plan — 001 Create and list tasks (in memory)

The contract (fields, status codes, error format, the Python interface tests import) is in [design.md](design.md). t1 and t2 run in parallel; t3 wires them into the app and makes the acceptance tests pass.

## t1 — Add bounded, thread-safe in-memory TaskStore

**Files:** src/taskboard26_api/task_store.py, tests/test_task_store_unit.py
**Covers:** AC-001.3, AC-001.7, AC-001.8
**Goal:** The storage half of the feature: an ordered, bounded, process-local store with exactly the interface in design.md "Python interface", so the router and the acceptance tests can rely on it.

**Implementation notes:**
- `MAX_TASKS = 10_000`; `Task` frozen slotted dataclass (`id: UUID`, `title: str`, `due_date: date | None`, `created_at: datetime`).
- `TaskLimitReachedError(Exception)`.
- `TaskStore.__init__(limit=MAX_TASKS)` holds a `list[Task]` and a `threading.Lock`.
- `add(title, due_date)`: under the lock, raise `TaskLimitReachedError` when `len >= limit`, else build `Task(uuid4(), title, due_date, datetime.now(UTC))`, append, return it. The store does not trim or validate; t2's schema does.
- `list_all()` returns a copy (`list(self._tasks)`) in insertion order; `__len__` returns the count.
- Module-level `_store = TaskStore()` and `get_task_store() -> TaskStore` returning it. No persistence of any kind (AC-001.8).
- Unit tests: insertion order kept; `list_all` returns a copy; limit raises and leaves the count unchanged (use a small `limit`); `created_at` is UTC-aware; ids unique; a fresh `TaskStore()` is empty.

**Done when:** `tests/test_task_store_unit.py` passes and `devbox run quality` is green. The acceptance tests pass only after t3.

## t2 — Add TaskCreate and TaskOut schemas with title and due_date validation

**Files:** src/taskboard26_api/task_schemas.py, tests/test_task_schemas_unit.py
**Covers:** AC-001.1, AC-001.2, AC-001.4, AC-001.5, AC-001.6
**Goal:** The wire format: a request model that trims and validates exactly as design.md's `POST /tasks` table says, and a response model that serializes the Task object exactly as specified.

**Implementation notes:**
- `TaskCreate(BaseModel)` with default `extra="ignore"` (A8).
- `title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]`; pydantic's default `str` rejects numbers, booleans and `null`, giving `loc ["body","title"]` through FastAPI.
- `due_date: Annotated[date | None, BeforeValidator(_parse_calendar_date)] = None`; `_parse_calendar_date`: `None` → `None`; a `str` that fully matches `^[0-9]{4}-[0-9]{2}-[0-9]{2}$` → `date.fromisoformat(value)`; anything else, or a `fromisoformat` failure, raises `ValueError("due_date must be a calendar date in YYYY-MM-DD form")`.
- `TaskOut(BaseModel)`: `id: UUID`, `title: str`, `due_date: date | None`, `created_at: datetime`; classmethod `from_task(task)`. Takes the task as any object with those attributes (a `Protocol` or plain attribute access) so it does not import `task_store` and stays independent of t1.
- Unit tests: trimming; 200 vs 201 characters after trimming; empty/whitespace/non-string/missing titles fail; every due_date example in design.md fails; `None`/absent give `None`; `TaskOut.model_dump(mode="json")` yields `due_date` `null` or `"YYYY-MM-DD"` and `created_at` ending in `Z`.

**Done when:** `tests/test_task_schemas_unit.py` passes and `devbox run quality` is green. The acceptance tests pass only after t3.

## t3 — Expose POST /tasks and GET /tasks and include the router in the app

**Files:** src/taskboard26_api/tasks_api.py, src/taskboard26_api/main.py
**Covers:** AC-001.1, AC-001.2, AC-001.3, AC-001.4, AC-001.5, AC-001.6, AC-001.7, AC-001.8
**Goal:** The HTTP surface from design.md "Contract", using t1's store through the `get_task_store` dependency and t2's schemas.

**Implementation notes:**
- `router = APIRouter(tags=["tasks"])`; endpoints are plain `def`.
- `POST /tasks`, `status_code=201`, `response_model=TaskOut`, `responses={409: ...}` documented: `store.add(body.title, body.due_date)`; on `TaskLimitReachedError` log `task_limit_reached` (warning, `limit`) and raise `HTTPException(409, detail="task limit reached")`; else log `task_created` (info, `task_id`, `task_count`) and return `TaskOut.from_task(task)`.
- `GET /tasks`, `response_model=list[TaskOut]`: `[TaskOut.from_task(t) for t in store.list_all()]`.
- Store injected as `Annotated[TaskStore, Depends(get_task_store)]` so tests override it.
- `main.py`: `from .tasks_api import router as tasks_router`; `app.include_router(tasks_router)` after the middleware setup. Leave `/health`, `/ready`, `/ping`, `/metrics` unchanged.
- Logger: `structlog.get_logger(__name__)`; never log titles.

**Done when:** every acceptance test for AC-001.1 to AC-001.8 passes and `devbox run ci` is green.
