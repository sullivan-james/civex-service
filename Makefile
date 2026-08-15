.PHONY: install install-all lock lint lint-check format format-check typecheck test test-fast secrets audit migrations-check check check-all check-fast check-fast-all pre-commit serve dev docs docs-build clean frontend-install frontend-lint frontend-lint-check frontend-format frontend-format-check frontend-build frontend-test

install: ## Sync the dev environment (server + workflows + dev + docs extras)
	uv sync --extra server --extra workflows --extra dev --extra docs

install-all: ## Sync every optional extra
	uv sync --all-extras

lock: ## Re-resolve dependencies into uv.lock
	uv lock

lint: ## Ruff lint (auto-fix)
	uv run ruff check --fix src/ civex-plugin-sdk/src/

lint-check: ## Ruff lint, check only (what CI runs)
	uv run ruff check src/ civex-plugin-sdk/src/

format: ## Ruff format
	uv run ruff format src/

format-check: ## Ruff format, check only (what CI runs)
	uv run ruff format --check src/

typecheck: ## Mypy
	uv run mypy src/civex civex-plugin-sdk/src/civex_plugin_sdk

test: ## Run the test suite with coverage
	uv run pytest tests/ -q -n auto --cov=civex --cov-report=term-missing

# Coverage costs much less under `-n auto` than it did serially, and how
# much depends on the machine: measured at 47s vs 41s in the civex-agent
# runner container, but 51s vs 30s on a 22-core workstation. Either way
# `check` keeps coverage (CI consumes the report) and only `check-fast`
# drops it.
test-fast: ## Test suite without coverage — for tight iteration loops
	uv run pytest tests/ -q -n auto

secrets: ## Scan the repo (working tree + history) for leaked secrets
	@command -v gitleaks >/dev/null 2>&1 || { echo "gitleaks not found — install via 'brew install gitleaks' or https://github.com/gitleaks/gitleaks#installing"; exit 1; }
	gitleaks git --redact -v

# Both commands call out to a registry (PyPI's advisory API, npm's) with no
# client-side timeout of their own. In civex-agent's unattended runner a
# network stall here has no human to Ctrl-C it, so it silently burns the
# whole run's wall-clock budget instead of failing fast — confirmed live:
# a run sat with zero output for the better part of an hour with nothing
# to show but this step never returning.
audit: ## Scan Python + frontend dependencies for known vulnerabilities
	timeout 120 uv run pip-audit
	cd frontend && timeout 120 npm audit --audit-level=high

migrations-check: ## Check for Alembic migration drift (what CI runs)
	$(eval DBFILE := $(shell mktemp -u --suffix=.db))
	uv run alembic -x db_url="sqlite:///$(DBFILE)" upgrade head
	uv run alembic -x db_url="sqlite:///$(DBFILE)" check

# format-check/lint-check/typecheck/test/secrets/audit/migrations-check mirror
# ci.yml's lint/test/audit/migrations jobs; frontend-lint-check/
# frontend-format-check/frontend-test/frontend-build mirror frontend-ci.yml's
# lint/test/build jobs; docs-build mirrors docs.yml's build job. Keep this
# list in lockstep with all three workflow files — this target's whole point
# is that a green `make check` locally means CI will be green too, so
# agent-driven commits stop landing PRs that pass this and then fail the real
# pipeline. Requires frontend deps installed (frontend-install or npm ci) in
# addition to `make install`.
#
# Prerequisites, not sequential `$(MAKE)` lines in a recipe body. That's
# the whole reason this is split into `check` and `check-all`: a recipe
# body always runs serially no matter what -j says, so the old shape could
# never use more than one core, while ci.yml runs the same work as five
# parallel jobs. Nothing here is ordered against anything else — the two
# pairs that touch the same tree are safe by config (frontend-build writes
# frontend/dist, which both eslint.config.js and .prettierignore exclude).
#
# `check` re-invokes make rather than being the parallel target itself so
# callers get the parallelism without knowing to ask: CI, civex-agent's
# check_commands, and a human all just run `make check`.
# --output-sync=target keeps each target's output as one contiguous block
# instead of interleaving twelve streams — that matters most for the
# unattended agent, whose only view of a failure is this text.
#
# Measured in the civex-agent runner container: 249s serial, and the
# parallel shape costs about as long as its slowest single target (the
# test suite, 47s) since everything else lands in 0-7s.
#
# Bounded, not bare `-j`. The fan-out here multiplies with the one inside
# `test` (pytest's own `-n auto`, one worker per core), and the product is
# set by core count while the ceiling that matters is memory: a 22-core
# box with 7GB gets 22 pytest workers plus eleven other targets at once
# and the kernel starts killing things. Four lanes is enough to hide
# every non-test target behind the test suite — that's all the
# parallelism this target can actually use, since after `test` the next
# slowest is 7s. Raise CHECK_JOBS on a machine with memory to spare.
CHECK_JOBS ?= 4

check: ## Everything CI checks, in one shot
	@$(MAKE) --no-print-directory --output-sync=target -j$(CHECK_JOBS) check-all

check-all: format-check lint-check typecheck test secrets audit migrations-check \
	frontend-lint-check frontend-format-check frontend-test frontend-build docs-build

# The subset worth iterating on, for an agent or a human going round the
# loop repeatedly: everything that a single change plausibly breaks, and
# nothing that it doesn't. What's dropped is repo-wide invariants rather
# than anything about the code under edit — a secret scan over git
# history, two network dependency audits, Alembic drift, and the docs
# build. CI still runs all four on the PR, and so does `make check`, which
# is what civex-agent verifies with before it pushes. Do not point CI at
# this target: `check` is the CI-parity gate, this is the fast loop.
check-fast: ## The subset worth iterating on — see check for the full gate
	@$(MAKE) --no-print-directory --output-sync=target -j$(CHECK_JOBS) check-fast-all

check-fast-all: format-check lint-check typecheck test-fast \
	frontend-lint-check frontend-format-check frontend-test frontend-build

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

frontend-test: ## Vitest, run once (what CI runs)
	cd frontend && npm run test

frontend-build: ## Type-check + build frontend (what CI runs)
	cd frontend && npm run build

clean: ## Remove caches and the synced environment
	rm -rf .venv .ruff_cache .mypy_cache .pytest_cache .coverage htmlcov
