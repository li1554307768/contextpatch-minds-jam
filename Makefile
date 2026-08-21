.PHONY: run test lint typecheck security audit build secret-scan license-scan verify verify-offline

run:
	uv run uvicorn app.main:app --host 127.0.0.1 --port 8010

test:
	uv run pytest

lint:
	uv run ruff check .

typecheck:
	uv run mypy app

security:
	uv run bandit -c pyproject.toml -r app

audit:
	uv run pip-audit --skip-editable

build:
	uv build

secret-scan:
	uv run python scripts/security_scan.py

license-scan:
	uv run python scripts/check_licenses.py

verify: test lint typecheck security audit build secret-scan license-scan

verify-offline: verify
