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

Record `data` is stored as a JSON/JSONB dict (no EAV), keyed by **field UUID** — `RecordService._names_to_ids()`/`_ids_to_names()` translate at the service boundary, so everything above that layer sees name-keyed data and renaming a field costs nothing in storage. Field types: `integer | float | string | boolean | date | datetime | geo | file | file_list | reference | reference_list | enum | url | tags | longtext` (`VALID_DTYPES` in `schema_service.py` is the authority).

- `file` / `file_list`: record stores `FileRef` dict(s) `{sha256, filename, size}`; bytes live in `_civex/objects/<sha256[:2]>/<sha256[2:]>` (git object store layout).
- `date`: stored as an ISO string at the precision it was written (`2019`, `2019-06` or `2019-06-14`; a `precision` restriction names the least precise form a field accepts, default `day`). Logic in `domain/partial_dates.py`, mirrored by `frontend/src/utils/partialDates.ts`. Min/max compare whole periods. `datetime`: always stored as a UTC ISO string. `RecordService.add`/`update` normalise every datetime via `_normalise_datetimes()` (and the CLI via `coerce_value`), reading a value with no UTC offset as wall time in the field's `timezone` restriction, else the collection's `timezone` (`datasets.timezone`), else UTC. DST gaps/overlaps and malformed values are rejected; `update` skips values merely echoed back, so a legacy offset-less value isn't shifted when a zone is set later. The logic lives in `domain/timezones.py`; `frontend/src/utils/dates.ts` mirrors its DST rules for display and entry, and works to the second: the datetime input must have `step={1}` (the default minute step hides the seconds field), `utcToZonedLocal` includes seconds when non-zero, `zonedLocalToUTC` accepts seconds and a fraction, and `formatDateTime` shows seconds when the value has them.
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
- Network drives are mounts the OS already made (`civex/fs_locations.py` detects them from `/proc/mounts`, macOS `mount`, Windows drive type; civex doesn't mount or hold credentials). Anything that touches a volume outside the project goes through `fs_locations.guarded()`: a time-limited call with at most one call per location outstanding: a caller that arrives while an earlier call is merely busy (younger than `FS_TIMEOUT`) shares its answer or waits its turn, and only a call already past the timeout counts as stuck, so a dead mount becomes `offline` ("not responding") instead of freezing a request, and a healthy-but-busy one doesn't, and `_locate` skips volumes that aren't answering so reads elsewhere aren't stalled.
- Where a file is stored is **response-only**. `RecordService._attach_file_locations` stamps `location` (`{volume, state, available, reason, fix}`; `reason`/`fix` are the volume's own words for why it can't be opened and what to do, blank when it can) on every `file`/`file_list` value, in one inventory lookup and one status check per volume for the whole batch (`store.locate_volumes`); it runs inside `_attach_reference_labels`, which every API read passes through, and **not** in `_with_names`, which audit snapshots also use, so a location is never frozen into the log. `_strip_derived_file_keys` (`DERIVED_FILE_KEYS`) removes `location`/`resolved_filename` on `add`/`update`, because the UI echoes values back. Details come from `FileInfoService` (`GET /files/{sha256}/info`, `civex store where`): every copy with its on-disk path, size, and what uses the file. `GET /files/{sha256}` answers 503 naming the volume when the content is recorded on one that isn't reachable (404 only when it is nowhere).
- Frontend: `hooks/useFileLocationDisplay.ts` is the one rule for when to show a location (always when unavailable; the volume once there are several; always with details in advanced mode); `FileLink` / `FileLocationChip` (`components/records/FileLocation.tsx`) are used everywhere a file is rendered, and `RecordStorageSummary` summarises a record. The chip is a click/keyboard popover for everyone (plain-words where/online/what to do, from the location's `reason`/`fix`; **More details** mounts `FileInfoPanel`, already open in advanced mode), and `FileLink` checks a download with a headers-only request first so a drive unplugged since page load says which drive instead of the browser's generic failure. Uploads share `hooks/useFileUploads.ts` (live bytes/speed/ETA, a "Saving…" phase once every byte is sent, cancel via `AbortSignal` that keeps finished files) and `components/records/UploadProgress.tsx`, used by both `RecordFieldGrid`'s `FileControl` and `DynamicField`.
- **Moving files between volumes** (`domain/transfers.py`, `services/transfer_engine.py`, `transfer_service.py`, `transfer_jobs.py`, `repositories/local/transfer_repo.py`; table `storage_transfers`). Two kinds: `drain` (empty source volumes) and `consolidate` (gather collections' files; files also used by a collection kept elsewhere stay unless `include_shared`). The engine's per-file order is the whole safety argument and must not be reordered: copy to a scratch file on the target while hashing (must equal the recorded sha256), optional read-back, atomic rename, `record_moves` + commit, *then* remove from the source. A crash between any two steps leaves the file on the source, the target, or both. Resuming re-discovers work from what is physically on the source (`iter_volume_objects`), so no cursor is stored; progress counts only after a batch commit, and `CopyResult.reused` + an inventory check stops a leftover original being counted twice. Transfers copy only through `FileObjectStore.transfer_object`; copies touching a volume outside the project run on a watched thread (`STALL_SECONDS`) because a blocked write to a dead mount can't be interrupted. `TransferService` owns planning (`plan` is the single rule set behind the preview and `create`), freezing drain sources read-only (`StoreService.set_volume_state`, which re-reads config.toml first, remembers the previous state in `frozen`, and restores it on finish/cancel), and interrupted detection (`_reap`: a record is dead only when its `updated_at` is stale **and** `transfer_lock_held()` is false — silence alone never is, since a read-back or slow drive goes quiet while alive). Pause/cancel are saved on the row (`control`) and noticed as progress is saved, so they work across processes (web UI controlling a CLI run and vice versa); `save()` deliberately never writes `control`. **Transfers queue and run one at a time**: `create`/`begin_resume` save a transfer as `queued`, and `TransferService.next_runnable()` is the single rule for what runs next (oldest queued, or one paused only for a drive that has since answered). `TransferWorker.drain()` (`transfer_worker.py`) runs them in turn and is hosted by whichever process is at hand: the CLI (`civex store move`/`transfers resume`/`transfers run`) runs it in the foreground with a live bar, and the server's `TransferJobs` (`jobs` singleton) runs it on one thread started at startup and when something is queued, holding the running transfer's latest progress in memory (`live_progress`, which the API reports in preference to the saved copy). The store's transfer lock (O_EXCL, PID-owned) keeps it to one runner across processes: a host that finds it held (`TransferBusy`) leaves the queue to the one running it. Pausing or cancelling a queued transfer settles it at once; pausing one waiting for a drive stops the waiting. A drain's sources are frozen when it starts and put back whenever it stops for good, pauses or fails. GC and a transfer take mutually exclusive lock files, each holding its owner's PID, so a lock whose process has died is free at once (a lock with no readable PID falls back to a one-hour mtime). A copy flushing to disk (`fsync`, one call that can't report progress) gets a size-scaled stall limit (`_CopyJob.stall_limit`). SQLite connections set `busy_timeout` (`db/engine.py`); WAL is deliberately not used (sidecar files break copying/moving the DB, and it is unreliable on network/WSL drives). `save_config` is atomic (temp file + `os.replace`) because transfers rewrite config.toml while requests read it. Frontend: Settings → Storage → Tasks (`TransfersTab`, `NewTransferModal`), polling `/store/transfers`.
- A missing volume root is **never created on demand** unless the volume is a relative path inside the project (`_ensure_volume`); and reconcile skips unreachable volumes, so an unplugged drive never loses its inventory rows.

### History (audit log) and revert

`audit_log` rows hold full before/after snapshots (`old_data`/`new_data`); the entry's *diff* is never stored. `domain/audit_diff.py` (`diff_entry`) is the one place a diff is made, and `AuditService` (`services/audit_service.py`, `ctx.history_svc`; `ctx.audit_svc` is still the raw `LocalAuditRepository`, used by sync and `status`) is the one place it is served: every audit endpoint and `civex history` read through `page`/`get`, which attach `changes` (`AuditLogDTO.changes`, response-only, never in a sync bundle) with the field's current label/dtype and in schema order. Record snapshots are **name-keyed** (`_with_names`) for every action; older delete/restore rows are id-keyed, so `AuditService._by_field_name` translates them on read (no migration). `DERIVED_FILE_KEYS` (`domain/dtos.py`) are ignored by the diff, so an echoed-back file isn't an edit. `scope_of(kind, ref)` resolves a record/schema (its own fields)/collection to the list scope, so routers and CLI share it.

Revert is record-only: `plan_revert` is the single rule set behind the UI preview (`GET /audit/{id}/revert`), `POST /audit/{id}/revert` and `civex history revert`, and `revert` applies it **only through `RecordService.update/delete/restore`**, so validation, reference checks, triggers and a fresh audit entry all happen (a revert is itself revertible). Per field: `apply` (still as the entry left it), `conflict` (edited since; only with `force`), `same`, `skipped` (field gone, or a file whose bytes were GC'd: history-only blobs aren't GC roots). Reverting an update sends the *whole* merged data, since `RecordRepository.update` replaces `data`. Schema/field/collection entries are readable but not revertible. Frontend: rows of `AuditTrail` open `AuditEntryDialog` (full `changes` via `AuditChangeList`, then a `RevertPanel` that shows the server's plan before confirming); `utils/recordAudit.tsx`, `schemaAudit.ts` and `collectionAudit.ts` now only supply titles. **Activity** (`/activity`, `ActivityPage`, sidebar *Activity*) is one list, `ActivityFeed`; there is no separate Recently Deleted page (`/trash` redirects to Activity with **Deleted** on). The same `ActivityFeed` is a record's History tab (scoped `under` that record) and a collection's Activity tab (scoped `collection`); a schema's History stays `AuditTrail`. **Deleted** is a toggle on the feed: it adds `now = deleted` and `change = delete` to the filter (`utils/auditFilter.ts` `toggleDeleted`), so what is waiting to be restored is just history narrowed, and an item's row has **Restore** (the `RestoreDialog`) and its dialog **Delete permanently**. With it on, **Restore all N** restores everything the filter matches: `AuditService.plan_restore_all`/`restore_all` (`GET`/`POST /audit/restore-all`) take the same filter, add the two conditions server-side, restore collections, then schemas, then records in rounds (a record under another in the set comes back with it, or once it has; one still under a deleted thing outside the set is *blocked* and reported), as one `restore` batch.

*History is filtered like records and runs, with their machinery, not its own.* `domain/audit_filters.py` declares `AUDIT_FIELDS` (`when`, `kind`, `change`, `how`, `collection`, `schema`, `under`, `now`) once, as `run_filters.py` does, and `parse_audit_filter` checks a `domain/filters.py` tree against them; `GET /audit/filter-fields` serves them, `GET /audit/events?filter=&q=&sort=` takes the tree, and the UI is the explorer's `FilterControls` over `runFilterFields` (`utils/auditFilter.ts`), with the page's own scope AND-ed in (`withScope`) and not shown as a chip. `AuditFilter` (`domain/audit_filter.py`, like `RecordQuery`) carries the fixed scopes plus `where`; `AuditService._resolve` turns what a person picks into what the repo tests (a collection or schema *name* becomes its id so a rename can't lose history, and `schema` matches the schema's own entries plus any snapshot whose `schema_id` is it, i.e. its fields, views and records of exactly that type; `under` becomes the record and everything beneath it, live or deleted) and `audit_repo._condition` maps each field to SQL (`under`/`collection` also match snapshots that *name* the id, which is how a purged child is still found). `now` (live | deleted | gone) is answered from the records table; `AuditLogDTO.now` / `AuditService._where_now` say it on each single entry, one lookup per page, so a lost record can be told from an edited, deleted or purged one.

*Bulk operations are one event.* `audit_batches` + `audit_log.batch_id` (migration `f2a6c8d1e093`; local only, not in a sync bundle). `LocalAuditRepository.batch(kind, label, ref)` creates the batch lazily at the first write inside it and joins an enclosing one, so a workflow run that deletes a tree is the run's one event. The server opens batches for record delete/restore/purge of more than one record (`_audit_batch`) and for each workflow run (`background.run_pending_jobs`, `cli.utils.run_job`); the browser import opens one with `POST /audit/batches` and sends `X-Civex-Batch` on each request (`get_ctx` joins it; an unknown id is ignored). `list_events` groups by `coalesce(batch_id, id)`; a batch reports `parts` (counts by kind and action), its entries are paged at `/audit/batches/{id}/entries`. A collection or schema delete is still one entry, since its records are stamped by the cascade, not logged. Batches can't be reverted yet (only single record changes can).

*Where a thing is now.* `now` is live | deleted | gone for a record, a collection or a schema (`audit_repo._now_is`, answered from those tables, and `AuditService._where_now` on each single entry with `ref`, the id or name to restore it by). **Permanently deleting a record deletes every audit entry about it and leaves one tombstone**: `RecordService.purge`/`purge_records` call `forget_records` (all its entries, then any batch left empty) and log one `purge` entry whose snapshot is `audit_diff.tombstone` (id, collection, schema, parent, created/deleted times, `"tombstone": true`, no `data`), so nothing it held survives in history and `now` is *gone*. A collection or schema purge deletes its records' entries (`forget_records_matching` on `"dataset_id"`/`"schema_id"` in the snapshot) and its own `purge` entry is the tombstone. Records purged before this are cleaned by `RetentionService.forget_purged` (`POST /retention/purged-history`, `civex retention forget-purged`, shown on Settings → Retention only while any remain), which keeps or makes one tombstone each. `civex trash list` is history filtered to deleted, in the CLI.

### Restoring from Recently Deleted

A delete stamps the thing and everything it cascades to with **one `deleted_at`** (`DatasetRepository.delete`, `SchemaRepository.delete`, `RecordRepository.delete_many`), and restore uses it: `DatasetRepository.restore`/`SchemaRepository.restore` bring back only records whose `deleted_at` equals the parent's, and `RecordService._restore_group` the descendants with the same stamp reached through others in the group, so a record deleted on its own earlier stays deleted. This is the stand-in for batch ids (see below), not a replacement: it breaks if two operations ever share a timestamp. `RecordService.restore_plan` is the single rule for "can this come back": a record is `blocked_by` (`BlockerDTO`) its collection, then its schema, then the topmost deleted record directly above it, and `restore` refuses with `RestorePlanDTO.blocked_message` (the one wording, so the API/CLI/UI agree). `DatasetService`/`SchemaService.restore_plan` give the count of records that would return. `AuditService.plan_revert` of a delete uses the same plan and carries the `blocker`. Frontend: `RestoreDialog` (`components/trash/`) is the only restore entry in the UI: it fetches the plan, says what returns and where, and when blocked offers to restore the blocker instead (a trail, with Back); `useRestore` shows the receipt (what came back, where, a **View** link) and invalidates every cache a restore touches.

### Retention (clean-ups by age)

`[retention]` (`RetentionConfig`): `purge_after_days` (how long deleted items stay restorable), `auto_purge_deleted` (whether a clean-up then deletes them), `audit_days`, `run_days` (None = forever, the default for everything). **Nothing runs by itself** (the server has no scheduler); `RetentionService` (`ctx.retention_svc`; `civex retention show|run`; `GET/PATCH /settings/retention`, `POST /retention/run`; Settings → Retention) is started by a person or a cron, always counts first (`dry_run` is the default), and takes `RetentionCutoffs` from the settings (`settings_cutoffs`) and/or explicit dates per kind (`cutoffs`: a date wins over the setting). Order: deleted collections, then schemas (their records go with them, no purge line each), then the records deleted on their own (`RecordRepository.purgeable_deleted`: never one with a child that stays, nor anything above it), then history, then runs, so the purges just made are the newest history and survive. History (`audit_repo.prune`) keeps entries about anything currently deleted (`_now_is("deleted")`, so *Deleted* in Activity still works) and, with a remote, entries not in a pushed commit; it then drops batches left empty. Runs (`job_repo.delete_finished_before`) are only completed/failed/cancelled ones, removed with their step logs via `bulk_delete_jobs`. Files nothing refers to afterwards are `GCService`'s job, not this one's. Retention's history pruning is by age; permanently deleting a record removes *its* history regardless (see "Where a thing is now"), leaving a tombstone that pruning may later remove by age like any entry.

### Names vs. labels

Schemas and fields each carry a `name` and a `label` (see `domain/naming.py`, mirrored in `frontend/src/utils/naming.ts`):

- `name` — the machine key. Slug-validated (`^[a-z_][a-z0-9_]*$`) on create and rename only. Referenced as text by workflow YAML (`field:`, `schema:`, `reference` restrictions), CSV headers, name templates and API paths.
- `label` — free-text display name, nullable. `display_label(name, label)` derives one from the name when unset; `FieldDTO.display_name`/`SchemaDTO.display_name` wrap that.

Validation is write-time only: rows predating the rule keep working, and `civex schema lint` (`SchemaService.lint_names()`) reports them. Restore/import paths pass `allow_legacy_name=True` so an old dump round-trips unchanged. UI forms collect the label first and auto-slug the name (`NameLabelFields`); editing never re-derives an existing name.

### Name templates

`domain/templating.py` is the one string builder: literal text with `{name}` / `{name:spec}` variables (`{{ }}` escape braces; a spec is `|`-chained ops: `upper lower title slug trunc(N)`, a number format `03` / `.2f`, or a date pattern `YYYY-MM-DD`). It is pure (`parse`, `validate`, `render`, `rename_field`, `remove_field`); `render`'s `on_missing` is `skip` (drop a blank value and the separator beside it — record names), `fallback` (None, so the caller keeps something else — file names) or `empty`. Built-ins `schema`, `id`, and for files `ext`, win over fields of the same name.

- A record's name is `schemas.display_template` rendered by `RecordService._natural_name` (surfaced as `RecordDTO.natural_name`); no template means the first non-blank value of a type not in `templating.UNNAMEABLE_DTYPES`. `SchemaService.add_field` starts a schema with no template (and no other own nameable field) with `{that_field}` so the rule is visible and editable (audited as a schema update; dump restore passes `auto_name=False`); schemas older than that keep the implicit rule, which the Naming tab names in its placeholder. It replaced the old `display_fields` list (the migration turns `[a, b]` into `{a} {b}`; `SchemaDTO.from_dict` still reads old dumps).
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
| `longtext` | `max_length` (multi-line text box; plain string, newlines kept; not nameable in name templates) |
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

**Stopping and provenance.** `AutomationConfig.paused` (`[automation]` in config.toml, read cheaply by `read_automation_paused(civex_dir)`) is the kill switch, and `WorkflowJobService` is its one decision point: `trigger_for_record` enqueues nothing, `enqueue_manual` raises, and `claim_pending` returns None while paused, so the server's `run_pending_jobs` and the CLI's `drain_jobs` both stop at once. `stop_all()` pauses *first* (so a run can't spawn more), then cancels every pending/running job (`status = "cancelled"`); `cancel_job` does one. A running job learns it was cancelled because `executor.run(should_stop=…)` asks `job_svc.should_stop(job_id)` (a fresh status read, or paused) before every step and raises `JobCancelled` (carrying the steps done); both drains then call `mark_cancelled`, and `mark_completed`/`mark_failed` never overwrite a `cancelled` row. A step already running is not interrupted. `claim_pending` is an atomic conditional UPDATE. `WorkflowJob.trigger_detail` (`{changes: [{field, before, after, watched}], caused_by: {job_id, workflow} | null}`) says what started a run; `RecordService.update` computes `changed` from the stored values on both sides (never from the response form with its derived `resolved_filename`, which once made a workflow watching a file field re-trigger itself on every save), and `WorkflowContext.job_id`/`workflow_name` become the `_cause` passed to `record_svc.update/add` so a chained run can name its parent. `WorkflowContext.job_depth` must be passed by every drain (the CLI's once forgot, so chains never hit `MAX_JOB_DEPTH`). Frontend: `StopAutomationDialog` is the one confirmation; workflow runs and the pause show in the shared status bar (below); `RunSummary` shows what changed and the chain; `JobsTable` has a per-run cancel.

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
| `civex.parse_table` | Parse delimited bytes (CSV, TSV, ...) into a DataFrame; `delimiters` lets one step read several kinds |

**Writing records from a plugin.** `RecordService.update` (and so `WorkflowContext.update_record`) **replaces** a record's whole data with what it is given, so a plugin passing only the fields it knows erases the rest: `civex.upsert_records` once reduced records with 58 fields (a file, 49 computed values) to its table's 9 columns. Use `WorkflowContext.patch_record(id, fields)`: it reads the record fresh, merges only `fields`, and writes nothing when they already hold those values (no history, no triggers, not listed as touched). An absent value is left out of `fields`; it never clears anything. `upsert_records`, `save_field` and `save_fields` use it; `match_files_to_records` merges by hand.

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

The schema page (`pages/SchemaDetailPage.tsx`) is a compact header over tabs held in the address (`?tab=`): Fields (`SchemaFieldsSection`), Naming (`NamingSection`), Automations, History (delete is in the page's actions menu). Records are browsed from Collections, not from here.

Settings is a set of sub-pages, not one scroll: `pages/settings/SettingsLayout.tsx` is a section list plus an `<Outlet/>`, with routes `/settings/<appearance|database|storage|recently-deleted|map|advanced>` and `/settings` redirecting to Appearance. Settings > Storage (`components/settings/storage/StorageSettings.tsx`) has Volumes / Collections / Tasks tabs (Tasks = `TasksTab`: two cards, **Move files** (`NewTransferModal`) and **Clean up unused files** (`CleanUpDialog`), above the list of moves (`TransfersTab`); the old `?tab=transfers|maintenance` addresses still open it). `CleanUpDialog` looks (a dry GC run) as soon as it opens, says what it found in plain words, and one button deletes exactly that; it is the one clean-up UI, opened from Tasks (every volume) and from a volume page's *Unused* row (`volume` set, so `POST /store/gc` / `GCService.run(volume=)` / `civex store gc --volume` only touch that volume, and leave abandoned-upload scratch files to a store-wide pass), with the tab and a volume filter held in the address (`?tab=collections&volume=archive`). A volume's own page is `VolumePage` (`/settings/storage/volumes/:name`, a routed page outside the Settings layout; the volume row is a link to it): it pivots the same collection-by-volume data (`useAllCollectionStorage`) to show which collections are on the drive, plus the volume's `unused_*`/`history_*` bytes (from `FileReferenceRepository.surplus_by_volume`, merged into `GET /store/volumes`) and the moves involving it (`TransferCard`, shared with the Tasks tab). The list and the page share `VolumeSpace` and `useVolumeActions` (edit/remove/adopt/queue and their dialogs), so neither has its own copy. Above the tabs `StorageAttention` lists what needs a look, built by `hooks/useStorageAttention.ts`, the single place that decides what counts (unreachable volume holding files, low space, a move running/paused/interrupted). Where a collection's files are comes from one rule: `FileInfoService.all_collection_storage` (`FileReferenceRepository.volume_breakdowns`, catalog only) behind `GET /store/collections[/{id}]` and `civex store collections`; the single-collection answer is the bulk one for one id. `SpreadBar` and `utils/collectionStorage.gatherPlan` are the shared bar and "gather onto where?" rule used by the collection page and the Collections tab. The Collections tab is the one place homes are assigned (per row, or in bulk; `?focus=<collection id>` opens it filtered to one); a collection page's own Storage tab (`CollectionStorage`, `CollectionFileLocations`) is a read-only report (where the files are, which drive to plug in, where new files go) whose "Change"/"Gather" actions are links into Settings, so there is one copy of that logic. There is deliberately no Storage item in the sidebar; instead a running move shows live in the bottom status bar (see **Status bar** below).

Pins, recents and the Ctrl+K palette are per-browser (localStorage, `utils/pins.ts` + `hooks/usePins.ts`; there are no user accounts). A pin's `NavTarget` is built in `utils/navTargets.ts`; a pinned saved filter's live count is `hooks/useViewCount.ts` (keyed under `records`, so any record edit refreshes it).

On the record page, `RecordFieldGrid`'s `FileControl` attaches at once: `FileDropZone` (`components/ui`, the one file chooser, shared with `DynamicField` and the workflow run dialog) hands the files over, `utils/fileChecks.ts` refuses a wrong type or oversize file *before* upload, `useFileUploads` uploads, and the record is saved straight away (so workflow triggers on the field fire on upload). The only confirmations are for a file going: removing one, or replacing a single-file field's current one. A removed file's bytes are left to `gc_service`. Running a workflow is a visible button in the record page header (`components/workflows/RunWorkflowButton`: one workflow is one button, several are a menu); one that takes no files starts at once with a toast offering **View run**, and `WorkflowRunModal` opens only for `files` inputs and never shows the record ID when opened for a record.

**Creating records.** A record's explorer (`RecordsExplorer`) builds one **New** menu: the listed schema, then, inside a record, every child schema of that record's own the collection allows (`childStarters`, so a record with none yet can still get its first), else the top-level starters; each goes to `NewRecordPage`, whose **Add and add another** saves and stays on a blank form (`round` remounts the fields; a parent fixed by the list is kept).

**Lists held in the address.** `useListParams` keeps search, filters, sort, page and size in the query string. `Pagination`'s `onPageSize` must change the size *and* return to page one in ONE call (the list setters already do): React Router's functional `setSearchParams` is not queued, so a second call in the same event starts from the old address and undoes the first (a `onPage(0)` after `onPageSize` is what once made the Rows menu do nothing). `DataTable` takes `dense` for scan-heavy lists; the runs table uses it with `selection` for bulk re-run (`POST /jobs/rerun`, one request) and a `workflow` filter (`GET /jobs?workflow=`, exact name).

**Status bar.** The bar at the bottom of every page is generic: `components/status/TaskStatusBar` draws any list of `BackgroundTask`s (`utils/backgroundTasks`: title, optional progress bar, detail, note, actions that are buttons or links, an optional `overlay` for a dialog) and knows nothing of what they are. Each kind of work is a *source* hook in `hooks/tasks/` that turns its own state into tasks (`useMoveTasks`: the running move with progress, speed, ETA and Pause, one waiting for a drive, or how many wait; `useAutomationTasks`: the pause, with Resume, or runs busy for `SHOW_AFTER_MS` with how many wait, a batch progress bar once there is more than one run, and Stop), and `hooks/useBackgroundTasks` lists them. To show another kind of work, write a source and add one line there. Runs go one at a time, so the bar never says how many are "running".

**Filtering runs** reuses the records' filter, not a copy. The wire format and `parse_filter_tree` are `domain/filters.py`'s; the run fields are declared once in `domain/run_filters.py` (`RUN_FIELDS`, served by `GET /jobs/filter-fields`; `parse_run_filter` checks fields and operators, no `schema`). `job_repo._tree`/`_condition` compile a tree onto `workflow_jobs` columns (error kind/step via `error_details` JSON), and list, count, `ids_matching` (bulk re-run by `filter`), `failure_groups` and the UI all take the same `filter`. Frontend: `JobsTable` renders `FilterControls`/`FilterBuilder` over `utils/runFilter.runFilterFields` (a `FilterableField` with `ownerless` and per-field `operators`, so no schema heading and no `schema` on conditions); the old `status`/`trigger`/`workflow` params are read as a filter (`legacyRunFilter`). `FailureGroups` is the triage panel. No migration was needed.

**The batch tracker** (`useAutomationTasks`) reads `batch` from `GET /automation`, counted by `job_repo.batch_stats` from existing timestamps: every run queued while the queue was non-empty since it last emptied (a run finished after the batch's earliest member was queued belongs to it). Failures count as done. It shows a bulk start at once (a single run only after `SHOW_AFTER_MS`), and when a batch ends with failures leaves a notice (counted by `jobs/count`) until dismissed. Mutations that start runs refresh `['automation']` straight away (`refreshRuns`), because idle polling is 15 s.

**Runs that finished with problems.** `utils/runNarrative.runProblems` is the one rule: skipped rows plus `unmatched` and `ambiguous` step outputs. `JobStatusBadge` takes `problems` and shows an `attention` badge instead of a green one (list and run page); `RunSummary` opens with the problems and the files named. A new plugin output that means "left something undone" belongs in `runProblems`.

**Bulk run.** `POST /workflows/{name}/run-many` (`RunManyRequest`; one run per record, `skipped` with reasons like `/jobs/rerun`; 422 for a workflow with `files` inputs). `RecordsExplorer`'s `SelectionBar` takes an `actions` slot holding `BulkRunWorkflow` (`bulkRunnable` filters by `record_schema` and no files input); not offered for "all matching".

**A run's page** (`pages/JobDetailPage`) has `?tab=` tabs, Summary / Steps / Records touched (`components/jobs/RecordsTouched`, names live from `RecordName`). A link from a record page carries `?from=<record id>` (`JobsTable` with `recordId`, `RecordProvenance`): the page then builds its breadcrumb from that record's ancestors (`recordTrail`) ending on `/records/<id>?tab=runs`; without it the trail is `Runs ›`. Keep `from` when switching tabs or re-running. `civex.match_files_to_records` refuses to guess: files whose normalised keys clash within a run are all skipped and listed in its `ambiguous` output (a pattern like `sel_([0-9]{2})` once made 64 files into 47 keys and silently overwrote 17 contour files).

**Shift-click ranges.** Every list of checkboxes picks a range the same way: click one, shift-click another, and everything between them in the order shown takes the second box's new state. The logic is one hook, `hooks/useRangeSelect` (`onClick` on each box records shift, since a change event doesn't carry it; `rangeFor(id)` in the change handler returns the ids or null), used by `DataTable` (so every table with `selection`; an optional `onSetMany` makes a range one update, else it toggles each row that needs it), the column picker, the collection schema list (each box in the range goes through the parent/child rule) and the geometry-type boxes. A new multi-select should use it.

**Tab titles.** `Page` sets the browser tab (`hooks/useDocumentTitle`, `utils/documentTitle`): the current thing first, then what it sits inside, nearest first, then `civex` ("Sample 12 · Patient 3 · study · civex"). It is made from the page's text title, or else the last item of its breadcrumb trail, plus the earlier trail items; a page made of several areas passes `documentTitle` instead (Settings does, adding the Storage tab: "Tasks · Storage · Settings · civex"). The title goes back to `civex` when the page goes away.

**UI components and content rules** live in `frontend/UI-AUDIT.md` ("Component and content rules"): one component per concept in `components/ui/` (`Button`/`IconButton`, `Chip`, `SegmentedControl`, `ListButton`, `Card`, `DataTable`, `SortableList`, `TabNav`/`TabPanel` + `useTabParam`, `Disclosure`, `InfoTip`/`Tooltip`, `Subheading`). Don't write a raw `<button>`, `<table>` or `<details>` outside `ui/` (lint warns). Explanations are tooltips (`Page info=`, `Field info=`), not paragraphs; `Page meta=` is for facts only; big pages are tabs held in the address, never stacked collapsibles. Rows and cards are clickable as a whole (`DataTable rowHref`/`onRowClick`, `Card to`), and controls are at least 32 px.

**Navigation state.** Anything that is a place lives in the address: tabs (`useTabParam`, pushes history), the explorer (`schema`/`within`/`q`/`filter`/`sort`), and a simple list's search, dropdown choices, sort and page (`useListParams`, with `ListToolbar` above a `DataTable`; used by Runs and every History tab, namespaced by `ns`, replaces history). A record's Contains tab is the record explorer itself (`RecordsExplorer root=`), so descending the hierarchy never leaves the record page. Cancel and "done" actions use `useBack(fallback)` (a step back in history, else the fallback) instead of hard-coded list links, and a finished form replaces its own history entry. Runs filter by status, trigger and search and sort by column on the server (`GET /jobs`); every audit endpoint takes `action` and `sort` through one `AuditView` dependency.

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
