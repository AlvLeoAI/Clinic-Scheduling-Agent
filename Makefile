# Developer shortcuts. Every database target uses the THROWAWAY test database that
# `make db-up` starts (tmpfs, 127.0.0.1:15433, lost on `make db-down`). compose.yaml is a
# separate, persistent development database on 127.0.0.1:15432 and is not used here.
# The stack-* targets run compose.demo.yaml: its own disposable database, API and UI.

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

PYTHON ?= python3.12
VENV := .venv
BIN := $(VENV)/bin
PG_IMAGE ?= postgres:16-alpine@sha256:4e6e670bb069649261c9c18031f0aded7bb249a5b6664ddec29c013a89310d50
PG_CONTAINER ?= clinic-scheduling-test-db
PG_PORT ?= 15433
PG_PASSWORD ?= localdemo
DB_URL := postgresql+psycopg://clinic_demo:$(PG_PASSWORD)@127.0.0.1:$(PG_PORT)/clinic_scheduling_test
# Explicit values override anything in a local .env, so targets never reach a paid provider.
RUN := env DATABASE_URL=$(DB_URL) TEST_DATABASE_URL=$(DB_URL) AGENT_PROVIDER=disabled \
	ENABLE_LIVE_OPENAI=false OPENAI_API_KEY= OPENAI_MODEL= \
	CLINIC_BOOKING_EVIDENCE_FILE=M6_booking_regression_cases.json \
	CLINIC_AGENT_EVIDENCE_FILE=M6_m4_regression_cases.json
LINT_PATHS := app cli scripts alembic tests evaluations ui
STACK := docker compose -f compose.demo.yaml

.PHONY: help install db-up db-down test demo lint ci serve purge-chat stack-up stack-smoke stack-down

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

install: ## Create .venv and install pinned dependencies
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install -q --require-hashes -r requirements-foundation.lock

db-up: ## Start the throwaway test database (tmpfs, port 15433) and wait until ready
	@if [ -n "$$(docker ps -q -f name=^$(PG_CONTAINER)$$)" ]; then \
		echo "$(PG_CONTAINER) is already running on 127.0.0.1:$(PG_PORT)"; \
	else \
		docker run -d --rm --name $(PG_CONTAINER) -p 127.0.0.1:$(PG_PORT):5432 \
			--tmpfs /var/lib/postgresql/data \
			-e POSTGRES_USER=clinic_demo -e POSTGRES_PASSWORD=$(PG_PASSWORD) \
			-e POSTGRES_DB=clinic_scheduling_test $(PG_IMAGE) >/dev/null; \
	fi
	@for attempt in $$(seq 30); do \
		if docker exec $(PG_CONTAINER) pg_isready -q -h 127.0.0.1 -U clinic_demo -d clinic_scheduling_test; then \
			echo "Throwaway test database ready on 127.0.0.1:$(PG_PORT)"; exit 0; \
		fi; \
		sleep 1; \
	done; \
	echo "PostgreSQL did not become ready within 30 s; see: docker logs $(PG_CONTAINER)" >&2; exit 1

db-down: ## Stop and remove the throwaway test database (its data is discarded)
	@if [ -n "$$(docker ps -q -f name=^$(PG_CONTAINER)$$)" ]; then \
		docker stop $(PG_CONTAINER) >/dev/null && echo "Stopped $(PG_CONTAINER)"; \
	else \
		echo "$(PG_CONTAINER) is not running"; \
	fi

test: ## Full test suite with real HTTP blocked
	$(RUN) $(BIN)/pytest -q -p tests.r2a_offline_guard

demo: ## Scripted CLI demo: catalog, availability, proposal, lost-response recovery
	$(RUN) $(BIN)/python -m cli --synthetic-only --scripted

lint: ## Ruff lint and format check
	$(BIN)/ruff check $(LINT_PATHS)
	$(BIN)/ruff format --check $(LINT_PATHS)

ci: lint ## Every CI step, in CI order
	$(RUN) $(BIN)/python -m scripts.check_synthetic
	$(RUN) $(BIN)/alembic upgrade head
	$(RUN) $(BIN)/alembic check
	$(RUN) $(BIN)/pytest -q -p tests.r2a_offline_guard
	$(RUN) $(BIN)/python -m evaluations.runner --evaluation-contract 1.2 --output-dir test-results/evals
	$(RUN) $(BIN)/python scripts/demo_concurrency.py --synthetic-only --evidence test-results/concurrency.json
	$(RUN) $(BIN)/python -m cli --synthetic-only --scripted --evidence test-results/cli.json
	$(RUN) $(BIN)/python -m scripts.check_docs

serve: ## API on 127.0.0.1:8000 with the demo provider, using the THROWAWAY test database
	@echo "serve uses the throwaway test database from 'make db-up' (127.0.0.1:$(PG_PORT));"
	@echo "data is lost on 'make db-down'. The persistent compose database (15432) is not used."
	$(RUN) $(BIN)/alembic upgrade head
	$(RUN) $(BIN)/python -m scripts.seed
	$(RUN) AGENT_PROVIDER=demo $(BIN)/uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log

purge-chat: ## Dry run of the chat retention purge against the throwaway database
	$(RUN) $(BIN)/python -m scripts.purge_chat

stack-up: ## Build and start db, migrate+seed, API (127.0.0.1:18000) and UI (127.0.0.1:8501)
	$(STACK) up -d --build --wait
	@echo "UI: http://127.0.0.1:8501   API: http://127.0.0.1:18000/docs   (demo provider)"

stack-smoke: ## Smoke-test the running stack: health, catalog turn, UI health, one booking
	python3 scripts/smoke_stack.py
	python3 scripts/smoke_deploy.py --api http://127.0.0.1:18000

stack-down: ## Stop the stack and discard its database
	$(STACK) down --volumes --remove-orphans
