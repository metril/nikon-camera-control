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
	cd frontend && bun run gen:api

# Client drift: regenerates into a temp dir beside the real one and diffs (never overwrites).
api-check:
	$(BIN)/python -m scripts.gen_api --check
	cd frontend && bun run gen:api:check

ci: lint api-check test
