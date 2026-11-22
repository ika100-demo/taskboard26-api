---
spec_id: 002-persistent-tasks-in-postgres
title: Persistent tasks in Postgres
status: done
priority: P1
shape: service-python
parent: ika100-demo/taskboard26-gitops:001-persistent-tasks-and-web-task-board
---

# 002 — Persistent tasks in Postgres

## Problem

The Task API keeps tasks only in the memory of its running process. Every restart or new deploy empties the list, so in dev and staging people lose what they wrote down each time a new version goes out. Also, a person can reach tasks only by calling the API directly: the Task board web UI is deployed but shows nothing yet. Keeping tasks in a Postgres database and giving the web UI a board that lists and creates tasks makes the taskboard usable by people, not only by API clients.

## System context

Slice of the system plan `001-persistent-tasks-and-web-task-board` in `ika100-demo/taskboard26-gitops` for `taskboard26-api` (service-python). The system criteria and the contract below are binding: every criterion of this spec implements one of them and names it: `(system AC-<NNN>.<n>)`.

### System criteria

- **AC-001.1** Given tasks were created through `POST /tasks` of the Task API, when the Task API restarts or a new version of it is deployed, then `GET /tasks` returns `200` with the same tasks, each with the same `id`, `title`, `due_date` and `created_at`, oldest first.
- **AC-001.2** Given the database of the environment is unreachable, when a client sends `GET /tasks` or a valid `POST /tasks` to the Task API, then the response is `503` with `detail` `"storage unavailable"`, no task is created, the API's readiness check answers `503` and its liveness check keeps answering `200`.
- **AC-001.3** Given the database was unreachable and becomes reachable again, when 60 seconds have passed, then without a restart of the Task API `GET /tasks` returns `200` with every task stored before the outage and a valid `POST /tasks` returns `201`.
- **AC-001.6** Given the board is open, when a person submits a title that is empty or only whitespace, or longer than 200 characters after trimming, or the Task API answers `409` (10,000 tasks reached), then the board shows "Enter a title", "Title must be at most 200 characters" or "Task limit reached" respectively next to the form, keeps the entered values, and no new task is listed by the board or by `GET /tasks`.

### Contract

Provider: `taskboard26-api`. Consumer: `taskboard26-web`, server-side only, at the base URL `TASK_API_URL` (in the cluster `http://taskboard26-api`). All bodies are JSON (`Content-Type: application/json`). No authentication (system A9). Everything except the `503` answers is the API's existing contract from API spec 001, unchanged (system A1).

**Task object**

| Field | Type | Notes |
|---|---|---|
| `id` | string, UUID | server-generated, never reused |
| `title` | string | trimmed, 1 to 200 characters |
| `due_date` | string `YYYY-MM-DD` or `null` | calendar date, no time; past dates allowed |
| `created_at` | string, UTC ISO 8601 with microseconds and `Z`, e.g. `2026-11-22T10:15:30.123456Z` | server-set, unchanged by restarts |

**`GET /tasks`** — list all tasks.

| Status | Body | Meaning |
|---|---|---|
| `200` | JSON array of task objects, oldest first (by `created_at`), no pagination; `[]` when none | stored tasks, the same across restarts and redeploys |
| `503` | `{"detail": "storage unavailable"}` | the database is unreachable |

**`POST /tasks`** — create a task.

Request: `{"title": "<string>", "due_date": "<YYYY-MM-DD>" | null}`; `due_date` may be omitted (same as `null`); unknown fields are ignored. The board sends the title as entered (the API trims it) and omits `due_date` when the field is empty.

| Status | Body | Meaning |
|---|---|---|
| `201` | the created task object | stored durably before the answer |
| `422` | `{"detail": [{"loc": ["body", "<field>"], "msg": "<text>", "type": "<rule>"}, ...]}` | invalid `title` or `due_date`; nothing stored |
| `409` | `{"detail": "task limit reached"}` | 10,000 tasks are stored; nothing stored |
| `503` | `{"detail": "storage unavailable"}` | the database is unreachable; nothing stored |

**Probes of the API:** `GET /health` answers `200` `{"status": "ok"}` whenever the process runs, independent of the database. `GET /ready` answers `200` `{"status": "ready"}` when a database ping succeeds, else `503`. The board's probes `/api/health` and `/api/ready` never call the Task API.

**Events:** none.

### Rules

```yaml
rules:
  - id: title-required
    endpoint: POST /tasks
    field: title
    kind: required
    value: true
    provider: taskboard26-api
    consumers: [taskboard26-web]
  - id: title-min
    endpoint: POST /tasks
    field: title
    kind: min_length
    value: 1
    provider: taskboard26-api
    consumers: [taskboard26-web]
  - id: title-max
    endpoint: POST /tasks
    field: title
    kind: max_length
    value: 200
    provider: taskboard26-api
    consumers: [taskboard26-web]
```

Rules no tool checks:

- Both length rules apply to the title **after trimming** leading and trailing whitespace: a title of only whitespace counts as empty. The board checks them before sending and shows "Enter a title" for `title-required` / `title-min` and "Title must be at most 200 characters" for `title-max`; the API enforces them again with `422`.
- `due_date` must be a calendar date in `YYYY-MM-DD` form or `null`/absent; anything else is `422` naming `due_date`. The board uses a date input, so it only ever sends a valid date or omits the field.
- At most 10,000 tasks are stored; a further valid create is `409` `"task limit reached"`. The board does not count tasks itself, it maps the `409`.
- The board shows its own fixed English messages, never the API's `detail` text (system A8).

### Errors

```yaml
errors:
  status: 422
  body:
    list: detail
    field: loc
    rule: type
    message: msg
  unlisted:
    message: "Task could not be saved. Try again."
```

A validation error is `422` with `detail` a list; each entry's `loc` is a list whose last element is the field name (`title` or `due_date`), `type` the rule that failed and `msg` a text for logs only. Other answers carry `detail` as one string: `409` `"task limit reached"`, `503` `"storage unavailable"`.

How the board treats answers:

| Call | Answer | Board shows |
|---|---|---|
| `GET /tasks` | `200` | the list, or "No tasks yet" for `[]` |
| `GET /tasks` | `503`, any other `5xx`, any status not listed above, a body that is not a task array, connection error, timeout | "Tasks could not be loaded. Try again later." in place of the list; the page itself answers `200` |
| `POST /tasks` | `201` | the returned task appended at the end of the list, form emptied |
| `POST /tasks` | `409` | "Task limit reached" next to the form, values kept |
| `POST /tasks` | `422` (its own checks passed, so the API disagrees), `503`, any other `5xx`, any status not listed above, connection error, timeout | "Task could not be saved. Try again." next to the form, values kept, no task added to the list |

### Timeouts

- **Board → Task API, `GET /tasks`:** 5 seconds for the whole request (connect and response). On timeout or connection error the board renders the page with "Tasks could not be loaded. Try again later."; no retry while rendering, a reload tries again.
- **Board → Task API, `POST /tasks`:** 5 seconds. On timeout or connection error the board shows "Task could not be saved. Try again." and keeps the values; it never retries by itself, because a create that timed out may have been stored (a reload shows it).
- **Task API → Postgres:** connect timeout 2 seconds, statement timeout 3 seconds, so a request answers `503` `"storage unavailable"` within 5 seconds of the database becoming unreachable or slow and the board's 5 seconds are not exceeded. A broken pooled connection is discarded and a new one is opened on the next request; no request waits for the database to come back.
- **Task API readiness:** `GET /ready` pings the database with a 2-second timeout and answers `503` when it fails. Kubernetes probes readiness every 5 seconds, so after the database returns the API is ready again within seconds, well inside the 60 seconds of AC-001.3. Liveness never touches the database, so an outage never restarts the API (system A5).
- **When the API is down or unready in the cluster:** an unready API pod is removed from its Service, so the board may see a connection error instead of the API's `503`; it treats both alike (the rows above). A client going through the Gateway may likewise get the Gateway's own `503` instead of the API's body during an outage; AC-001.2's body is checked by the API's own tests against the process.

### Contract rules

Copy: `contract/001-persistent-tasks-and-web-task-board.json`, from plan `001-persistent-tasks-and-web-task-board` at `ika100-demo/taskboard26-gitops@17f66c2`. The repo's contract check reads it.

| Rule | Endpoint | Field | Kind | Value | Status | Role |
|---|---|---|---|---|---|---|
| title-max | POST /tasks | title | max_length | 200 | 422 | provider |
| title-min | POST /tasks | title | min_length | 1 | 422 | provider |
| title-required | POST /tasks | title | required | True | 422 | provider |

Errors: status 422; body `detail[]` of objects with `loc`, `type`, `msg`; responses the contract does not list: show "Task could not be saved. Try again.".

### Provided by the system

The gitops part of this plan wires these for this repo; rely on them, do not ask for them again:

- resource `postgres`: env `DATABASE_URL`, `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`

### Notes for this repo

Storage switches from the in-memory store to the Postgres database the gitops entry wires in (`DATABASE_URL`, `PG*`
from the CloudNativePG Secret). The existing endpoints, fields, validation, 422/409 answers and the 10,000-task limit
of API spec 001 stay as they are (system A1); API spec 001's A10 no longer holds (system A2). No carry-over of
in-memory tasks (system A3). Keep `created_at` at microsecond precision and order by it with an insertion sequence
as tie-breaker. Liveness never touches the database; readiness pings it with the timeouts of the contract.

## Stories

<!-- As a <persona>, I want <goal>, so that <benefit>. -->

## Acceptance criteria

- **AC-002.1** Given tasks were created through `POST /tasks` and the database at `DATABASE_URL` keeps running, when the Task API process is restarted or replaced by a new version, then `GET /tasks` returns `200` with the same tasks, each with the same `id`, `title`, `due_date` and `created_at`, oldest first (system AC-001.1) (replaces AC-001.8)
- **AC-002.2** Given an empty database at `DATABASE_URL`, when the Task API starts, then it creates its table itself and `GET /tasks` returns `200` with `[]`; given the table already holds tasks, when the Task API starts, then it keeps every stored task unchanged (system AC-001.1)
- **AC-002.3** Given the database at `DATABASE_URL` is unreachable, when a client sends `GET /tasks` or a valid `POST /tasks`, then the response is `503` with `detail` `"storage unavailable"` within 5 seconds, no task is created, `GET /ready` answers `503` and `GET /health` keeps answering `200` (system AC-001.2)
- **AC-002.4** Given the database is unreachable when the Task API starts, when it starts, then the process keeps running, `GET /health` answers `200` and `GET /ready` answers `503` (system AC-001.2)
- **AC-002.5** Given the database was unreachable and becomes reachable again, when 60 seconds have passed, then without a restart `GET /ready` answers `200`, `GET /tasks` returns `200` with every task stored before the outage and a valid `POST /tasks` returns `201` (system AC-001.3)
- **AC-002.6** Given 10,000 tasks are stored in the database, when a client sends a further valid `POST /tasks`, then the response is `409` with `detail` `"task limit reached"` and `GET /tasks` still lists 10,000 tasks, also after a restart (system AC-001.6)
- **AC-002.7** Given the contract's rules for `POST /tasks`, when a client sends a title that is missing, empty or only whitespace after trimming, or longer than 200 characters after trimming, then the response is `422` with `detail` a list whose entry has `loc` ending in `title`, and no task is stored (system AC-001.6)

## Non-goals

## Assumptions

<!-- Spec 149: decisions taken by default, approved with the spec. One bullet each: - **A1** <the decision> (other option: <…>; affects AC-…). A revised one is struck through (~~…~~), never deleted. -->

## Open questions

<!-- Only what may not be decided by default (spec 149): security or access, money, destroying or migrating data, or a request too ambiguous to build. Approval is refused while any is open. Strike answered ones (~~…~~) and fold the answer into the criteria. -->

<!-- Priority levels (spec 196) for the product-manager's PRIORITY line: P0 an outage, data loss, a security problem, or something that blocks all other work; P1 a normal bug or feature; the fallback when nothing signals urgency; P2 cosmetic, a convenience, or something with an easy workaround. A reason is "P<n>: <phrase>", one of: P0: outage, data loss, security problem, blocks all other work; P1: normal bug or feature; P2: cosmetic, convenience, easy workaround. -->

## Changelog

- 2026-11-22 created from the system plan, with its criteria (spec 147)
- 2026-11-22 approved
- 2026-11-22 building
- 2026-11-22 done
