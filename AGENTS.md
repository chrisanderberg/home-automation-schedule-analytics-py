# AGENTS.md

## Purpose
- This file is intentionally minimal.
- Add guidance only when needed.

## Assumptions
- Add implementation assumptions here when they come up.
- Include enough context for later review/validation.
- Using one shared Python package (`shared-logic/src/shared_logic`) for domain/storage logic consumed by both Flask and Dagster.
- Snapshot export uses SQLite backup API (`sqlite3.Connection.backup`) for consistency.
- Local-only runtime uses two Werkzeug dev servers on background threads for `8080` (main) and `8081` (testing).
- Production should use a real WSGI server (for example gunicorn), with `8080` and `8081` served by separate processes/instances behind a reverse proxy.
- Production deployment should include explicit handling for port-bind failures and coordinated SIGTERM shutdown behavior.
- Testing DBs/snapshots are rooted at `test-data/` (or `TEST_DATA_DIR` override) to preserve isolation from `data/`.
- Runtime clock config requires explicit `HAA_LATITUDE` and `HAA_LONGITUDE` env vars; service startup fails fast when either is missing.
