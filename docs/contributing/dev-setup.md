# Dev setup

## Install

Dependencies and the venv are managed by [uv](https://docs.astral.sh/uv/) — it reads `pyproject.toml`, resolves against the committed `uv.lock`, and provisions a matching Python 3.12 itself (see `.python-version`) if the system doesn't have one.

```bash
git clone https://github.com/CivexData/civex-service
cd civex-service
make install           # uv sync --extra server --extra workflows --extra dev --extra docs
make frontend-install  # cd frontend && npm ci
```

Other useful `uv sync` invocations:

```bash
uv sync --all-extras   # every optional extra                    (== `make install-all`)
uv sync                # base install only, SQLite, no extras
uv lock                # re-resolve into uv.lock after editing pyproject.toml deps
uv run civex --help    # run inside the synced env without activating it
```

`uv sync` creates `.venv/`. There's no separate activation step required for `uv run ...`; activate `.venv/bin/activate` directly if you want a persistent shell.

`make check`/`make secrets` also require the [gitleaks](https://github.com/gitleaks/gitleaks#installing) binary on `PATH` — it's not a `uv`/npm dependency. Install via `brew install gitleaks`, `go install github.com/gitleaks/gitleaks/v8@latest`, or a downloaded release binary.

## Running the app locally

Run the API and the frontend dev server in parallel, in two terminals:

```bash
uv run civex serve --reload   # API + built frontend, auto-reload  (== `make serve`)
cd frontend && npm run dev    # Vite dev server, proxies /api      (== `make dev`)
```

Use `http://localhost:5173` (the Vite dev server) while iterating on the frontend — it proxies `/api` calls to the civex server on `:8000` and gives you hot reload. `civex serve` on its own serves whatever is already built into `frontend/dist/`, which is what a production install sees.

## Makefile targets

```bash
make lint          # ruff check --fix src/ civex-plugin-sdk/src/
make format        # ruff format src/
make format-check  # ruff format --check src/ (what CI runs)
make typecheck     # mypy src/civex civex-plugin-sdk/src/civex_plugin_sdk
make test          # uv run pytest tests/ -q --cov=civex --cov-report=term-missing
make secrets       # gitleaks git --redact -v (requires the gitleaks binary, see above)
make audit         # pip-audit + npm audit --audit-level=high
make check         # everything CI runs, in one shot — see below
make pre-commit    # run all pre-commit hooks against the whole tree
make clean         # remove .venv, ruff/mypy/pytest caches, coverage output
```

`make check` runs `format-check`, `ruff check`, `typecheck`, `test`, `secrets`, `audit`, `migrations-check`, `frontend-lint-check`, `frontend-format-check`, `frontend-build`, and `docs-build` — the same jobs CI runs, so a green `make check` locally means CI will be green too. It requires frontend deps installed (`make frontend-install`) in addition to `make install`.

## Architecture

See [Architecture](architecture.md) for the module layout, layer rules, and data model.
