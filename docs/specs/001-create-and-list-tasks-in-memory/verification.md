# Verification — 001 Create and list tasks (in memory)

**Result:** pass
**Commit:** e82e1f7 · **Base:** 32e57c2 · **Trace:** 8/8 criteria named by tests (smoke: AC-001.1, .3, .4)

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-001.1 | met | `tests/test_tasks_acceptance.py::test_ac_001_1_create_task_returns_201_and_task_object`; smoke `tests/test_smoke_tasks.py::test_smoke_ac_001_1_create_task` (`smoke` + `writes`) | `src/taskboard26_api/tasks_api.py:18-32`, `src/taskboard26_api/task_store.py:33`, `src/taskboard26_api/task_schemas.py:54-59` | Asserts 201, exact field set, canonical UUID, title, due_date, `created_at` ISO 8601 with `Z` (UTC). |
| AC-001.2 | met | `tests/test_tasks_acceptance.py::test_ac_001_2_no_due_date_is_null` (absent and `null`) | `src/taskboard26_api/task_schemas.py:21-23,45` | Asserts 201 and `due_date` present and `null`. |
| AC-001.3 | met | `tests/test_tasks_acceptance.py::test_ac_001_3_list_returns_tasks_oldest_first`; smoke `tests/test_smoke_tasks.py::test_smoke_ac_001_3_list_tasks_read_only` | `src/taskboard26_api/tasks_api.py:35-38`, `src/taskboard26_api/task_store.py:37-39` | Asserts `[]` on empty, then the list equals the three POST responses (same values) in order A, B, C. Smoke is read-only, as design.md requires for multi-replica deployments. |
| AC-001.4 | met | `tests/test_tasks_acceptance.py::test_ac_001_4_invalid_title_is_422` (missing, null, 123, true, "", "   ", 201 chars, 201 chars padded), `::test_ac_001_4_title_of_200_chars_after_trim_is_accepted`; smoke `tests/test_smoke_tasks.py::test_smoke_ac_001_4_invalid_title_is_422` | `src/taskboard26_api/task_schemas.py:44` | Asserts 422, `loc ["body","title"]` in `detail`, and `GET /tasks` still `[]`; boundary 200 after trim accepted. |
| AC-001.5 | met | `tests/test_tasks_acceptance.py::test_ac_001_5_invalid_due_date_is_422` (all four spec examples plus `T00:00:00Z` and integer) | `src/taskboard26_api/task_schemas.py:17-29,45` | Asserts 422, `loc ["body","due_date"]`, nothing stored. |
| AC-001.6 | met | `tests/test_tasks_acceptance.py::test_ac_001_6_title_is_trimmed` | `src/taskboard26_api/task_schemas.py:44` | Asserts returned and listed title `"Buy milk"`. |
| AC-001.7 | met | `tests/test_tasks_acceptance.py::test_ac_001_7_task_limit_gives_409` | `src/taskboard26_api/task_store.py:8,29-35`, `src/taskboard26_api/tasks_api.py:26-30` | Store prefilled with 10,000 (default `MAX_TASKS`); asserts 409, `detail == "task limit reached"`, list length 10,000. Limit check under a lock. |
| AC-001.8 | met | `tests/test_tasks_acceptance.py::test_ac_001_8_restart_gives_empty_list` | `src/taskboard26_api/task_store.py:23-27,46-50` | The restart is modelled as a fresh `TaskStore()` (the hook design.md defines); a store that loaded persisted tasks in its constructor would fail it. Code review: no file, env var or external call; module state is only `_store`. |

## Non-goals

No single-task read/update/delete, no persistence, no filtering/sorting/pagination, no extra fields (response field set asserted exactly), no users and no auth were added. `main.py` gains only the router import and `include_router` (`src/taskboard26_api/main.py:16,27`); `/health`, `/ready`, `/ping`, `/metrics` are unchanged. ✔

## Deviations from the plan

- `tests/test_tasks_acceptance.py`, `tests/test_smoke_tasks.py` are in no task's `files`: they are the acceptance and smoke tests written before the build (red commit f2619bc); acceptable.
- `docs/specs/001-.../{spec,design,plan}.md` changed: spec status `approved` → `building` plus changelog line, design and plan added; acceptable.
- All tasks t1–t3 are `done: true`; every source file sits in its task's `files`.
- Minor: `tasks_api.py:29` logs `limit=MAX_TASKS` rather than the store's actual limit (differs only when a test injects a smaller store); not in any criterion; acceptable.

## Contract

Matches `design.md`: fields `id`/`title`/`due_date`/`created_at` only, `created_at` UTC with microseconds and `Z` (`task_schemas.py:59`), 422 body is FastAPI's default with the specified `loc`, 409 `{"detail": "task limit reached"}`, `GET /tasks` creation order, dependency `get_task_store` as the test hook. No `contract/` copy exists for this service, so no contract-rule cases apply. ✔

## Checks

`devbox run ci` green (quality, test, security) per the Phase 3 summary; acceptance tests unchanged since the red commit f2619bc. No suppressions, no tightened tests, no unresolved test-review findings.

## Mutation check (report only)

17 of 20 mutants of the changed code were caught by the acceptance tests (85 %; spec 152, report only).

Survived (a test that names the criterion would fail if it checked this):
- `src/taskboard26_api/task_schemas.py:56 Is → IsNot`
- `src/taskboard26_api/task_store.py:11 True → False`
- `src/taskboard26_api/task_store.py:11 True → False`
