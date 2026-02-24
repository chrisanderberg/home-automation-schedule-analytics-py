PYTHON ?= python3
PYTHONPATH_BASE=$(CURDIR)/shared-logic/src:$(CURDIR)/aggregation/src:$(CURDIR)/reporting/src

.PHONY: setup setup-test setup-aggregation setup-reporting setup-dev check-test-deps test test-shared test-aggregation test-reporting

setup: setup-test setup-aggregation setup-reporting

setup-test:
	$(PYTHON) -m pip install -e '.[test]'

setup-aggregation:
	$(PYTHON) -m pip install -e '.[aggregation]'

setup-reporting:
	$(PYTHON) -m pip install -e '.[reporting]'

setup-dev:
	$(PYTHON) -m pip install -e '.[dev]'

check-test-deps:
	@PYTHONPATH=$${PYTHONPATH:+$$PYTHONPATH:}$(PYTHONPATH_BASE) $(PYTHON) -c "import flask, dagster; from aggregation_service.jsonio import decode_strict_json; from reporting_service.http_json import decode_json_body" >/dev/null 2>&1 || (echo "Missing dependency or import path. Run 'make setup' first."; exit 1)

test: check-test-deps
	@set +e; \
	shared=0; aggregation=0; reporting=0; \
	PYTHONPATH=$${PYTHONPATH:+$$PYTHONPATH:}$(PYTHONPATH_BASE) $(PYTHON) -m unittest discover -s $(CURDIR)/shared-logic/tests -p "test_*.py" || shared=$$?; \
	PYTHONPATH=$${PYTHONPATH:+$$PYTHONPATH:}$(PYTHONPATH_BASE) $(PYTHON) -m unittest discover -s $(CURDIR)/aggregation/tests -p "test_*.py" || aggregation=$$?; \
	PYTHONPATH=$${PYTHONPATH:+$$PYTHONPATH:}$(PYTHONPATH_BASE) $(PYTHON) -m unittest discover -s $(CURDIR)/reporting/tests -p "test_*.py" || reporting=$$?; \
	if [ $$shared -ne 0 ] || [ $$aggregation -ne 0 ] || [ $$reporting -ne 0 ]; then \
		echo "Test summary: shared=$$shared aggregation=$$aggregation reporting=$$reporting"; \
		exit 1; \
	fi; \
	echo "Test summary: all suites passed"

test-shared: check-test-deps
	PYTHONPATH=$${PYTHONPATH:+$$PYTHONPATH:}$(PYTHONPATH_BASE) $(PYTHON) -m unittest discover -s $(CURDIR)/shared-logic/tests -p "test_*.py"

test-aggregation: check-test-deps
	PYTHONPATH=$${PYTHONPATH:+$$PYTHONPATH:}$(PYTHONPATH_BASE) $(PYTHON) -m unittest discover -s $(CURDIR)/aggregation/tests -p "test_*.py"

test-reporting: check-test-deps
	PYTHONPATH=$${PYTHONPATH:+$$PYTHONPATH:}$(PYTHONPATH_BASE) $(PYTHON) -m unittest discover -s $(CURDIR)/reporting/tests -p "test_*.py"
