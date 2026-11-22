# Architecture decision records

| ADR | Decision |
|---|---|
| [001](001-postgres-storage-sqlalchemy-psycopg.md) | Task storage uses SQLAlchemy 2 Core over psycopg 3 with pre-ping pooling; the API creates its schema idempotently under an advisory lock (no migration tool yet) |
| [002](002-postgres-integration-tests-testcontainers.md) | Postgres-backed tests run against a testcontainers postgres:17-alpine, or TEST_DATABASE_URL when set |
