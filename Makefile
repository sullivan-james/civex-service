.PHONY: install install-all lock lint format format-check typecheck test secrets audit migrations-check check pre-commit serve dev docs docs-build clean frontend-install frontend-lint frontend-lint-check frontend-format frontend-format-check frontend-build

install: ## Sync the dev environment (server + workflows + dev + docs extras)
	uv sync --extra server --extra workflows --extra dev --extra docs

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

secrets: ## Scan the repo (working tree + history) for leaked secrets
	@command -v gitleaks >/dev/null 2>&1 || { echo "gitleaks not found — install via 'brew install gitleaks' or https://github.com/gitleaks/gitleaks#installing"; exit 1; }
	gitleaks git --redact -v

audit: ## Scan Python + frontend dependencies for known vulnerabilities
	uv run pip-audit
	cd frontend && npm audit --audit-level=high

migrations-check: ## Check for Alembic migration drift (what CI runs)
	$(eval DBFILE := $(shell mktemp -u --suffix=.db))
	uv run alembic -x db_url="sqlite:///$(DBFILE)" upgrade head
	uv run alembic -x db_url="sqlite:///$(DBFILE)" check

# format-check/ruff/typecheck/test/secrets/audit/migrations-check mirror
# ci.yml's lint/test/audit/migrations jobs; frontend-lint-check/
# frontend-format-check/frontend-build mirror frontend-ci.yml's lint/build
# jobs; docs-build mirrors docs.yml's build job. Keep this list in lockstep
# with all three workflow files — this target's whole point is that a green
# `make check` locally means CI will be green too, so agent-driven commits
# stop landing PRs that pass this and then fail the real pipeline. Requires
# frontend deps installed (frontend-install or npm ci) in addition to
# `make install`.
check: format-check ## Everything CI checks, in one shot
	uv run ruff check src/
	$(MAKE) typecheck
	$(MAKE) test
	$(MAKE) secrets
	$(MAKE) audit
	$(MAKE) migrations-check
	$(MAKE) frontend-lint-check
	$(MAKE) frontend-format-check
	$(MAKE) frontend-build
	$(MAKE) docs-build

pre-commit: ## Run all pre-commit hooks against the whole tree
	uv run pre-commit run --all-files

serve: ## Start the API with auto-reload (requires the server extra)
	uv run civex serve --reload

dev: ## Frontend dev server (run alongside `make serve`)
	cd frontend && npm run dev

docs: ## Serve the docs site with live reload
	uv run mkdocs serve

docs-build: ## Build the static site into site/ (what CI runs)
	CIVEX_LOG_LEVEL=WARNING uv run mkdocs build --strict

frontend-install: ## Install frontend dependencies (matches CI's `npm ci`)
	cd frontend && npm ci

frontend-lint: ## ESLint (auto-fix)
	cd frontend && npm run lint:fix

frontend-lint-check: ## ESLint, check only (what CI runs)
	cd frontend && npm run lint

frontend-format: ## Prettier
	cd frontend && npm run format

frontend-format-check: ## Prettier, check only
	cd frontend && npm run format:check

frontend-build: ## Type-check + build frontend (what CI runs)
	cd frontend && npm run build

clean: ## Remove caches and the synced environment
	rm -rf .venv .ruff_cache .mypy_cache .pytest_cache .coverage htmlcov
