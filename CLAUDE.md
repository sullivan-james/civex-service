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
pip install -e ".[dev]"                       # add pytest + httpx for tests
pip install -e ".[postgres,workflows,server]" # everything
```

## Commands

```bash
# CLI
civex --help
civex init                    # create a .civex/ project in the current directory
civex serve                   # start HTTP API (requires [server] extra)
civex serve --reload          # dev mode with auto-reload

# Tests
pytest tests/                 # run all smoke tests
pytest tests/test_smoke.py::test_init_creates_civex_dir  # single test

# Frontend (cd frontend/ first)
npm run dev                   # Vite dev server (proxies /api to localhost:8000)
npm run build                 # tsc + Vite production build (outputs to frontend/dist/)
```

The server serves the built frontend from `frontend/dist/` via the `ui` router. During development run `civex serve --reload` and `npm run dev` in parallel — Vite proxies API calls.

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
    builtins/    # Built-in plugins (see Built-in plugins section below)
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

`build_local_context(config)` in `context.py` wires all repos and services. CLI commands call `get_ctx()` from `cli/utils.py`, then call `ctx.commit()` after mutating operations, and `ctx.close()` when done. The server calls `build_local_context()` once per request.

### Data model

Record `data` is stored as a JSON/JSONB dict (no EAV). Field types: `integer | float | string | boolean | date | datetime | file | file_list | reference`.

- `file` / `file_list`: record stores `FileRef` dict(s) `{sha256, filename, size}`; bytes live in `.civex/objects/<sha256[:2]>/<sha256[2:]>` (git object store layout).
- `date`: stored as ISO date string (`YYYY-MM-DD`). `datetime`: stored as UTC ISO string. Naive datetimes are assumed UTC on ingest (`_parse_datetime` in `record_service.py`).
- `reference`: stores the UUID of another record as a string. The target schema is enforced via a `schema` restriction.
- `file_list`: stores a list of `FileRef` dicts.

On PostgreSQL, JSON columns use `JSONB` via `with_variant`.

Schema inheritance is resolved recursively by `SchemaService.collect_fields()` — parent fields are appended after own fields and labelled with their source schema.

### Field restrictions

Each field carries a `restrictions: dict[str, Any]` validated at write time by `_check_restrictions()` in `record_service.py` — the single source of truth. Restriction keys by type:

| Type | Keys |
|---|---|
| `integer`, `float` | `min`, `max` |
| `string` | `choices` (list), `max_length` |
| `date`, `datetime` | `min`, `max` (ISO strings; compared as parsed objects, not strings) |
| `file`, `file_list` | `accept` (comma-separated MIME/ext), `max_size` (bytes) |
| `reference` | `schema` (target schema name) |

### Workflow execution

`executor.run()` topologically sorts steps (Kahn's algorithm), resolves `step_id.output_name` input references, and calls each plugin's `run()` in order. `ctx.commit()` is called once at the end. Custom plugins are discovered from `.civex/plugins/*.py` and must define a class named `Plugin` subclassing `BasePlugin`.

Workflow triggers fire via `trigger_for_record()` in `WorkflowJobService`. When a record is **created**, both `record_created` and `record_updated` are fired — but `record_updated` only includes fields with non-null values in `changed_fields`, so field-restricted triggers (`fields: [some_field]`) do not fire unless that field was actually set to a non-null value on creation.

Manual workflow runs supply inputs via `initial_outputs` in the executor (key `"__input__"`). Steps reference them as `__input__.field_name`.

### Built-in plugins

| Plugin ID | Purpose |
|---|---|
| `civex.get_field` | Read a field from the trigger record |
| `civex.save_field` | Write a value to a field on the trigger record |
| `civex.save_fields` | Write multiple fields at once |
| `civex.load_file` | Load bytes + filename from a file field |
| `civex.load_file_list` | Load a list of file refs from a file_list field |
| `civex.extract_from_filename` | Apply a regex to a filename; optionally convert to date/datetime using token format (`YYYY MM DD HH mm SS`); non-token chars are raw regex so `[-_]` works as a separator alternative |
| `civex.create_records_from_files` | Create one record per file in a file list (no key matching — pure insert) |
| `civex.match_files_to_records` | Match files to existing child records by key extracted from filename; creates if not found |
| `civex.upsert_records` | Upsert records from a pandas DataFrame |
| `civex.rows_to_records` | Convert rows to records |
| `civex.load_csv` | Load a CSV file into a DataFrame |

### CLI pattern

Each CLI module (e.g. `cli/schema.py`) creates a `typer.Typer()` sub-app. Commands call `get_ctx()`, delegate to a service, print with `console` (Rich), call `ctx.commit()`, then `ctx.close()`. Error handling raises `typer.Exit(1)` after printing; `CivexError` subclasses (`NotFoundError`, `AlreadyExistsError`, `ValidationError`) are the canonical error types.

### Frontend

React + TypeScript (Vite). Entry: `frontend/src/main.tsx`. Routing via React Router; data fetching via TanStack Query v5.

```
frontend/src/
  api/          # Typed fetch wrappers (schemas.ts, records.ts, workflows.ts, …)
  hooks/        # TanStack Query hooks (useSchemas, useRecords, useWorkflows, …)
  pages/        # One file per route (SchemaDetailPage, RecordDetailPage, JobsPage, …)
  components/   # Shared UI (records/DynamicField.tsx, jobs/JobsTable.tsx, …)
  utils/dates.ts  # utcToDatetimeLocal / datetimeLocalToUTC helpers
```

`DynamicField` is the single component that renders an editable input for any field type, including restriction-aware behaviour (choices→select, min/max, accept/max_size on files). `JobsTable` owns its own pagination state and accepts `recordId?` + `statusFilter?` props — do not duplicate pagination in parent pages.

## Key files for common tasks

| Task | File |
|---|---|
| Add a new CLI command | `src/civex/cli/<group>.py` + register in `src/civex/main.py` |
| Add business logic | `src/civex/services/<name>_service.py` |
| Add a DB table | `src/civex/db/models.py` + `src/civex/repositories/protocols.py` + `src/civex/repositories/local/` |
| Add a built-in plugin | `src/civex/plugins/builtins/<name>.py` (auto-discovered; no registration needed) |
| Add an API endpoint | `src/civex/server/routers/<resource>.py` |
| New domain types | `src/civex/domain/dtos.py` or `src/civex/domain/exceptions.py` |
| Add a frontend API call | `frontend/src/api/<resource>.ts` + hook in `frontend/src/hooks/use<Resource>.ts` |
