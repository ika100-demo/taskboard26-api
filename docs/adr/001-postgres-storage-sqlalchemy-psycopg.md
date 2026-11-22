# ADR-001: Postgres storage sqlalchemy psycopg

**Status:** Proposed (2026-11-22)

## Context

<!-- why a decision is needed: the forces and constraints -->

## Decision

Task storage uses SQLAlchemy 2 Core over psycopg 3 with pre-ping pooling; the API creates its schema idempotently under an advisory lock (no migration tool yet)

## Consequences

<!-- what becomes easier or harder, what a later change must keep -->
