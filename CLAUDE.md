# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

Dependencies and the venv are managed by [uv](https://docs.astral.sh/uv/) — it reads `pyproject.toml`, resolves against the committed `uv.lock`, and provisions a matching Python 3.12 itself (see `.python-version`) if the system doesn't have one.

```bash
uv sync --extra server --extra workflows --extra dev  # standard dev setup (== `make install`)
uv sync --all-extras                                   # every optional extra (== `make install-all`)
uv sync                                                 # base install only, SQLite, no extras

uv lock                                                 # re-resolve after editing pyproject.toml deps
uv run civex --help                                     # run inside the synced env without activating it
```

`uv sync` creates `.venv/`. There's no separate activation step required for `uv run ...`; activate `.venv/bin/activate` directly if you want a persistent shell.

`make check`/`make secrets` also require the [gitleaks](https://github.com/gitleaks/gitleaks#installing) binary on `PATH` — it's not a `uv`/`npm` dependency. Install via `brew install gitleaks`, `go install github.com/gitleaks/gitleaks/v8@latest`, or download a release binary.

## Commands

Common tasks are wrapped in the `Makefile` — `make help`-style targets: `install`, `lint`, `format`, `format-check`, `typecheck`, `test`, `secrets`, `check` (everything CI runs), `pre-commit`, `serve`, `dev`, `clean`.

```bash
# CLI
uv run civex --help
uv run civex init                 # create a _civex/ project in the current directory
uv run civex serve                # start HTTP API (requires the server extra)
uv run civex serve --reload       # dev mode with auto-reload  (== `make serve`)

# Tests
uv run pytest tests/              # run all smoke tests            (== `make test`)
uv run pytest tests/test_smoke.py::test_init_creates_civex_dir  # single test

# Lint / format / typecheck
make check                        # ruff format --check, ruff check, mypy, pytest — what CI runs
make lint                         # ruff check --fix
make format                       # ruff format

# Frontend (cd frontend/ first)
npm run dev                       # Vite dev server (proxies /api to localhost:8000)  (== `make dev`)
npm run build                     # tsc + Vite production build (outputs to frontend/dist/)
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
    registry.py  # Discovers built-ins and user plugins from _civex/plugins/
    builtins/    # Built-in plugins (see Built-in plugins section below)
  workflows/
    definition.py  # Pydantic models for YAML workflow files
    executor.py    # Topological sort (Kahn's) + step execution
  server/
    app.py       # FastAPI app factory
    routers/     # One router per resource: schemas, datasets, records, files, workflows, ui
  config.py      # find_project_root() walks up from cwd; load_config() reads _civex/config.toml
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

Record `data` is stored as a JSON/JSONB dict (no EAV), keyed by **field UUID** — `RecordService._names_to_ids()`/`_ids_to_names()` translate at the service boundary, so everything above that layer sees name-keyed data and renaming a field costs nothing in storage. Field types: `integer | float | string | boolean | date | datetime | file | file_list | reference`.

- `file` / `file_list`: record stores `FileRef` dict(s) `{sha256, filename, size}`; bytes live in `_civex/objects/<sha256[:2]>/<sha256[2:]>` (git object store layout).
- `date`: stored as ISO date string (`YYYY-MM-DD`). `datetime`: stored as UTC ISO string. Naive datetimes are assumed UTC on ingest (`_parse_datetime` in `record_service.py`).
- `reference`: stores the UUID of another record as a string. The target schema is enforced via a `schema` restriction.
- `file_list`: stores a list of `FileRef` dicts.

On PostgreSQL, JSON columns use `JSONB` via `with_variant`.

Schema inheritance is resolved recursively by `SchemaService.collect_fields()` — parent fields are appended after own fields and labelled with their source schema.

### Names vs. labels

Schemas and fields each carry a `name` and a `label` (see `domain/naming.py`, mirrored in `frontend/src/utils/naming.ts`):

- `name` — the machine key. Slug-validated (`^[a-z_][a-z0-9_]*$`) on create and rename only. Referenced as text by workflow YAML (`field:`, `schema:`, `reference` restrictions), CSV headers, `display_fields` and API paths.
- `label` — free-text display name, nullable. `display_label(name, label)` derives one from the name when unset; `FieldDTO.display_name`/`SchemaDTO.display_name` wrap that.

Validation is write-time only: rows predating the rule keep working, and `civex schema lint` (`SchemaService.lint_names()`) reports them. Restore/import paths pass `allow_legacy_name=True` so an old dump round-trips unchanged. UI forms collect the label first and auto-slug the name (`NameLabelFields`); editing never re-derives an existing name.

### Field restrictions

Each field carries a `restrictions: dict[str, Any]` validated at write time by `_check_restrictions()` in `record_service.py` — the single source of truth. Restriction keys by type:

| Type | Keys |
|---|---|
| `integer`, `float` | `min`, `max` |
| `string` | `choices` (list), `max_length` |
| `date`, `datetime` | `min`, `max` (ISO strings; compared as parsed objects, not strings) |
| `file`, `file_list` | `accept` (comma-separated MIME/ext), `max_size` (bytes), `filename_template` (see below) |
| `reference` | `schema` (target schema name) |

`filename_template` is a `{field_name}` placeholder string (plus the reserved `{ext}` token for the original file extension) resolved server-side by `resolve_filename()` in `record_service.py` — rejected at field-save time if it references a field not on the schema (`SchemaService._validate_filename_template()`). `RecordService._with_names()` resolves it against each record's own field values and stamps the result onto every `file`/`file_list` value in API responses as `resolved_filename`, alongside the unchanged original `filename`; a blank/missing referenced field falls back to the original filename rather than emitting a partial name.

### Workflow execution

`executor.run()` topologically sorts steps (Kahn's algorithm), resolves `step_id.output_name` input references, and calls each plugin's `run()` in order. `ctx.commit()` is called once at the end. Custom plugins are discovered from `_civex/plugins/*.py` and must define a class named `Plugin` subclassing `BasePlugin`.

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
| Add a container-tier (Tier 2) plugin starter for a new language | `plugin-templates/<language>/` — Dockerfile + minimal shim speaking the Tier 1 wire protocol (see `plugin-templates/r/`) |
| Add an API endpoint | `src/civex/server/routers/<resource>.py` |
| New domain types | `src/civex/domain/dtos.py` or `src/civex/domain/exceptions.py` |
| Add a frontend API call | `frontend/src/api/<resource>.ts` + hook in `frontend/src/hooks/use<Resource>.ts` |

## Documentation

The docs site lives under `docs/` (MkDocs Material, see `mkdocs.yml`). Some pages are generated at build time — editing a generated page directly loses the change on the next build, so know which is which before touching a file under `docs/`:

| Path | Source of truth |
|---|---|
| `docs/reference/cli/*` | Generated from `civex.main:app` by `docs/_gen/_cli.py` |
| `docs/reference/http-api.md` + `openapi.json` | Generated from `create_app().openapi()` |
| `docs/reference/plugins/*` | Generated from the plugin registry + `docs/_prose/plugins/*.md` |
| everything else under `docs/` | Hand-written |

Keep-in-sync rules:

- New CLI command → write prose help only; no indented line art, and never `\b` escapes — it renders in the generated reference.
- New HTTP endpoint → add a docstring, and `Field(description=)` on any new request/response model — both feed the generated `http-api.md`.
- New built-in plugin → add `docs/_prose/plugins/<slug>.md` with the `<!-- civex:tables -->` marker, or CI fails.

`make docs` serves the site with live reload; `make docs-build` runs the strict build CI uses.
