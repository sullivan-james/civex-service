# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

```bash
python -m venv venv
source venv/bin/activate

pip install -e .                              # SQLite (default)
pip install -e ".[postgres]"                  # add PostgreSQL driver
pip install -e ".[workflows]"                 # add pandas (required by load_csv / rows_to_records)
pip install -e ".[server]"                    # add FastAPI + uvicorn
pip install -e ".[postgres,workflows,server]" # everything
```

## Running the CLI

```bash
civex --help
civex init                    # create a .civex/ project in the current directory
civex serve                   # start HTTP API (requires [server] extra)
civex serve --reload          # dev mode with auto-reload
```

## Architecture

```
src/civex/
  cli/           # Typer commands — parse args → call service → format output
  domain/        # Plain dataclasses (DTOs) and exceptions; no framework dependency
  services/      # Business logic: SchemaService, DatasetService, RecordService, FileService
  repositories/
    protocols.py         # Protocol interfaces (SchemaRepository, DatasetRepository, etc.)
    local/               # SQLAlchemy implementations of those protocols
  db/
    models.py    # SQLAlchemy 2.0 ORM models (Schema, Field, Dataset, Record)
    session.py   # Engine factory; engine is cached, session is per-request
  plugins/
    base.py      # BasePlugin ABC + WorkflowContext dataclass
    registry.py  # Discovers built-ins and user plugins from .civex/plugins/
    builtins/    # load_file, load_csv, get_field, save_field, rows_to_records
  workflows/
    definition.py  # Pydantic models for YAML workflow files
    executor.py    # Topological sort (Kahn's) + step execution
  server/
    app.py       # FastAPI app factory
    routers/     # One router per resource: schemas, datasets, records, files, workflows, ui
  config.py      # find_project_root() walks up from cwd; load_config() reads .civex/config.toml
  context.py     # AppContext dataclass + build_local_context() factory
  console.py     # Rich Console instance used across CLI
```

### Layer rules (strict)

- `cli` → `services` via `AppContext`. Never touches repos or DB models directly.
- `services` → `repositories/protocols` (interfaces). Never imports from `cli` or `db`.
- `repositories/local` → `db/models`. The only layer that imports SQLAlchemy models.
- `plugins` → `WorkflowContext` only. Never imports SQLAlchemy or sessions.
- `domain` has no imports from the rest of civex — safe to import anywhere.

### AppContext pattern

`build_local_context(config)` in `context.py` wires all repos and services. CLI commands call `get_ctx()` from `cli/utils.py`, then call `ctx.commit()` after mutating operations, and `ctx.close()` when done. The server will call `build_local_context()` once per request.

### Data model

Record `data` is stored as a JSON/JSONB dict (no EAV). Schema field types are `integer | float | string | boolean | file`. For `file` fields, the record stores a `FileRef` dict `{sha256, filename, size}`; bytes live in `.civex/objects/<sha256[:2]>/<sha256[2:]>` (git object store layout). On PostgreSQL, JSON columns use `JSONB` via `with_variant`.

Schema inheritance is resolved recursively by `SchemaService.collect_fields()` — parent fields are appended after own fields and labelled with their source schema.

### Workflow execution

`executor.run()` topologically sorts steps (Kahn's algorithm), resolves `step_id.output_name` input references, and calls each plugin's `run()` in order. `ctx.commit()` is called once at the end. Custom plugins are discovered from `.civex/plugins/*.py` and must define a class named `Plugin` subclassing `BasePlugin`.

### CLI pattern

Each CLI module (e.g. `cli/schema.py`) creates a `typer.Typer()` sub-app. Commands call `get_ctx()`, delegate to a service, print with `console` (Rich), call `ctx.commit()`, then `ctx.close()`. Error handling raises `typer.Exit(1)` after printing; `CivexError` subclasses (`NotFoundError`, `AlreadyExistsError`, `ValidationError`) are the canonical error types.

## Key files for common tasks

| Task | File |
|---|---|
| Add a new CLI command | `src/civex/cli/<group>.py` + register in `src/civex/main.py` |
| Add business logic | `src/civex/services/<name>_service.py` |
| Add a DB table | `src/civex/db/models.py` + `src/civex/repositories/protocols.py` + `src/civex/repositories/local/` |
| Add a built-in plugin | `src/civex/plugins/builtins/<name>.py` + register in `src/civex/plugins/builtins/__init__.py` |
| Add an API endpoint | `src/civex/server/routers/<resource>.py` |
| New domain types | `src/civex/domain/dtos.py` or `src/civex/domain/exceptions.py` |
