PYTHONPATH_BASE=shared-logic/src:aggregation/src:reporting/src

.PHONY: setup setup-test setup-aggregation setup-reporting setup-dev check-test-deps test test-shared test-aggregation test-reporting

setup: setup-test

setup-test:
	python -m pip install -e '.[test]'

setup-aggregation:
	python -m pip install -e '.[aggregation]'

setup-reporting:
	python -m pip install -e '.[reporting]'

setup-dev:
	python -m pip install -e '.[dev]'

check-test-deps:
	@python -c "import flask" >/dev/null 2>&1 || (echo "Missing dependency: Flask. Run 'make setup' first."; exit 1)

test: check-test-deps
	PYTHONPATH=$(PYTHONPATH_BASE) python -m unittest discover -s shared-logic/tests -p "test_*.py"
	PYTHONPATH=$(PYTHONPATH_BASE) python -m unittest discover -s aggregation/tests -p "test_*.py"
	PYTHONPATH=$(PYTHONPATH_BASE) python -m unittest discover -s reporting/tests -p "test_*.py"

test-shared: check-test-deps
	PYTHONPATH=$(PYTHONPATH_BASE) python -m unittest discover -s shared-logic/tests -p "test_*.py"

test-aggregation: check-test-deps
	PYTHONPATH=$(PYTHONPATH_BASE) python -m unittest discover -s aggregation/tests -p "test_*.py"

test-reporting: check-test-deps
	PYTHONPATH=$(PYTHONPATH_BASE) python -m unittest discover -s reporting/tests -p "test_*.py"
