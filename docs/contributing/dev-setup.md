# Dev setup

## Install

Dependencies and the venv are managed by [uv](https://docs.astral.sh/uv/) — it reads `pyproject.toml`, resolves against the committed `uv.lock`, and provisions a matching Python 3.12 itself if the system doesn't have one.

```bash
git clone https://github.com/CivexData/civex-service
cd civex-service
make install          # uv sync --extra server --extra workflows --extra dev
make frontend-install # cd frontend && npm ci
```

`uv sync` creates `.venv/`. There's no separate activation step required for `uv run ...`; activate `.venv/bin/activate` directly if you want a persistent shell.

`make check`/`make secrets` also require the [gitleaks](https://github.com/gitleaks/gitleaks#installing) binary on `PATH` — it's not a `uv`/`npm` dependency.

## Running the app locally

```bash
uv run civex serve --reload   # API + built frontend, auto-reload  (== `make serve`)
cd frontend && npm run dev    # Vite dev server, proxies /api      (== `make dev`)
```

## Checks

```bash
make lint       # ruff check --fix
make format     # ruff format
make typecheck  # mypy
make test       # uv run pytest tests/
make check      # everything CI runs, in one shot: format, lint, typecheck, test, secrets, audit, frontend, docs build
make pre-commit # run all pre-commit hooks against the whole tree
```

`make check` requires frontend deps installed (`make frontend-install`) in addition to `make install`.

## Architecture

See [Architecture](architecture.md) for the module layout and layer rules.
