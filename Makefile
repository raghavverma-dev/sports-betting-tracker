# BetEdge — convenience targets. Run `make help` for the list.

.DEFAULT_GOAL := help
.PHONY: help dev down logs shell migrate seed backtest test lint fmt \
        frontend-dev frontend-build clean \
        venv dev-native migrate-native seed-native backtest-native test-native

# Path to the venv's python & scripts; override if your venv lives elsewhere.
VENV := backend/.venv
PY   := $(VENV)/bin/python
# SQLite lives at backend/betedge.db by default — no Postgres install required.
SQLITE_URL := sqlite:///./betedge.db

help: ## Show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ================ Docker path ================

dev: ## Start Postgres + backend in Docker (requires Docker Desktop)
	docker compose up --build

down: ## Stop Docker containers (keeps the DB volume)
	docker compose down

logs: ## Tail backend container logs
	docker compose logs -f backend

shell: ## Open a bash shell in the backend container
	docker compose exec backend bash

migrate: ## Run pending Alembic migrations in Docker
	docker compose exec backend alembic upgrade head

seed: ## Seed synthetic NBA games via Docker
	docker compose exec backend betedge seed --num-games 400

backtest: ## Run a market-baseline backtest via Docker
	docker compose exec backend betedge backtest run --strategy market-baseline --sport NBA

test: ## Run pytest inside the backend container
	docker compose exec backend pytest -q

lint: ## Ruff check + mypy inside Docker
	docker compose exec backend ruff check src tests
	docker compose exec backend mypy src

fmt: ## Format Python inside Docker
	docker compose exec backend ruff format src tests

clean: ## Remove the Postgres volume (wipes Dockerized data!)
	docker compose down -v

# ================ No-Docker (native venv + SQLite) path ================

venv: ## Create the Python 3.12 venv at backend/.venv and install deps
	cd backend && python3.12 -m venv .venv \
	    && .venv/bin/pip install --upgrade pip \
	    && .venv/bin/pip install -e ".[dev]"

dev-native: ## Run backend natively with SQLite (no Docker)
	@cd backend && DATABASE_URL=$(SQLITE_URL) .venv/bin/alembic upgrade head
	@cd backend && DATABASE_URL=$(SQLITE_URL) \
	    .venv/bin/uvicorn betedge.main:app \
	    --host 0.0.0.0 --port 8000 --reload --reload-dir src

migrate-native: ## Run Alembic against the local SQLite DB
	@cd backend && DATABASE_URL=$(SQLITE_URL) .venv/bin/alembic upgrade head

seed-native: ## Seed the local SQLite DB
	@cd backend && DATABASE_URL=$(SQLITE_URL) .venv/bin/betedge seed --num-games 400

backtest-native: ## Run a market-baseline backtest against the local SQLite DB
	@cd backend && DATABASE_URL=$(SQLITE_URL) \
	    .venv/bin/betedge backtest run --strategy market-baseline --sport NBA

test-native: ## Run pytest in the local venv (no Docker)
	cd backend && .venv/bin/pytest -q

# ================ Frontend ================

frontend-dev: ## Run the Vite dev server on the host
	npm run dev

frontend-build: ## Build the static frontend bundle
	npm run build
