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

Record `data` is stored as a JSON/JSONB dict (no EAV), keyed by **field UUID** — `RecordService._names_to_ids()`/`_ids_to_names()` translate at the service boundary, so everything above that layer sees name-keyed data and renaming a field costs nothing in storage. Field types: `integer | float | string | boolean | date | datetime | geo | file | file_list | reference | reference_list | enum | url | tags` (`VALID_DTYPES` in `schema_service.py` is the authority).

- `file` / `file_list`: record stores `FileRef` dict(s) `{sha256, filename, size}`; bytes live in `_civex/objects/<sha256[:2]>/<sha256[2:]>` (git object store layout).
- `date`: stored as an ISO string at the precision it was written (`2019`, `2019-06` or `2019-06-14`; a `precision` restriction names the least precise form a field accepts, default `day`). Logic in `domain/partial_dates.py`, mirrored by `frontend/src/utils/partialDates.ts`. Min/max compare whole periods. `datetime`: always stored as a UTC ISO string. `RecordService.add`/`update` normalise every datetime via `_normalise_datetimes()` (and the CLI via `coerce_value`), reading a value with no UTC offset as wall time in the field's `timezone` restriction, else the collection's `timezone` (`datasets.timezone`), else UTC. DST gaps/overlaps and malformed values are rejected; `update` skips values merely echoed back, so a legacy offset-less value isn't shifted when a zone is set later. The logic lives in `domain/timezones.py`; `frontend/src/utils/dates.ts` mirrors its DST rules for display and entry.
- `geo`: stores a GeoJSON geometry dict (WGS84, `[lon, lat]`). Validated by `domain/geo.py` on every write, with or without restrictions; `bbox` with west > east crosses the antimeridian. CSV cells and the CLI read `"lat, lon"`, `POINT(lon lat)` or GeoJSON (`geo.parse_text`); exports write a plain point as `"lat, lon"` (`geo.to_text`). Mirrored by `frontend/src/utils/geo.ts` and `geoCoords.ts`. `parse_coordinates` also reads hemisphere letters and degrees/minutes/seconds (`56°07'12"N 3°24'36"W`); both implementations are tested against the same table of examples. A Point may carry `uncertainty_m` (a foreign member, validated) and a third coordinate (elevation, negative for depth). On the record form `GeoInput` gives guidance and an **Edit on map…** modal (`components/geo/GeoEditor.tsx`): OpenLayers in plain lat/lon with bundled coastlines (`world-atlas`) and a graticule, in a lazy chunk (`GeoMap.tsx`) so the main bundle doesn't carry it; an optional XYZ tile URL comes from `[map]` in `config.toml` (`GET/PATCH /settings/map`, `hooks/useMapSettings.ts`). The editor edits a draft (`utils/geoDraft.ts`) and changes nothing until Apply; file import (`utils/geoImport.ts`) reads GeoJSON, GPX, KML and WKT via OpenLayers' readers.
- `float` with a `unit` restriction: a field has exactly one unit and every stored value is in it. The service never converts; `domain/units.py` (mirrored by `frontend/src/utils/units.ts`) converts only at entry edges: `RecordService.coerce_value` (CLI) reads `"1024 ft"`, the record form's `UnitInput` does the same, and the CSV import asks each column's unit (`MapState.columnUnits`). Changing a field's unit is a relabel, never a conversion (the CLI asks for confirmation). Units outside the table are plain labels.
- `reference`: stores the UUID of another record as a string. The target schema is enforced via a `schema` restriction.
- `file_list`: stores a list of `FileRef` dicts.

On PostgreSQL, JSON columns use `JSONB` via `with_variant`.

Schema inheritance is resolved recursively by `SchemaService.collect_fields()` — parent fields are appended after own fields and labelled with their source schema.

### Collection scope and schema lists

A collection (`datasets` table) carries a `scope` (`local` | `global`, `domain/scopes.py`) and a schema list (`dataset_schemas`, surfaced as `DatasetDTO.schemas` — names). Both are managed by `DatasetService`:

- `RecordService.add` rejects a record whose schema isn't in its collection's list (`_check_schema_allowed`); an empty list allows nothing. A child schema's ancestors must be listed too, and a schema with live records can't be removed (`DatasetService._check_schema_list`/`update`).
- `RecordService.add`/`update` check every `reference`/`reference_list` value (`_check_references`): the target must be a live record in the same collection or in a `global` one. Values equal to the stored ones are skipped on update. Schema-level reference restrictions are *not* checked against collections — schemas are global and can't know their collection.
- A `global` collection that other collections' records reference can't be made `local` or deleted (`RecordService.collection_referrers`).
- `find_by_schema(..., reachable_from=<collection>)` / `GET /records?reachable_from=` is what reference pickers search; `RecordDTO.dataset_name` and `reference_collections` (set in `_attach_reference_labels`) drive the "from collection X" marker in the UI.
- Tests: the schema-list check is disabled by an autouse fixture in `tests/conftest.py`; request `strict_schema_lists` to exercise it.

### Storage volumes

`VolumeAwareFileObjectStore` (`repositories/local/file_store.py`) writes to the first usable volume in `store.volume_queue`. A volume's whole definition lives in `config.toml` (`[store.volumes.<name>]`: `path`, `allocated_gb`, `id`, `state`); the DB holds only the blob inventory (`stored_objects`), never volume configuration.

- `volume_status(name)` is the **single** decision point for "can this volume be used?" — writes, stats, directory walks and inventory reconcile all go through it, and it returns a `VolumeStatus` (`domain/dtos.py`: `state`, `reason`, `fix`). `fix` is interface-neutral prose; the CLI adds the command and the UI a button.
- Identity: `VolumeConfig.id` + a `.civex-volume` marker in the volume root. Enforced only for volumes outside the project, and only once a volume has an `id` (assigned by `StoreService.add_volume`/`adopt_volume`, never during an upload, which must not rewrite `config.toml`). A mismatch is `wrong_drive`.
- Placement: `[store.placement.<collection-id>]` (`PlacementConfig`: `volume`, `on_unavailable` = `spill`|`fail`, `domain/placement.py`) names a collection's home volume. It is keyed by collection **id** and lives in config.toml with the volumes it names. `_write_candidates(collection_id)` is the single place that orders volumes for a new write (home first, then the queue unless `fail`); the hint is a `collection_id` argument on `put`/`put_path`/`put_stream` and `FileService`, supplied by the upload endpoints (`?collection=`), `WorkflowContext.store_file`, the import wizard and record forms (`hooks/uploadCollection.ts`). `StoreService.set_placement`/`clear_placement` manage it; `DatasetService` calls `on_purge` (wired in `context.py`) so a purged collection loses its placement.
- **Dedup always wins over placement.** `_existing_copy()` runs before any write: content already stored on a reachable volume — or recorded in `stored_objects` on a volume that is unplugged — is reused, never copied to the home. Placement only steers content that is not stored yet.
- Picking a location: `StoreService.inspect_path()` is the single rule set for "can this folder become a volume?" (`PathInspection`: `problems` block, `warnings` don't); `add_volume` enforces it, the Add-volume form previews it (`GET /store/inspect`), so they can't disagree. `browse_directory`/`create_folder` back the in-app folder browser (`GET /store/browse`; folders only), because a browser can't give a server-side path. A relative path is resolved against the project root and "inside the project" is the store's own `_inside_project` rule.
- Network drives are mounts the OS already made (`civex/fs_locations.py` detects them from `/proc/mounts`, macOS `mount`, Windows drive type; civex doesn't mount or hold credentials). Anything that touches a volume outside the project goes through `fs_locations.guarded()`: a time-limited call with at most one stuck call per location, so a dead mount becomes `offline` ("not responding") instead of freezing a request, and `_locate` skips volumes that aren't answering so reads elsewhere aren't stalled.
- Where a file is stored is **response-only**. `RecordService._attach_file_locations` stamps `location` (`{volume, state, available}`) on every `file`/`file_list` value, in one inventory lookup and one status check per volume for the whole batch (`store.locate_volumes`); it runs inside `_attach_reference_labels`, which every API read passes through, and **not** in `_with_names`, which audit snapshots also use, so a location is never frozen into the log. `_strip_derived_file_keys` (`DERIVED_FILE_KEYS`) removes `location`/`resolved_filename` on `add`/`update`, because the UI echoes values back. Details come from `FileInfoService` (`GET /files/{sha256}/info`, `civex store where`): every copy with its on-disk path, size, and what uses the file. `GET /files/{sha256}` answers 503 naming the volume when the content is recorded on one that isn't reachable (404 only when it is nowhere).
- Frontend: `hooks/useFileLocationDisplay.ts` is the one rule for when to show a location (always when unavailable; the volume once there are several; always with details in advanced mode); `FileLink` / `FileLocationChip` (`components/records/FileLocation.tsx`) are used everywhere a file is rendered, and `RecordStorageSummary` summarises a record.
- **Moving files between volumes** (`domain/transfers.py`, `services/transfer_engine.py`, `transfer_service.py`, `transfer_jobs.py`, `repositories/local/transfer_repo.py`; table `storage_transfers`). Two kinds: `drain` (empty source volumes) and `consolidate` (gather collections' files; files also used by a collection kept elsewhere stay unless `include_shared`). The engine's per-file order is the whole safety argument and must not be reordered: copy to a scratch file on the target while hashing (must equal the recorded sha256), optional read-back, atomic rename, `record_moves` + commit, *then* remove from the source. A crash between any two steps leaves the file on the source, the target, or both. Resuming re-discovers work from what is physically on the source (`iter_volume_objects`), so no cursor is stored; progress counts only after a batch commit, and `CopyResult.reused` + an inventory check stops a leftover original being counted twice. Transfers copy only through `FileObjectStore.transfer_object`; copies touching a volume outside the project run on a watched thread (`STALL_SECONDS`) because a blocked write to a dead mount can't be interrupted. `TransferService` owns planning (`plan` is the single rule set behind the preview and `create`), freezing drain sources read-only (`StoreService.set_volume_state`, which re-reads config.toml first, remembers the previous state in `frozen`, and restores it on finish/cancel), and interrupted detection (`updated_at` heartbeat, `STALE_SECONDS`). Pause/cancel are saved on the row (`control`) and noticed as progress is saved, so they work across processes (web UI controlling a CLI run and vice versa); `save()` deliberately never writes `control`. `TransferJobs` (`jobs` singleton) runs transfers on server threads and auto-resumes ones paused only because a volume vanished; the CLI (`civex store move`, `store transfers`) runs in the foreground instead. GC and a transfer take mutually exclusive locks. `save_config` is atomic (temp file + `os.replace`) because transfers rewrite config.toml while requests read it. Frontend: Settings → Storage → Tasks (`TransfersTab`, `NewTransferModal`), polling `/store/transfers`.
- A missing volume root is **never created on demand** unless the volume is a relative path inside the project (`_ensure_volume`); and reconcile skips unreachable volumes, so an unplugged drive never loses its inventory rows.

### Names vs. labels

Schemas and fields each carry a `name` and a `label` (see `domain/naming.py`, mirrored in `frontend/src/utils/naming.ts`):

- `name` — the machine key. Slug-validated (`^[a-z_][a-z0-9_]*$`) on create and rename only. Referenced as text by workflow YAML (`field:`, `schema:`, `reference` restrictions), CSV headers, name templates and API paths.
- `label` — free-text display name, nullable. `display_label(name, label)` derives one from the name when unset; `FieldDTO.display_name`/`SchemaDTO.display_name` wrap that.

Validation is write-time only: rows predating the rule keep working, and `civex schema lint` (`SchemaService.lint_names()`) reports them. Restore/import paths pass `allow_legacy_name=True` so an old dump round-trips unchanged. UI forms collect the label first and auto-slug the name (`NameLabelFields`); editing never re-derives an existing name.

### Name templates

`domain/templating.py` is the one string builder: literal text with `{name}` / `{name:spec}` variables (`{{ }}` escape braces; a spec is `|`-chained ops: `upper lower title slug trunc(N)`, a number format `03` / `.2f`, or a date pattern `YYYY-MM-DD`). It is pure (`parse`, `validate`, `render`, `rename_field`, `remove_field`); `render`'s `on_missing` is `skip` (drop a blank value and the separator beside it — record names), `fallback` (None, so the caller keeps something else — file names) or `empty`. Built-ins `schema`, `id`, and for files `ext`, win over fields of the same name.

- A record's name is `schemas.display_template` rendered by `RecordService._natural_name` (surfaced as `RecordDTO.natural_name`); no template means the first non-blank scalar value. It replaced the old `display_fields` list (the migration turns `[a, b]` into `{a} {b}`; `SchemaDTO.from_dict` still reads old dumps).
- `{ref.field}` reaches one hop through a single `reference` field whose `schema` restriction is set (`SchemaService._reference_targets` is what validation allows; file names pass none, so they can't). The engine stays pure: `render` just looks up the key `"ref.field"`, and `RecordService._label_references` fills it in from the targets it already batch-loads for reference labels (`reached_name`, so no extra query) — which means the name using it exists only on API reads, not in `_with_names` audit snapshots, and a target's own label never expands its references. `_template_holders` returns a `via` per hit (None = direct, or the reference field's name) so renames/deletes on the *target* schema's fields rewrite `{ref.f}` too.
- `SchemaService.update` validates a template against the schema's own and inherited fields. `_template_holders`/`_rewrite_templates` keep both `display_template` and every `filename_template` restriction in step when a field is renamed or deleted, resolving by field identity so a shadowed inherited field is left alone.
- `POST /schemas/{name}/preview-name` renders a template against sample values (errors come back in the body). Frontend: `components/templates/TemplateBuilder.tsx` (chips insert at the cursor, per-variable format picker by dtype from `utils/templates.ts`, server-rendered preview) is used by the schema page's Naming tab and the file field's download-name rule.

### Field restrictions

Which restriction keys exist for a type, and how the UI should present them, is declared once in `domain/field_descriptors.py` (`FIELD_TYPES`, `FIELD_KINDS`). `schema_service.VALID_RESTRICTION_KEYS` is derived from it and `GET /schemas/field-types` serves it, so the field editor (`components/schemas/FieldForm.tsx`, rendering `RestrictionControls.tsx` through `controlRegistry.ts`) and the record form's guidance build from data. Adding a restriction means: a descriptor entry, its check in `_check_restrictions()`, and — only if no existing `control` fits — a new control in `RestrictionControls.tsx` registered in `controlRegistry.ts`. Descriptors only describe; validation stays in `_check_restrictions()` (stored values) and `SchemaService` (restriction values, `_check_control_value` + `_validate_restriction_values`). Rules (validation) are kept apart from views (how a value is displayed, e.g. a spectrogram for audio): a field's views are meant to become another section of the field inspector (`InspectorSection` in `SchemaFieldsSection.tsx`) with their own settings, not more keys in `restrictions`.

Each field carries a `restrictions: dict[str, Any]` validated at write time by `_check_restrictions()` in `record_service.py` — the single source of truth. Restriction keys by type:

| Type | Keys |
|---|---|
| `integer`, `float` | `min`, `max` |
| `float` | also `unit` (symbol; canonicalised, e.g. `degC` → `°C`) |
| `string` | `choices` (list), `max_length` |
| `date`, `datetime` | `min`, `max` (ISO strings; compared as parsed objects, not strings; `date` bounds may be partial) |
| `date` | also `precision` (`year` / `month` / `day`) |
| `geo` | `geometry_types` (list), `bbox` (`[west, south, east, north]`) |
| `datetime` | also `timezone` (IANA name; overrides the collection's `timezone` when reading and showing this field) |
| `file`, `file_list` | `accept` (comma-separated MIME/ext), `max_size` (bytes), `filename_template` (see below) |
| `reference` | `schema` (target schema name) |

`filename_template` is a name template (see "Name templates" below; `{ext}` is the original file extension) resolved server-side by `resolve_filename()` in `record_service.py`, a thin wrapper over `templating.render` that adds sanitising — rejected at field-save time if it names a field not on the schema (`SchemaService._validate_filename_template()`). `RecordService._with_names()` resolves it against each record's own field values and stamps the result onto every `file`/`file_list` value in API responses as `resolved_filename`, alongside the unchanged original `filename`; a blank/missing referenced field falls back to the original filename rather than emitting a partial name. The record-UI download link (`DynamicField.tsx`) uses `resolved_filename` for its `download=` attribute. `GET /files/{sha256}` stays content-addressed and record-agnostic — it doesn't accept record/field context to resolve a template itself; it takes an explicit `?filename=` override, so scripted consumers that want the resolved name read it off the record API and pass it through.

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
  utils/dates.ts  # timezone-aware datetime helpers (utcToZonedLocal / zonedLocalToUTC / formatDateTime / effectiveTimeZone)
```

The schema page (`pages/SchemaDetailPage.tsx`) is a compact header over tabs held in the address (`?tab=`): Fields (`SchemaFieldsSection`), Naming (`NamingSection`), Automations, Settings (history and delete). Records are browsed from Collections, not from here.

Settings is a set of sub-pages, not one scroll: `pages/settings/SettingsLayout.tsx` is a section list plus an `<Outlet/>`, with routes `/settings/<appearance|database|storage|recently-deleted|map|advanced>` and `/settings` redirecting to Appearance. Settings > Storage (`components/settings/storage/StorageSettings.tsx`) has Volumes / Collections / Tasks tabs (Tasks = `TasksTab`: `TransfersTab` for moves, then `GCPanel`; the old `?tab=transfers|maintenance` addresses still open it), with the tab and a volume filter held in the address (`?tab=collections&volume=archive`). A volume's own page is `VolumePage` (`/settings/storage/volumes/:name`, reached from the volume's name in the list): it pivots the same collection-by-volume data (`useAllCollectionStorage`) to show which collections are on the drive, plus the volume's `unused_*`/`history_*` bytes (from `FileReferenceRepository.surplus_by_volume`, merged into `GET /store/volumes`) and the moves involving it (`TransferCard`, shared with the Tasks tab). The list and the page share `VolumeSpace` and `useVolumeActions` (edit/remove/adopt/queue and their dialogs), so neither has its own copy. Above the tabs `StorageAttention` lists what needs a look, built by `hooks/useStorageAttention.ts`, the single place that decides what counts (unreachable volume holding files, low space, a move running/paused/interrupted). Where a collection's files are comes from one rule: `FileInfoService.all_collection_storage` (`FileReferenceRepository.volume_breakdowns`, catalog only) behind `GET /store/collections[/{id}]` and `civex store collections`; the single-collection answer is the bulk one for one id. `SpreadBar` and `utils/collectionStorage.gatherPlan` are the shared bar and "gather onto where?" rule used by the collection page and the Collections tab. The Collections tab is where homes are assigned (per row, or in bulk); a collection page's own Storage section edits the same placement. There is deliberately no Storage item in the sidebar.

Pins, recents and the Ctrl+K palette are per-browser (localStorage, `utils/pins.ts` + `hooks/usePins.ts`; there are no user accounts). A pin's `NavTarget` is built in `utils/navTargets.ts`; a pinned saved filter's live count is `hooks/useViewCount.ts` (keyed under `records`, so any record edit refreshes it).

On the record page, `RecordFieldGrid`'s `FileControl` stages an upload: the file sits in `PendingFiles` (with `accept`/`max_size` checks from `utils/fileChecks.ts`) until someone approves it, and only approval saves the record (and so fires workflow triggers). Pending state is page-local; unreferenced objects are left to `gc_service`.

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
