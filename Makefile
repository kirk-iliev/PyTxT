.PHONY: install dev test test-unit test-integration test-e2e dev-up dev-down lint clean

install:
	pip install -e ".[dev]"
	cd tests/e2e && npm install && npx playwright install chromium

dev:
	python -m pytxt

test: test-unit test-integration test-e2e

test-unit:
	pytest tests/unit -v

test-integration:
	pytest tests/integration -v

test-e2e:
	cd tests/e2e && npx playwright test --reporter=list

dev-up:
	python -m pytxt &
	@echo "PyTxT started in background; logs to stdout"

dev-down:
	pkill -f "python -m pytxt" || true

lint:
	ruff check pytxt tests

clean:
	rm -rf build dist *.egg-info .pytest_cache .ruff_cache .mypy_cache htmlcov
	find . -type d -name __pycache__ -exec rm -rf {} +
