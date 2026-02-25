PYTHON ?= python3
PYTHONPATH_BASE=$(CURDIR)/shared-logic/src:$(CURDIR)/aggregation/src:$(CURDIR)/reporting/src

.PHONY: all clean setup setup-test setup-aggregation setup-reporting setup-dev check-shared-test-deps check-aggregation-test-deps check-reporting-test-deps test run-shared-tests run-aggregation-tests run-reporting-tests test-shared test-aggregation test-reporting

all: setup

setup: setup-test setup-aggregation setup-reporting

setup-test:
	$(PYTHON) -m pip install -e '.[test]'

setup-aggregation:
	$(PYTHON) -m pip install -e '.[aggregation]'

setup-reporting:
	$(PYTHON) -m pip install -e '.[reporting]'

setup-dev:
	$(PYTHON) -m pip install -e '.[dev]'

check-shared-test-deps:
	@PYTHONPATH=$${PYTHONPATH:+$$PYTHONPATH:}$(PYTHONPATH_BASE) $(PYTHON) -c "from shared_logic.contracts import Config" >/dev/null 2>&1 || (echo "Missing shared test dependency or import path. Run 'make setup' first."; exit 1)

check-aggregation-test-deps:
	@PYTHONPATH=$${PYTHONPATH:+$$PYTHONPATH:}$(PYTHONPATH_BASE) $(PYTHON) -c "import flask; from aggregation_service.jsonio import decode_strict_json" >/dev/null 2>&1 || (echo "Missing aggregation test dependency or import path. Run 'make setup' first."; exit 1)

check-reporting-test-deps:
	@PYTHONPATH=$${PYTHONPATH:+$$PYTHONPATH:}$(PYTHONPATH_BASE) $(PYTHON) -c "import dagster; from reporting_service.http_json import decode_json_body" >/dev/null 2>&1 || (echo "Missing reporting test dependency or import path. Run 'make setup' first."; exit 1)

test: check-shared-test-deps check-aggregation-test-deps check-reporting-test-deps run-shared-tests run-aggregation-tests run-reporting-tests

run-shared-tests:
	PYTHONPATH=$${PYTHONPATH:+$$PYTHONPATH:}$(PYTHONPATH_BASE) $(PYTHON) -m unittest discover -s $(CURDIR)/shared-logic/tests -p "test_*.py"

run-aggregation-tests:
	PYTHONPATH=$${PYTHONPATH:+$$PYTHONPATH:}$(PYTHONPATH_BASE) $(PYTHON) -m unittest discover -s $(CURDIR)/aggregation/tests -p "test_*.py"

run-reporting-tests:
	PYTHONPATH=$${PYTHONPATH:+$$PYTHONPATH:}$(PYTHONPATH_BASE) $(PYTHON) -m unittest discover -s $(CURDIR)/reporting/tests -p "test_*.py"

clean:
	rm -rf .pytest_cache .ruff_cache .tmp_dagster_home_* .coverage
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

test-shared: check-shared-test-deps
	PYTHONPATH=$${PYTHONPATH:+$$PYTHONPATH:}$(PYTHONPATH_BASE) $(PYTHON) -m unittest discover -s $(CURDIR)/shared-logic/tests -p "test_*.py"

test-aggregation: check-aggregation-test-deps
	PYTHONPATH=$${PYTHONPATH:+$$PYTHONPATH:}$(PYTHONPATH_BASE) $(PYTHON) -m unittest discover -s $(CURDIR)/aggregation/tests -p "test_*.py"

test-reporting: check-reporting-test-deps
	PYTHONPATH=$${PYTHONPATH:+$$PYTHONPATH:}$(PYTHONPATH_BASE) $(PYTHON) -m unittest discover -s $(CURDIR)/reporting/tests -p "test_*.py"
