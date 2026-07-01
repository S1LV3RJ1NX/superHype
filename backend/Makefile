# Developer commands for the super-hype backend. Run from backend/.
# Usage: make <target>   (run `make help` to list everything)

.DEFAULT_GOAL := help
.PHONY: help install server worker flush reset migrate seed test lint format

help: ## List available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "} {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install: ## Sync dependencies with uv
	uv sync

server: ## Run the API (uvicorn, autoreload)
	uv run uvicorn app.main:app --reload

worker: ## Run the ARQ worker
	uv run arq app.workers.arq_app.WorkerSettings

flush: ## Clear the ARQ worker queue in Redis
	uv run python -m scripts.flush_queue

reset: ## Reset a campaign to review to launch again (CAMPAIGN=<id> [REGEN=1]; omit to list)
	uv run python -m scripts.reset_campaign $(CAMPAIGN) $(if $(REGEN),--regenerate,)

migrate: ## Apply database migrations
	uv run alembic upgrade head

seed: ## Seed bootstrap admins and default teams
	uv run python -m app.seed

test: ## Run the test suite
	uv run pytest

lint: ## Lint (ruff) and type-check (mypy)
	uv run ruff check . && uv run mypy app

format: ## Format with ruff
	uv run ruff format .
