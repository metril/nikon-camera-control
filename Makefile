BIN := .venv/bin

.PHONY: lint test ci

lint:
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .
	$(BIN)/mypy backend

test:
	$(BIN)/pytest

ci: lint test
