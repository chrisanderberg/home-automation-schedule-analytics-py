# AGENTS.md

## Purpose
- This file is intentionally minimal.
- Add guidance only when needed.

## Assumptions
- Add implementation assumptions here when they come up.
- Include enough context for later review/validation.
- Using one shared Python package (`shared-logic/src/shared_logic`) for domain/storage logic consumed by both Flask and Dagster.
- Snapshot export uses SQLite backup API (`sqlite3.Connection.backup`) for consistency.
- Flask service runs both ports (`8080` and `8081`) in one process via two werkzeug servers on background threads.
- Testing DBs/snapshots are rooted at `test-data/` (or `TEST_DATA_DIR` override) to preserve isolation from `data/`.
- Default runtime clock config falls back to `UTC`, latitude `0`, longitude `0` when env vars are not set.
