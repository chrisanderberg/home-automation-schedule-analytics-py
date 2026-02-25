# Home Automation Schedule Analytics (Python)

Monorepo layout:
- `aggregation/`: Flask aggregation APIs (`:8080` main, `:8081` testing)
- `reporting/`: Dagster reporting assets/jobs/sensors
- `shared-logic/`: shared domain/storage logic used by both services
- `data/`: sanitized local development fixtures only; production snapshots belong in internal object storage/artifact store, not git

## Run aggregation service

```bash
make setup-aggregation
# Replace HAA_LATITUDE/HAA_LONGITUDE with your own coordinates (decimal degrees).
export HAA_LATITUDE="37.7749"
export HAA_LONGITUDE="-122.4194"
PYTHONPATH=shared-logic/src:aggregation/src python -m aggregation_service.main
```

## Run reporting service (Dagster)

```bash
make setup-reporting
PYTHONPATH=shared-logic/src:reporting/src dagster dev -m reporting_service.definitions
```

## Deploy with Docker Compose

Copy `.env.example` to `.env`, fill in `DAGSTER_PG_PASSWORD` (and adjust `HAA_LATITUDE`/`HAA_LONGITUDE` if desired), then start the stack:

```bash
cp .env.example .env
# Edit .env and set DAGSTER_PG_PASSWORD (rotate any default before deploying)
docker compose --env-file .env up --build
```

- **Aggregation**: `http://localhost:8080`
- **Reporting (Dagster UI)**: `http://localhost:3000`

The reporting service runs **dagster-webserver** (UI) and **dagster-daemon** (schedules/sensors) via supervisord in the Docker image. Both require **DAGSTER_HOME** (`/app/.dagster`) for run history and SQLite state. The `app_dagster_home` volume is mounted at `/app/.dagster` so this state persists across container restarts. Without this mount, run history and schedule/sensor state would be ephemeral.

Do not commit database secrets to git. Use a local `.env` file (or deployment secrets/CI) for `DAGSTER_PG_PASSWORD`. Update `.gitignore` to include `.env` and `env/*.local`, and verify `.env` is not tracked (e.g. run `git status` or `git rm --cached .env` if already added) so secrets are never committed. Rotate any default/shared password before deploying.

### Using an external Postgres

When `DAGSTER_PG_HOST` is set to an external Postgres host (e.g. a managed DB), the local `dagster_postgres` service in `docker-compose.yml` still starts by default. To disable it, use the override pattern:

1. Copy the example override: `cp docker-compose.override-external-db.yml.example docker-compose.override.yml`
2. Set `DAGSTER_PG_HOST`, `DAGSTER_PG_PORT`, `DAGSTER_PG_DB`, `DAGSTER_PG_USERNAME`, and `DAGSTER_PG_PASSWORD` in `.env` for your external instance.
3. Run `docker compose up` as usual.

The override puts `dagster_postgres` behind a Compose profile (`local-db`) and removes it from `reporting`'s `depends_on`, so the local service is not started when using an external DB. To run with the local DB again, remove `docker-compose.override.yml` or run `docker compose --profile local-db up`.

## Run tests

```bash
make setup
make test
```

Dependency setup options:

```bash
make setup              # umbrella target: setup-test + setup-aggregation + setup-reporting
make setup-test         # test dependencies only
make setup-aggregation  # Flask aggregation runtime only
make setup-reporting    # Dagster reporting runtime only
make setup-dev          # full local dev dependencies
```

Useful scoped targets:

```bash
make test-shared
make test-aggregation
make test-reporting
```

If `make` is unavailable, run directly:

```bash
PYTHONPATH=shared-logic/src python -m unittest discover -s shared-logic/tests -p "test_*.py"
PYTHONPATH=shared-logic/src:aggregation/src python -m unittest discover -s aggregation/tests -p "test_*.py"
PYTHONPATH=shared-logic/src:reporting/src python -m unittest discover -s reporting/tests -p "test_*.py"
```
