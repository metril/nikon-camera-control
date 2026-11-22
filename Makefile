BIN := .venv/bin

.PHONY: lint test api api-check ci frontend-install frontend-lint frontend-test frontend-build docker-build release-check

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

frontend-install:
	cd frontend && bun install --frozen-lockfile

frontend-lint: frontend-install
	cd frontend && bun run lint && bun run format:check

frontend-test: frontend-install
	cd frontend && bun run test

frontend-build: frontend-install
	cd frontend && bun run build

docker-build:
	docker build -f docker/Dockerfile -t nikon-camera-control:dev .

release-check:
	scripts/release_check.sh $(TAG)

# Mirrors .github/workflows/ci.yml (lint, backend, frontend jobs). The docker job needs a
# daemon, so run `make docker-build` separately.
ci: lint api-check test frontend-lint frontend-test frontend-build
