# `make check` is the one command to run before committing.
PY := .venv/bin/python
.PHONY: check test web lint demo
check:
	@scripts/check.sh
test:
	$(PY) -m pytest -q
web:
	cd console/web && npm run build
lint:
	@scripts/check.sh --lint-only
demo:
	$(PY) scripts/make_synthetic_data.py && $(PY) run_console.py --demo
