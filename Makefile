.PHONY: install install-all lock lint format format-check typecheck test check pre-commit serve dev clean frontend-lint frontend-format frontend-format-check

install: ## Sync the dev environment (server + workflows + dev extras)
	uv sync --extra server --extra workflows --extra dev

install-all: ## Sync every optional extra
	uv sync --all-extras

lock: ## Re-resolve dependencies into uv.lock
	uv lock

lint: ## Ruff lint (auto-fix)
	uv run ruff check --fix src/

format: ## Ruff format
	uv run ruff format src/

format-check: ## Ruff format, check only (what CI runs)
	uv run ruff format --check src/

typecheck: ## Mypy
	uv run mypy src/civex

test: ## Run the test suite with coverage
	uv run pytest tests/ -q --cov=civex --cov-report=term-missing

check: format-check ## Everything CI checks, in one shot
	uv run ruff check src/
	$(MAKE) typecheck
	$(MAKE) test

pre-commit: ## Run all pre-commit hooks against the whole tree
	uv run pre-commit run --all-files

serve: ## Start the API with auto-reload (requires the server extra)
	uv run civex serve --reload

dev: ## Frontend dev server (run alongside `make serve`)
	cd frontend && npm run dev

frontend-lint: ## ESLint (auto-fix)
	cd frontend && npm run lint:fix

frontend-format: ## Prettier
	cd frontend && npm run format

frontend-format-check: ## Prettier, check only
	cd frontend && npm run format:check

clean: ## Remove caches and the synced environment
	rm -rf .venv .ruff_cache .mypy_cache .pytest_cache .coverage htmlcov
