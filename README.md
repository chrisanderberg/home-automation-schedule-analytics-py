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
