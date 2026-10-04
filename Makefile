# Cairn developer commands. Work on the host and inside the Dev Container.
# Inside the Dev Container (CAIRN_IN_DEVCONTAINER=1) Python commands run directly
# against the compose services; on the host they run inside the compose containers
# or against localhost ports.

SHELL := /bin/bash
.DEFAULT_GOAL := help

COMPOSE ?= docker compose
UV ?= uv
IN_DEVCONTAINER := $(CAIRN_IN_DEVCONTAINER)

POSTGRES_PORT ?= 5432
NEO4J_BOLT_PORT ?= 7687
TEMPORAL_PORT ?= 7233
MINIO_API_PORT ?= 9000
CAIRN_API_PORT ?= 8000

ifeq ($(IN_DEVCONTAINER),1)
INTEGRATION_ENV := CAIRN_INTEGRATION=1
API_URL ?= http://api:8000
else
# From the host, reach the compose services through their published ports.
INTEGRATION_ENV := CAIRN_INTEGRATION=1 \
	CAIRN_DATABASE_URL=postgresql+asyncpg://cairn:cairn_local_dev_only@localhost:$(POSTGRES_PORT)/cairn \
	CAIRN_CONTEXT_PROVIDER=graphiti CAIRN_NEO4J_URI=bolt://localhost:$(NEO4J_BOLT_PORT) \
	CAIRN_EVIDENCE_STORE=minio CAIRN_MINIO_ENDPOINT=localhost:$(MINIO_API_PORT) \
	CAIRN_WORKFLOW_DISPATCHER=temporal CAIRN_TEMPORAL_ADDRESS=localhost:$(TEMPORAL_PORT)
API_URL ?= http://localhost:$(CAIRN_API_PORT)
endif

.PHONY: help setup up down stop restart logs ps build test unit contract integration check \
	lint format typecheck migrate migration seed demo api worker shell clean \
	web-install web web-check

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup: ## Install Python dependencies (uv) and git hooks
	$(UV) sync
	-$(UV) run pre-commit install

# ------------------------------------------------------------------ compose
up: ## Start the full stack (postgres, neo4j, temporal, temporal-ui, minio, api, worker, web)
	$(COMPOSE) up -d --build --wait

down: ## Stop the stack (inside the Dev Container: stops api + worker only)
ifeq ($(IN_DEVCONTAINER),1)
	@echo "Inside the Dev Container: stopping api/worker/web only (infra hosts this container)."
	$(COMPOSE) stop api worker web
else
	$(COMPOSE) down
endif

stop: ## Stop containers without removing them
	$(COMPOSE) stop

restart: ## Restart api + worker
	$(COMPOSE) restart api worker

logs: ## Follow api + worker + web logs
	$(COMPOSE) logs -f api worker web

ps: ## Show service status
	$(COMPOSE) ps

build: ## Build the application image
	$(COMPOSE) build api

# ------------------------------------------------------------------ quality
test: unit contract ## Unit + contract tests (no external services, no API keys)

unit: ## Unit tests
	$(UV) run pytest tests/unit -q

contract: ## Contract tests (provider/pack contracts; Neo4j params need `make integration`)
	$(UV) run pytest tests/contract -q

integration: ## Integration tests against the running compose services
	$(INTEGRATION_ENV) $(UV) run pytest tests/integration tests/contract -q -rs

check: lint typecheck test ## Lint, type check and test (what CI runs)

lint: ## Ruff lint + format check
	$(UV) run ruff check .
	$(UV) run ruff format --check .

format: ## Auto-format and fix lint
	$(UV) run ruff format .
	$(UV) run ruff check . --fix

typecheck: ## mypy (strict) over the cairn package
	$(UV) run mypy

# ------------------------------------------------------------------ database
migrate: ## Apply Alembic migrations and bootstrap derived-store indices
ifeq ($(IN_DEVCONTAINER),1)
	$(UV) run alembic upgrade head
	$(UV) run python -m cairn.context.bootstrap
else
	$(COMPOSE) run --rm migrate
endif

migration: ## Create a migration: make migration m="describe change"
	@test -n "$(m)" || (echo 'usage: make migration m="describe change"'; exit 1)
ifeq ($(IN_DEVCONTAINER),1)
	$(UV) run alembic revision --autogenerate -m "$(m)"
else
	CAIRN_DATABASE_URL=postgresql+asyncpg://cairn:cairn_local_dev_only@localhost:$(POSTGRES_PORT)/cairn \
		$(UV) run alembic revision --autogenerate -m "$(m)"
endif

seed: ## Seed SYNTHETIC demo data (idempotent; RESET=1 to recreate)
ifeq ($(IN_DEVCONTAINER),1)
	$(UV) run python scripts/seed_demo.py $(if $(RESET),--reset,)
else
	$(COMPOSE) exec -T api python scripts/seed_demo.py $(if $(RESET),--reset,)
endif

demo: ## Run the acceptance demo flow against the running API
	$(UV) run python scripts/demo_flow.py --api $(API_URL)

# ------------------------------------------------------------------ run locally
api: ## Run the API with reload (Dev Container)
	$(UV) run uvicorn cairn.api.main:app --host 0.0.0.0 --port 8000 --reload

worker: ## Run the Temporal worker (Dev Container)
	$(UV) run python -m cairn.workflows.worker

# ------------------------------------------------------------------ website (apps/web)
web-install: ## Install website dependencies (npm ci)
	cd apps/web && npm ci

web: ## Run the website with hot reload on :5173 (proxies /v1 to CAIRN_API_URL, default :8000)
	cd apps/web && npm run dev

web-check: ## Website: TypeScript, unit tests and production build
	cd apps/web && npm run typecheck && npm test && npm run build

shell: ## Shell in the api container
	$(COMPOSE) exec api bash

clean: ## Remove caches; `make clean VOLUMES=1` also deletes compose volumes (data loss!)
	rm -rf .pytest_cache .mypy_cache .ruff_cache .data
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
ifeq ($(VOLUMES),1)
	$(COMPOSE) down -v
endif
