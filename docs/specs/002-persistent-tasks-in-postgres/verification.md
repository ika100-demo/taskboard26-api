# Verification — 002 Persistent tasks in Postgres

**Result:** pass
**Commit:** 94e1f15 · **Base:** 0142e43 · **Trace:** 7/7 criteria named by tests

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-002.1 | met | `tests/test_postgres_acceptance.py::test_ac_002_1_restart_keeps_tasks` | `src/taskboard26_api/postgres_store.py:120-154`, `src/taskboard26_api/task_store.py:70-78`, `src/taskboard26_api/main.py:41-44` | Compares full task dicts (`id`, `title`, `due_date`, `created_at`) before and after two restarts, checks the rows are in the table, and checks oldest-first order including a task created after the restart. |
| AC-002.2 | met | `tests/test_postgres_acceptance.py::test_ac_002_2_empty_db_table_created_and_empty_list`, `::test_ac_002_2_existing_rows_kept_unchanged` | `src/taskboard26_api/main.py:37-40`, `src/taskboard26_api/postgres_store.py:23-32,104-118` | Uses `to_regclass` to check the table exists right after startup, before any request. `[]` on an empty table. Rows inserted directly (microsecond `created_at`, out of order) come back unchanged and ordered after a restart, and the count stays 2. The DDL is `IF NOT EXISTS` only. |
| AC-002.3 | met | `tests/test_postgres_acceptance.py::test_ac_002_3_db_unreachable_gives_503`, `::test_ac_002_3_unreachable_from_the_start_gives_503` | `src/taskboard26_api/tasks_api.py:42-43,55-58`, `src/taskboard26_api/postgres_store.py:45-48,76-102`, `src/taskboard26_api/main.py:70-74` | For a cut connection, a stalled database and a closed port: GET and POST each answer `503` `{"detail":"storage unavailable"}` in under 5 s, `/ready` 503, `/health` 200 `{"status":"ok"}`. After restore the list is exactly `[stored]`, so nothing was created during the outage. |
| AC-002.4 | met | `tests/test_postgres_acceptance.py::test_ac_002_4_db_unreachable_at_start`, `::test_ac_002_4_database_url_unset_is_unready` | `src/taskboard26_api/main.py:33-44,70-74`, `src/taskboard26_api/postgres_store.py:91-92,156-169` | The lifespan runs on `TestClient` enter and does not raise. `/health` 200, `/ready` 503 `{"status":"unavailable"}`. The same holds when `DATABASE_URL` is unset. |
| AC-002.5 | met | `tests/test_postgres_acceptance.py::test_ac_002_5_db_back_after_outage_without_restart` | `src/taskboard26_api/postgres_store.py:63-70` (`pool_pre_ping`), `:87-102` | 6 s outage (503s are checked throughout), then restore. Without a restart, `/ready` reaches 200 `{"status":"ready"}` within 60 s, the list equals the tasks stored before the outage, and `POST` gives 201 and appends the task. |
| AC-002.6 | met | `tests/test_postgres_acceptance.py::test_ac_002_6_limit_reached_gives_409` | `src/taskboard26_api/postgres_store.py:123-129`, `src/taskboard26_api/tasks_api.py:39-41` | 9,999 rows inserted directly plus the 10,000th through the API (201). The next create gives `409` `{"detail":"task limit reached"}` and the list has 10,000 entries. Same after a restart, and the table count is 10,000. |
| AC-002.7 | met | `tests/test_postgres_acceptance.py::test_ac_002_7_invalid_title_is_422_and_not_stored` (6 cases), `::test_ac_002_7_title_of_200_after_trimming_is_accepted` | `src/taskboard26_api/task_schemas.py:33-49`, `src/taskboard26_api/tasks_api.py:62-68`, `src/taskboard26_api/main.py:48` | Cases: missing, empty, whitespace, 201 characters, 201 characters plus padding. Each gives 422 with `detail` a list whose title entry has `loc[-1] == "title"` and the contract rule id as `type`. Nothing is stored, also after a restart. 200 characters after trimming is accepted. |

## Non-goals

The spec lists no non-goals. Nothing outside the criteria was added: no gitops, Dockerfile or migration-tool changes, and no data carry-over (system A3). The service has no template-owned layout (header, footer, navigation), and none was touched. ✔

## Deviations from the plan

- `tests/conftest.py` `client` fixture changed after the reviewed test commit 437bf5e (outside every task's `files`). It now overrides `get_task_store` with a fresh in-memory `TaskStore` so that spec 001's tests run without a database. Acceptable: this is a fixture change only, no assertion changed, design.md "In-memory TaskStore stays" plans for it, and `cplat spec test-diff` reported no acceptance test changed.
- `postgres_store.py:45-102`: a client-side watchdog (2 s `threading.Timer` plus `_abort_connections`) that design.md does not describe. Design accepted the frozen-server case as a residual risk; the reviewed stall test (AC-002.3) needs this watchdog. Acceptable, with two follow-ups. (a) Update design.md "Timeouts" to describe the watchdog. (b) The watchdog shuts the sockets of **every** pooled connection, including other requests in flight. So one legitimately slow call (more than 2 s, e.g. waiting on `INSERT_LOCK_KEY` under contention) turns concurrent requests into 503s. That is tolerable at taskboard volume, and a candidate for an issue.
- `tasks_api.py:64-65`: `isinstance` check + `raise exc` instead of the planned `assert` (bandit fix 94e1f15). Acceptable, same behaviour.
- Docs outside every task's `files`: `docs/adr/001-*`, `docs/adr/002-*`, `docs/adr/README.md` (the ADRs that design.md marks pending), `docs/backlog.md`, and spec 001 marking AC-001.8 superseded by AC-002.1. `.secrets.baseline.json` covers 3 false positives. Acceptable.
- All tasks t1–t3 are `done: true`.

## Contract

Matches design.md and the system contract. GET/POST `503` `{"detail":"storage unavailable"}`. `/ready` answers `200 {"status":"ready"}` or `503 {"status":"unavailable"}`, and `/health` does not touch the store. 422 `type` is set to `title-required`/`title-min`/`title-max` only for `loc == ["body","title"]` on `POST /tasks`. Only `DATABASE_URL` is read, and the URL is not logged. The connect, statement and pool timeouts match design.md "Timeouts". Contract copy `contract/001-persistent-tasks-and-web-task-board.json` is checked by `tests/test_contract.py` through the `contract_send` override. ✔

## Unresolved test-review findings

| Test | Criterion | Finding |
|---|---|---|
| `tests/test_smoke_persistent_tasks.py::test_smoke_ac_002_5_ready_read_only` | AC-002.5 | A black-box `/ready` 200 reads the same from the in-memory store and from Postgres, and an outage cannot be observed through the base URL. Does not affect the verdict: the criterion is proven by `test_ac_002_5_db_back_after_outage_without_restart`. |
| `tests/test_smoke_persistent_tasks.py::test_smoke_ac_002_1_created_task_is_listed` | AC-002.1 | Proving persistence needs a restart, which a smoke test must not do. Does not affect the verdict: the criterion is proven by `test_ac_002_1_restart_keeps_tasks`. |

The read-only `test_smoke_ac_002_2_list_is_task_shaped_read_only` likewise cannot tell Postgres from the in-memory store. None of the criteria is marked `(smoke)`, so all three smoke tests are deploy health checks, not criterion evidence.

## Mutation check (report only)

4 of 20 mutants tested in 90 s (time budget of 90 s, `--budget`); the score covers the tested ones.

2 of 4 mutants of the changed code were caught by the acceptance tests (50 %; spec 152, report only).

Survived (a test that names the criterion would fail if it checked this):
- `src/taskboard26_api/postgres_store.py:19 7002000000001 → 7002000000002`
- `src/taskboard26_api/postgres_store.py:37 1 → 2`
