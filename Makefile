.DEFAULT_GOAL := help

MISE := mise exec --
UV := $(MISE) uv

.PHONY: help setup sync lock test test-unit test-cov smoke-openai smoke-azure lint format format-check check run migrate \
	migration \
	docker-build docker-up docker-down docker-logs docker-test

help: ## Show available project commands
	@awk 'BEGIN {FS = ":.*## "; printf "Usage: make <target>\n\nTargets:\n"} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup: ## Install mise tools and locked Python dependencies
	mise install
	$(UV) sync --locked

sync: ## Synchronize the virtual environment from uv.lock
	$(UV) sync --locked

lock: ## Resolve dependencies and update uv.lock
	$(UV) lock

test: ## Run the complete test suite
	$(UV) run pytest

test-unit: ## Run isolated unit tests
	$(UV) run pytest -m unit

test-cov: ## Run tests with the configured coverage threshold
	$(UV) run pytest --cov --cov-report=term-missing

smoke-openai: ## Run the explicitly enabled, billed OpenAI integration smoke test
	ACC_RUN_OPENAI_SMOKE=1 $(UV) run pytest -m smoke tests/smoke/test_real_openai_generation.py

smoke-azure: ## Run the explicitly enabled, billed Azure Speech smoke test
	ACC_RUN_AZURE_SPEECH_SMOKE=1 $(UV) run pytest -m smoke tests/smoke/test_real_azure_speech.py

lint: ## Run Ruff lint checks
	$(UV) run ruff check .

format: ## Format Python sources and tests
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

format-check: ## Verify Python formatting without changing files
	$(UV) run ruff format --check .

check: lint format-check test-cov ## Run all local quality gates

run: ## Start the local development server
	$(UV) run uvicorn anki_custom_card.app:app --host 127.0.0.1 --port 8000 --reload

migrate: ## Upgrade the configured database to the latest schema
	$(UV) run alembic upgrade head

migration: ## Generate an Alembic revision; usage: make migration MESSAGE="description"
	@test -n "$(MESSAGE)" || (echo 'MESSAGE is required' && exit 2)
	$(UV) run alembic revision --autogenerate -m "$(MESSAGE)"

docker-build: ## Build the production container image
	docker compose build app

docker-up: ## Start the application container
	docker compose up -d app

docker-down: ## Stop and remove Compose resources
	docker compose down

docker-logs: ## Follow application container logs
	docker compose logs -f app

docker-test: ## Run the test suite in an isolated container
	docker compose --profile test run --build --rm test
