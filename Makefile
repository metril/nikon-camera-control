BIN := .venv/bin

.PHONY: lint test api api-check ci

lint:
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .
	$(BIN)/mypy backend scripts

test:
	$(BIN)/pytest

api:
	$(BIN)/python -m scripts.gen_api

api-check:
	$(BIN)/python -m scripts.gen_api --check

ci: lint api-check test
