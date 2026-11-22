---
spec_id: 001-create-and-list-tasks-in-memory
title: Create and list tasks (in memory)
status: building
priority: P1
shape: service-python
---

# 001 — Create and list tasks (in memory)

## Problem

The Task API is deployed but holds no tasks yet: it answers only health, readiness, ping and metrics, so a client of the taskboard has nothing to record or show. Users need a first, minimal way to write down a task with a title and, when it has one, a due date, and to see all tasks again. Keeping tasks in memory gives a working API now, without choosing storage yet; tasks are lost when the service restarts.

## Stories

As a taskboard user (through a client of the Task API), I want to create a task with a title and an optional due date, so that I can write down what I have to do and by when.

As a taskboard user, I want to list all tasks, so that I can see what I have recorded.

## Acceptance criteria

- **AC-001.1** Given the service is running, when a client sends `POST /tasks` with the JSON body `{"title": "Buy milk", "due_date": "2026-12-24"}`, then the response is `201` with a JSON object holding `id` (a UUID string), `title` `"Buy milk"`, `due_date` `"2026-12-24"` and `created_at` (a UTC timestamp in ISO 8601). (smoke)
- **AC-001.2** Given the service is running, when a client sends `POST /tasks` with `{"title": "Call Bob"}` (no `due_date`) or with `"due_date": null`, then the response is `201` and the returned task has `due_date` `null`.
- **AC-001.3** Given tasks were created in the order A, B, C, when a client sends `GET /tasks`, then the response is `200` with a JSON array of exactly those three task objects (same fields and values as returned on creation), oldest first; given no task exists, the response is `200` with `[]`. (smoke)
- **AC-001.4** Given the service is running, when a client sends `POST /tasks` whose `title` is missing, not a string, empty or only whitespace, or longer than 200 characters after trimming leading and trailing whitespace, then the response is `422` with a `detail` naming the `title` field, and `GET /tasks` lists no new task. (smoke)
- **AC-001.5** Given the service is running, when a client sends `POST /tasks` with a `due_date` that is not a calendar date in `YYYY-MM-DD` form (for example `"2026-02-30"`, `"24.12.2026"`, `"tomorrow"` or `"2026-12-24T10:00:00Z"`), then the response is `422` with a `detail` naming the `due_date` field, and `GET /tasks` lists no new task.
- **AC-001.6** Given a title with leading or trailing whitespace such as `"  Buy milk  "`, when the task is created, then the returned and listed `title` is `"Buy milk"`.
- **AC-001.7** Given 10,000 tasks exist, when a client sends a further valid `POST /tasks`, then the response is `409` with `detail` `"task limit reached"`, and `GET /tasks` still lists 10,000 tasks.
- **AC-001.8** Given tasks were created, when the service restarts, then `GET /tasks` returns `200` with `[]`.

## Non-goals

- Reading, updating, completing or deleting a single task.
- Durable storage; tasks surviving a restart or being shared between several replicas.
- Filtering, sorting options, search or pagination of the list.
- Fields other than title and due date (description, status, assignee, priority, time of day on the due date).
- Users, accounts and per-user task lists.
- Authentication and authorization: anyone who can reach the service may create and list tasks, in every environment; access control comes in a later spec.

## Assumptions

- **A1** Endpoints are `POST /tasks` to create and `GET /tasks` to list (other option: `/api/v1/tasks`; affects AC-001.1–AC-001.8).
- **A2** A task's `id` is a server-generated UUID string, so ids are never reused after a restart (other option: an increasing integer starting at 1; affects AC-001.1).
- **A3** The response carries `created_at` (UTC, ISO 8601) in addition to the requested fields (other option: only `id`, `title`, `due_date`; affects AC-001.1, AC-001.3).
- **A4** `due_date` is a calendar date `YYYY-MM-DD` without time or time zone; dates in the past are accepted (other option: a full timestamp, or rejecting past dates; affects AC-001.1, AC-001.5).
- **A5** A missing `due_date` and `"due_date": null` both mean "no due date" and come back as `null` (other option: omit the field from the response; affects AC-001.2).
- **A6** The title is trimmed and must be 1 to 200 characters after trimming; duplicate titles are allowed (other option: 500 characters, or keeping whitespace as sent; affects AC-001.4, AC-001.6).
- **A7** The list returns all tasks, oldest first, as a plain JSON array without pagination (other option: newest first, or ordered by due date; affects AC-001.3).
- **A8** Invalid input answers `422` with the framework's usual `detail` error body; unknown extra fields in the request body are ignored (other option: `400`, or rejecting unknown fields; affects AC-001.4, AC-001.5).
- **A9** At most 10,000 tasks are kept so memory stays bounded; a further create answers `409` `"task limit reached"` (other option: no limit, or evicting the oldest task; affects AC-001.7).
- **A10** Tasks live only in the memory of the running process: a restart or new deploy empties the list, and with more than one replica each would hold its own tasks (other option: none within this spec, durable storage is a later spec; affects AC-001.8).

## Open questions

- ~~May anyone who can reach the service create and list tasks, without authentication, in every environment it is deployed to? (suggested: yes for this spec, access control comes in a later spec; alternatives: require a shared API key from an environment variable, or no, keep the endpoints out of staging and prod until auth exists, which limits to [dev]; affects AC-001.1–AC-001.7)~~ Answered 2026-11-22: yes, no authentication for now; anyone who can reach the service may create and list tasks in every environment; authentication comes in a later spec (folded into the Non-goals).

<!-- Priority levels (spec 196) for the product-manager's PRIORITY line: P0 an outage, data loss, a security problem, or something that blocks all other work; P1 a normal bug or feature; the fallback when nothing signals urgency; P2 cosmetic, a convenience, or something with an easy workaround. A reason is "P<n>: <phrase>", one of: P0: outage, data loss, security problem, blocks all other work; P1: normal bug or feature; P2: cosmetic, convenience, easy workaround. -->

<!-- Priority levels (spec 196) for the product-manager's PRIORITY line: P0 an outage, data loss, a security problem, or something that blocks all other work; P1 a normal bug or feature; the fallback when nothing signals urgency; P2 cosmetic, a convenience, or something with an easy workaround. A reason is "P<n>: <phrase>", one of: P0: outage, data loss, security problem, blocks all other work; P1: normal bug or feature; P2: cosmetic, convenience, easy workaround. -->

## Changelog

- 2026-11-22 created
- 2026-11-22 priority P1 proposed: P1: normal bug or feature
- 2026-11-22 amended: open question on access answered (no authentication for now, every environment); added as a non-goal
- 2026-11-22 approved
- 2026-11-22 building
