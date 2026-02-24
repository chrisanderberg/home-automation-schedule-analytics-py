# DECISIONS.md

## Architecture Decisions
- Shared Python package path: `shared-logic/src/shared_logic`.
Rationale: keeps aggregation and reporting on one domain/storage implementation to avoid drift.

- Snapshot export uses `sqlite3.Connection.backup`.
Rationale: provides a consistent SQLite snapshot artifact without copying live DB files directly.

- Local runtime serves two ports (`8080` main, `8081` testing) via two Werkzeug dev servers.
Rationale: convenient single-process local development topology; not a production deployment model.

- Testing data root is `test-data/` with optional `TEST_DATA_DIR` override.
Rationale: keeps testing DB/snapshots isolated from production `data/` paths.

- Runtime clock configuration requires explicit `HAA_LATITUDE` and `HAA_LONGITUDE`.
Rationale: avoids silent location defaults and forces explicit, auditable clock semantics.
