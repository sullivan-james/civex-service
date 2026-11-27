# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository. It holds the rules and traps that the code doesn't make obvious; for where a feature lives, search the code.

## Setup

Dependencies and the venv are managed by [uv](https://docs.astral.sh/uv/): it reads `pyproject.toml`, resolves against the committed `uv.lock`, and provisions Python 3.12 itself (`.python-version`).

```bash
uv sync --extra server --extra workflows --extra dev  # standard dev setup (== `make install`)
uv sync --all-extras                                   # every optional extra (== `make install-all`)
uv lock                                                 # re-resolve after editing pyproject.toml deps
uv run civex --help                                     # run inside the synced env without activating it
```

`make check`/`make secrets` also need the [gitleaks](https://github.com/gitleaks/gitleaks#installing) binary on `PATH` (not a uv/npm dependency).

## Commands

`Makefile` targets: `install`, `lint`, `format`, `format-check`, `typecheck`, `test`, `test-postgres`, `secrets`, `check` (everything CI runs), `pre-commit`, `serve`, `dev`, `docs`, `docs-build`, `clean`.

```bash
uv run civex init                 # create a _civex/ project in the current directory
uv run civex serve --reload       # dev server (== `make serve`)
uv run pytest tests/              # all tests (== `make test`)
uv run pytest tests/test_smoke.py::test_init_creates_civex_dir  # single test
make check                        # ruff format --check, ruff check, mypy, pytest: what CI runs

# Frontend (cd frontend/ first)
npm run dev                       # Vite dev server, proxies /api to localhost:8000 (== `make dev`)
npm run build                     # tsc + Vite build to frontend/dist/; also the way to type-check
```

The server serves the built frontend from `frontend/dist/`. In development run `civex serve --reload` and `npm run dev` side by side. PostgreSQL tests (`tests/db`, `tests/sync/test_postgres_authority.py`) run when `CIVEX_TEST_POSTGRES_URL` is set.

## Architecture

```
src/civex/
  cli/           # Typer commands: parse args → call service → format output
  domain/        # Plain dataclasses (DTOs), exceptions and pure rules; no framework dependency
  services/      # Business logic
  repositories/
    protocols.py # Protocol interfaces
    local/       # SQLAlchemy implementations; s3/ for the bucket store
  db/            # models.py (SQLAlchemy 2.0 ORM), engine/session, migrations
  plugins/       # runtime, launchers, host_api, registry, builtins/
  workflows/     # definition.py (YAML models), executor.py (Kahn's topological sort)
  server/        # FastAPI app factory, routers/ (one per resource)
  testing/       # shipped test harness (Projects, sync peers, scenarios, FakeS3); no pytest import
  config.py      # find_project_root(), load_config()
  context.py     # AppContext + build_context()/build_local_context()
```

### Layer rules (strict)

- `cli` → `services` via `AppContext`. Never touches repos or DB models directly.
- `services` → `repositories/protocols` (interfaces). Never imports from `cli` or `db`.
- `repositories/local` → `db/models`. The only layer that imports SQLAlchemy models.
- `plugins` → `WorkflowContext` only. Never imports SQLAlchemy or sessions.
- `domain` has no imports from the rest of civex.

### AppContext and the public API

**The service layer is the public Python API.** `civex.open(path)` returns the same `AppContext` the CLI and server build; it is a context manager (commit on success, rollback on error). There is no separate client or facade, so nothing outside a service reaches into its private attributes: a caller that needs something gets a public service method. Notebooks get typed tables from `AppContext.frame`/`rows`, which only build a `RecordQuery` for `FileAccessService.typed_rows`/`frame`: the export's own table (`table_rows`), not a second one. Guide: `docs/guides/python.md`.

`build_context(project)` wires all repos and services for one `Project` (`civex/project.py`). CLI commands call `get_ctx()` (`cli/utils.py`), `ctx.commit()` after mutating, then `ctx.close()`; errors print and raise `typer.Exit(1)`. The server resolves the project per request with `deps.current_project(request)`.

- **Settings are saved only through `ctx.config_store`** (`ConfigStore`), never by calling `save_config` from a service, so a hosted project can keep them elsewhere. Exceptions: the database-admin paths and the CLI.
- **Background hosts take a context factory** (`context.ContextFactory`). A route that queues background work passes `context_factory(ctx.project)` so it runs on the project the request was about.
- A new action gets a service method first, then both a CLI command and an endpoint calling it; neither holds rules of its own.

### Features and permissions

- `domain/features.py` names what a server offers (`LOCAL_FEATURES` for a local project). Only three places read it: `server/app.api_routers(features)` (whole routers), `deps.requires(feature)` on a route in a shared router (501), and `GET /api/status/features` for the frontend (`useFeatures`, `NavItemDef.feature`). Features that touch the server's own machine (`server_path_export`, `plugin_install`, `remote_dial`) are in `LOCAL_FEATURES` and left out by a host. **`RELEASES` is the opposite: off by default and not in `LOCAL_FEATURES`; only a host turns it on** (it gates the whole releases router, so off is a 404, and the app's Releases views). Adding one: a name in `FEATURES`, the router/route gated, `feature:` on its UI items.
- **Read-only routes may be served by a replica.** A route that only reads and tolerates lag takes `deps.get_read_ctx`, which uses `Project.read_engine` (read-only transaction, PostgreSQL only) unless `needs_primary` is set; anything that writes, or must see its own write, uses the primary context. Never write through a read context (`uses_read_engine`).
- `domain/permissions.py`: actions (`read`, `write_records`, `change_structure`, `add_files`, `delete_files` (`manage_files` aliases both), `delete`, `notes`, `views`, `manage_members`, `manage_devices`, `release`) over the project or collections, `read` included: **a collection without `read` is absent from every query** (`db/read_scope.install`, one session-level rule, so a new query needs nothing; the sync authority runs `unscoped` and asks `Permissions` itself) and a direct request for it is a 404. A new router about the whole project (storage, retention) takes `reads_whole_project()`; a new admin route takes `allows(ACTION)`. `Project.push_accepted` is the host's after-commit callback for a device push. `build_context` gives the same `Permissions` to every service and to the sync authority as its policy. **A new write path calls `self._permissions.require(...)` first, before anything changes** (bulk paths check every collection first). `RELEASE` (make, correct, withdraw, yank) follows `CHANGE_STRUCTURE` for a host that says nothing about it (`permissions.FOLLOWS`, as notes and views follow writing); stating or `lacking` it separates them. A new UI control consults `usePermissions`, and stays visible but disabled with the reason as its title.

### Data model

- Record `data` is a JSON/JSONB dict keyed by **field UUID**, translated to names at the service boundary (`RecordService._names_to_ids()`/`_ids_to_names()`). Everything above the service sees name-keyed data. Audit snapshots are also id-keyed.
- Field types: `VALID_DTYPES` in `schema_service.py` is the authority. A `formula` stores nothing (see **Formula fields**).
- `file`/`file_list`: `FileRef` dict(s) `{sha256, filename, size}`; bytes stored by content (`<sha[:2]>/<sha[2:]>`).
- `date`: ISO string at the precision written (`2019`, `2019-06`, `2019-06-14`); `domain/partial_dates.py`, mirrored by `frontend/src/utils/partialDates.ts`.
- `datetime`: always a UTC ISO string. `RecordService.add`/`update` normalise via `_normalise_datetimes()`, reading an offset-less value as wall time in the field's `timezone` restriction, else the collection's, else UTC; DST gaps/overlaps are rejected; `update` skips echoed-back values. Logic in `domain/timezones.py`, mirrored by `frontend/src/utils/dates.ts`, which works to the second: datetime inputs need `step={1}`.
- `geo`: GeoJSON geometry (WGS84, `[lon, lat]`), validated by `domain/geo.py` on every write; text forms via `geo.parse_text`/`geo.to_text`. Mirrored by `frontend/src/utils/geo.ts`; both are tested against the same table of examples.
- `float` with `unit`: one unit per field, every stored value in it. The service never converts; `domain/units.py` (mirrored by `frontend/src/utils/units.ts`) converts only at entry edges. Changing a field's unit is a relabel.
- `reference`: the UUID of another record; target schema via the `schema` restriction.
- Schema inheritance: `SchemaService.collect_fields()` resolves it; parent fields follow own fields.
- **Python ↔ TypeScript mirrors** (`partial_dates`, `timezones`/`dates`, `geo`, `units`, `naming`) must change together.

**Text search matches values, never the stored JSON.** `RecordService.text_search` is the one rule for which fields are searched and `record_repo.text_match` the one predicate (EXISTS over `json_each`/`jsonb_each`, LIKE wildcards escaped, file names, id prefixes of ≥ 4 hex digits). Never search with `cast(data, String)`: it matches field ids and file hashes.

### Records

- **`RecordService.update` replaces `data` whole.** Code that changes some fields uses `patched_data`/`patch` (plugins: `WorkflowContext.patch_record`), or it erases the rest.
- `_check_references`: a reference target must be live, in the same collection or a `global` one. A collection holds records of every schema (no per-collection schema list).
- `_check_unique` is the single uniqueness enforcement point (scope: same collection, same parent, live records of exactly that schema; a key with any blank field doesn't constrain). Keys are own field ids (`schemas.unique_keys`), defined only by `SchemaService.set_unique_keys`. Every path that brings records back goes through `_restore_clashes`. Not enforced by the database.
- **Moving records**: `plan_move`/`move` is the one rule. **The database holds a child to its parent's collection** (`fk_records_parent_same_dataset`, deferred to commit).
- **Bulk edit**: `plan_bulk_edit`/`bulk_edit`/`bulk_edit_chunks`; each record takes all changes or none, through the same checks as `update` (`_checked_update`). The plan is worked out over the set (`RecordRepository.field_rows`, one statement) and the checks run once per case (`_edit_case`), not once per record; don't turn it back into a per-record walk.
- **An update checks only the values it changes** (`record_service._changed_values`, the one "unchanged" rule behind restrictions, references and unique keys), and changing a rule never re-checks stored values: a record breaking a tightened rule still takes edits to other fields. Sync's `check_incoming` uses the same rule. The field editor warns instead (`QualityService.check_field`).
- Fields are deleted softly (`fields.deleted_at`): `SchemaDTO.fields` holds only live ones, records keep their values, and `update` carries them across a save. `_ids_to_names` leaves out deleted fields' values and any key naming no field of the kind (one would make a bundle or release unreadable). Field names are unique among live fields only.
- `_strip_derived_file_keys` (`DERIVED_FILE_KEYS`: `location`, `resolved_filename`) removes response-only keys on write, because the UI echoes values back. `_attach_file_locations` runs in `_attach_reference_labels` (API reads), **never** in `_with_names` (audit snapshots), so a location is never frozen into history.
- **Set-level, not per-record.** Planners and bulk paths look things up together, and tests hold their query count constant whatever the size. Don't add a per-record lookup in a loop.

### Names, labels and templates

- Schemas and fields have a `name` (machine key, slug `^[a-z_][a-z0-9_]*$`, validated on create/rename only) and a `label` (display; `display_label` derives one). The UI calls them **Key** and **Name**; never show "label" as a UI word.
- `domain/templating.py` is the one string builder (`{field}`, `{field:spec}`, `{ref.field}` one hop through a `reference` field). Record names (`display_template`) and file names (`filename_template`) both use it. `SchemaService._rewrite_templates` keeps templates in step when fields are renamed or deleted, and logs each rewrite.
- `GET /files/{sha256}` is content-addressed and record-agnostic; it takes `?filename=`.

### Field restrictions

Declared once in `domain/field_descriptors.py` (`FIELD_TYPES`); `VALID_RESTRICTION_KEYS` derives from it and `GET /schemas/field-types` serves it to the UI. Values are validated only in `_check_restrictions()` (`record_service.py`). Adding a restriction: a descriptor entry, its check in `_check_restrictions()`, and only if no existing control fits, a control in `RestrictionControls.tsx` registered in `controlRegistry.ts`. Display (views) is kept apart from validation: don't put view settings in `restrictions`.

### History (audit log)

- **History is complete, and `tests/services/test_audit_replay.py` holds it**: replaying each thing's entries must reach the database. Anything that changes a schema, field, collection, view or record writes an entry, including side effects on other things. Cascades (a schema/collection delete or restore) write an entry per record (`services/cascades`).
- Storage: `audit_diff.stored_form` is the one rule (whole for create/delete, a `delta` for edits). **Read an entry only through `audit_diff.entry_snapshots`**, never the columns. `diff_entry` is the one place a diff is made, `AuditService` (`ctx.history_svc`) the one place it is served. Entries from older releases (whole snapshots, name-keyed) still read the same way; `tests/db/test_upgrade_from_releases.py` opens real old databases; add a fixture per release.
- `audit_log.local_seq` is write order (never wall-clock time or `rowid`). `op_id` groups one action's entries; `batch_id` groups bulk operations into one Activity event (`LocalAuditRepository.batch`, which joins an enclosing batch).
- Revert is records-only and applied only through `RecordService.update/delete/restore` (`plan_revert` is the one rule; a bulk edit is undone whole with `revert_batch`/`revert_batch_chunks`: planned with the same rule (`_plan`) but over a chunk as a set, and saved through `RecordService.put_fields_back`, the bulk edit's chunk save; don't turn it back into a per-entry `plan_revert` + `update` walk. A field edited since is a conflict (left unless forced); other fields of that record are still put back).
- Restore: `RecordService.restore_plan` is the one "can this come back" rule. A delete stamps everything it cascades to with one `deleted_at`, and restore uses it to bring back only what was deleted together. Deletes must be undoable in parts (`only_this`, `with_parents`, `restore_records`).
- Purging a record deletes its history and leaves one tombstone (`audit_diff.tombstone`).
- History filters reuse the records' filter machinery (`domain/filters.py`; `AUDIT_FIELDS`), as runs do (`RUN_FIELDS`); don't write a filter system of your own.

### Object stores and drives

- `ObjectStore` (what every file-handling service sees) and `VolumeStore(ObjectStore)` (drives as places; only `StoreService`, the transfer engine and the folder-making parts of `FileAccessService` need it). `context.make_store` picks drives or an S3 bucket from the settings; a bucket is one always-online volume. Only `BucketService` switches between them, and only while the place being left holds no files.
- Where files are is answered from the `stored_objects` inventory (one row per copy), never by listing a bucket or walking a drive. A query asking whether a file is here joins `inventory.stored_files()`.
- **Each record's file points at exactly one copy** (`file_references.volume`), kept right in three places only (citing a file, recording a copy, removing a copy). `_existing_copy()` is the one dedup rule; `transfer_engine.plan_steps` + `placement.file_step` the one move rule behind previews, the move dialog and the engine.
- Volume definitions live only in `config.toml` (`[store.volumes.<name>]`); the DB holds only the inventory. `volume_status(name)` is the single "can this volume be used?" decision. `StoreService.inspect_path()` the single "can this folder become a volume?" rule. A missing volume root is never created on demand (except a relative path inside the project), and reconcile skips unreachable volumes, so an unplugged drive never loses its inventory.
- Anything touching a volume outside the project goes through `fs_locations.guarded()`, so a dead mount becomes `offline` instead of freezing a request.
- **The transfer engine's per-file order is the whole safety argument; don't reorder it**: copy to scratch on the target while hashing (must match), optional read-back, atomic rename, record + commit, *then* remove from the source. Resume rediscovers work from the source's contents (no cursor). Transfers run one at a time under the store's PID-owned transfer lock; GC takes a mutually exclusive lock. `save_config` is atomic because transfers rewrite config.toml while requests read it.
- SQLite uses `busy_timeout`; WAL is deliberately not used (sidecar files break copying the DB and it is unreliable on network/WSL drives).
- A deleted record's files are outside placement policies (storage report, moves, sync downloads count live records) but not safety ones (clean-up keeps them, emptying a drive moves them).
- The app says "drive", never "volume"; code, CLI and server messages say "volume".

### Files by name and folder

- `FileAccessService` turns a `FileSelection` into a plan, then optionally an export. **Plan before action**: `plan()` makes nothing and says what is unreachable; `export()` refuses unless `allow_partial`.
- **One path rule** (`domain/file_access.py`): the names of the records above a file, then its `resolved_filename`; clashes get a short id (`folder_segments`, `file_names_in_folder`). Files and tables get their folders in the same pass. Don't write a second path rule.
- It never searches or walks: sources come from `VolumeStore.path_on`, records in pages; `test_a_big_selection_costs_a_fixed_number_of_queries` holds it constant.
- Exports: hard links where possible, else copies; **linked files are read-only** (they *are* the stored file). **No symlinks.** Anything that removes or replaces a stored or exported file goes through `file_modes.remove`/`replace` (Windows refuses to delete read-only files). An export folder is ours only if it has `.civex-export.json`; removal deletes exactly the marker's files.
- Tables: `domain/tables.py` is the one rule for formats and cells; `table_rows()` the only row builder; `services/table_files.write_table` the one writer; `services/archive.build_download` the one "hand it over" rule (zip or lone table).
- `domain/file_access.place_of` is the one rule for where a file is; `FileAccessService.chosen` the one rule for which files a person picked.
- A saved view is not an export definition, and there is no separate "export preset" concept.
- Exports offer **Save to a folder** (any folder, picked with the app's folder browser) or **Download a zip**; how a folder is made (links or copies) is never asked. **Change storage drive…** is housekeeping, never beside Export.
- **The files list is answered from the database, never from a plan.** `FileAccessService.listing`/`chosen` read only the records the catalog says hold a file, in one statement whatever the size (`RecordService.held_files`); planning every file of a selection took minutes at 100k+ records. A plan of files stays *lean* (`_lean`) unless it makes a table.

### Sync

Star topology: a project follows one **authority** (`civex serve` with `[sync] serve = true`). Devices push their `audit_log` entries; the authority merges, numbers and serves a feed. A project serves or follows, never both (`SyncService._one_role`).

- **Conflict policy**: the authority's value stays; the losing value is kept in `sync_conflicts` on the device whose change didn't go in. Edit-vs-delete keeps the record. Merge is three-way per field (`domain/merge.py`). **Data rules are soft**: `RecordService.check_incoming` returns `unfit` findings (required field empty, `RuleBroken` restriction) instead of raising; the record is taken in (bulk path included, no extra queries) and the answer carries one `unfit` item per field (status unchanged). New records are judged in full, edits by changed values plus required fields they empty. The flag is the authority's judgement, computed from its rules and data: a copy shows it and clears the pusher's `unfit` item only when level with the authority (nothing unsent, feed read to head; `_settle_flags`), judging the records the push answered or the pull brought (all flags if a schema/field came in), so a fix or delete elsewhere clears it on the next sync and a stale local schema never does. The data-quality check lists the record for everyone. Locally saved data can arrive flagged: the authority's rules decide. File and geo restrictions stay hard refusals for now. A value that is not of its field's kind (a `ValidationError` that is not `RuleBroken`, incl. a wrong-kind value or malformed date), a taken key or a missing reference still refuse.
- **The authority holds an incoming change to what a local edit must pass** (`domain/sync.problem_with` for shape, `RecordService.check_incoming` for records, `ProjectRules` for cross-kind rules after writing). One odd change is refused by itself, never failing the push.
- **One action is taken whole** (entries sharing `op_id`): never split one when sending; the authority settles it in one savepoint, or keeps / puts back the whole thing.
- **Apply the authority's entries for a thing in order** (`SyncService._replay`). Applying an older state over a newer rolls it back; `tests/sync/test_convergence.py` exists for exactly this (`CIVEX_SYNC_SEEDS=300` runs more).
- Peer routes commit **before** responding (`Depends(get_ctx, scope="function")`), and `push` takes the feed lock first. Don't change either.
- **Files and data converge separately.** A change is never held for a file, and nothing about files owed is stored: it is worked out each time from `file_references` and the authority's answers. Don't reintroduce either.
- Deletes use one stamp for the entry and `deleted_at`, so every device stamps identically; deletes/restores don't bump `updated_at`.
- **Releases are never synced** (protocol 6): `NOT_SYNCED_KINDS` is outside `ENTITY_ORDER`, the authority refuses a pushed one (`REFUSAL_NOT_SYNCED`) before anything else, feed/snapshot/counts and a device's pending/unsent count leave them out (`sync_repo._SYNCED`), and release-owned `file_references` are not files a device sends or fetches. Protocol 3-5 peers are answered, never errored (empty `/snapshot/release`).
- **What travels is `WIRE_FIELDS`**, held by `tests/sync/test_wire_shapes.py` and `wire_shapes.json`. Changing it means raising `PROTOCOL_MAX`, recording the new shape and serving the previous version through an adapter in the peer router. Compatibility is the protocol range alone; civex versions are shown, never compared to refuse. A kind or field newer than a device's protocol is held back by `KINDS_SINCE`/`FIELDS_SINCE` in the peer router's adapter (`kinds_for`/`snapshot_for`/`entry_for`), never in the core.
- `audit_log.apply_state` is `applied`, `held` (this device has an unsent change to that thing) or `superseded`.
- Security: devices join by one-time invite or approved login and sign in with an Ed25519 key (`civex/keys.py` is the one crypto module); only `join` and `session` take no token. On a serving project remote hosts reach only `/api/sync/v1/`; an authority on a network runs `civex serve --sync-only` behind the proxy. Devices connect only over `https://` (or `http://` to loopback; `domain/hosts.is_loopback`). Device id and keys live in `~/.civex/sync.toml`, never in the project folder.
- `ssh://` addresses are HTTP through an SSH tunnel, not a second transport.
- Workflows and plugins are shared through the library, never synced, and **nothing is written into `_civex/workflows`/`_civex/plugins` by sync or publishing** (describing a plugin runs it). The authority checks text without running it.
- Failures go through `domain/sync.plain_failure` (plain words; technical text in `detail`). A sync failure is not toasted; the status bar holds it.
- A new sync scenario goes in `civex.testing`, with a thin wrapper test in `tests/sync`. `tests/sync/test_invariants.py` must keep passing.
- **Hosting surface for the database.** `civex.db.migrate` is public to hosts: `ensure_schema_current(engine)` migrates, `schema_status(engine)` only reports (`SchemaStatus`) and honours a `search_path` on the engine. A host that wants to refuse a stale tenant calls `schema_status`, never a migration attempt. A host that wants a PostgreSQL `records` table (made with partitioning off, or before it existed) hash-partitioned calls `convert_records_partitions(engine, n)` and reads the layout with `records_partitioning(engine)`; hosts never import `civex.db.partitioning`.

### Formula fields

A `formula` field is **worked out when read, never stored**: nothing in `records.data`, history, sync snapshots or bundle records. `domain/formulas.py` is the language, parsed with Python `ast` against an allow-list (no attributes but one-hop `link.field`, no subscripts, lambdas or dunders; size limits) and never `eval`ed; `compute` returns `(None, why)` rather than raising. `SchemaService._validate_formula` checks names, kinds and cycles; a rename rewrites formulas that read the field, and deleting a field a formula reads is refused. **One place works them out**: `RecordService._formula_results` (batched with `_derived_values`); API reads carry them in `derived`, never `data`, via `_attach_formulas` (inside `_attach_reference_labels`, so never in an audit snapshot). Writes drop formula values; filters, sorts, summaries, unique keys, search and name templates refuse or leave out formulas (SQL can't see them).

### Summaries and charts

- `RecordService.summarise(query, SummaryRequest)` groups exactly the records a `RecordQuery` lists; `domain/summary.py` is the request, the one written form (`parse_group_by`/`parse_measure`, shared by CLI, API and address) and the result, whose rows carry `where` (the filter tree listing that group, so drilling in is the filter's own rule). Which measures and groupings a type allows is `FieldTypeDescriptor.measures`/`grouping`/`buckets`, never a second table. `summary_sql.py` is one statement on both dialects (`test_one_statement_however_many_records`). Maps: `RecordService.points`.
- **A chart is one definition** (`domain/charts.py`, `parse_chart(s)` the one check), **one renderer** (`components/charts/ChartView`), **one service call**, used by the explorer, a kind's Charts tab and the Analytics page. A chart says nothing about which records: it counts what it is shown beside. A kind's charts (`schemas.charts`) are part of the schema's snapshot, so they are audited, synced, bundled and kept in step on field rename/delete (`_rewrite_charts`). The Analytics page is one synced thing per project (`dashboards`, fixed `DASHBOARD_ID`); `DashboardService` leaves an existing card alone even when its field is gone (it shows a `problem`).
- **One filter, one tree** (`utils/chartFilter`, the one rule): clicking a bar adds or removes its `where` in the explorer's own filter tree, so bar picks and builder filters are the same thing. A chart's bars are lit, and its term left out of what it counts, only while the tree holds one simple choice about its field; anything else is left as written and never rewritten. `utils/summaryChart.buildSummaryChart` is the one rule for a chart's form.
- No charts by default and none suggested from the data (tried and removed). Changing a kind's charts in a list saves for the kind at once; there is no per-person set.

### Releases (frozen, citable copies)

**Releases belong to a host, never a personal device, and are never synced** (`features.RELEASES`, the `RELEASE` permission, protocol 6): the desktop has no release commands or pages at all (`civex release` only says so; old local releases are simply not shown); `GET /releases/{name}/bundle` streams one bundle with the files (`ReleaseService.full_bundle`) and `civex clone <url> --release NAME` reads it into a new, read-only (`[project] read_only`) project. `ReleaseService` makes a small bundle of **records** plus `release.json` and `CITATION.cff`. **Files are referenced, never copied**: a release is a third owner in `file_references` (`release_id`), so GC, "used by", pointers and moves treat it like any owner, with no special case; making one is catalog-only and asks no drive. Per-record hashes are one definition (`rules.record_hash`, keyed by field id, stored live fields only), so a rename changes no record; **the content hash is over contents, never zip bytes**. A release is **never deleted**: `correct` changes only `METADATA_FIELDS`, `withdraw` keeps data, `yank` (irreversible) disowns files and leaves a citing tombstone. **What changed since is a comparison of the data, never history** (`compare`, paged). Getting files out goes through `FileAccessService.with_records(FrozenRecords)`, so the one path rule, plan and export apply. Code (workflows, plugins) is left out unless `include_workflows`. Chosen records come with what is inside them (`ReleaseScope.below`).

### Data checks

`QualityService` says what in the records a `RecordQuery` lists needs a look by **asking the rules that already exist, never a copy of them** (`restriction_problem`, `key_duplicates`, `reference_problems`, `place_of`). One walk (`_walk`) is behind `check`, `records_with` (what the explorer ticks and hands to bulk edit) and `check_field` (rules as they would be); a fixed number of queries per page. Not in `civex doctor` (it would read every record).

### Notes on records

`domain/notes.py` + `NoteService`: notes are their own kind (`note`, `record_notes`), in **threads one level deep** (a reply to a reply joins the thread). Resolving always acts on the thread's first note; a reply to a resolved thread reopens it in one action. Deleting a thread's first note hides its replies without stamping them. Each write is a history entry; a record purge takes its notes and their entries. Open notes are the filter field `@open_notes` and are read set-level (`open_notes_of`). The one place to see everything open is All records filtered with every kind (`schema=*`). There is no review status (a sign-off is a choice field). Deliberately not local: mentions, notifications, assignment, inboxes, unread state, reactions.

### Bundles

`BundleService` exports/imports a zip of schemas, collections, records (`records.jsonl`), optional files, workflows and plugins. Import writes each record through `RecordService.add(record_id=, ...)`, so validation, references, uniqueness, history and sync all apply; files go through `FileService.store`; workflow/plugin members pass `member_name_problem`. Not carried: history, views, saved exports, settings. In the app a bundle is "a copy for another project": "Export" on screen only ever means files and tables for use outside civex (code, CLI and API keep "bundle"). Copies are written straight into a folder of this computer through `FileAccessService.save_to`, the one rule, not through the browser.

### Retention

`RetentionService` runs only when started by a person or cron (no scheduler) and counts first (`dry_run` default). History pruning keeps entries about anything currently deleted and each thing's first and latest entry. Unreferenced files afterwards are `GCService`'s job.

### Workflows and plugins

- `executor.run()` commits nothing; both drains run it inside `AppContext.all_or_nothing()` and commit once, so a failed run keeps none of its writes.
- **What a plugin may ask of civex is one table**, `plugins/host_api.HOST_API`; a new host function is an entry there plus the SDK `Ctx` method (`test_host_api` holds the docs table to it).
- Every plugin, built-in or not, runs over the SDK wire protocol; a tier is only a `Launcher`. Built-ins get an SDK `Ctx`, never a `WorkflowContext`. Custom plugins live in `_civex/plugins/*.py`, define `class Plugin(civex_plugin_sdk.Plugin)`, and declare their contract in the PEP 723 header (`[tool.civex]`).
- Files go by path in one run folder outside the project; `host_api.inside_run` refuses paths outside it.
- Triggers: `trigger_for_record()`. On create, `record_updated` fires only with non-null fields in `changed_fields`. `changed` is computed from stored values, never the response form (derived `resolved_filename` once made a file-watching workflow re-trigger itself on every save).
- Manual inputs: `initial_outputs["__input__"]`. A Files step set to `source: run` is asked for by its step id: the executor fills its optional `provided` input from `__input__.<step id>` (uploaded `FileRef`s, or `{folder, glob, subfolders}` read by the step through the explicit-only `store_folder` host function, gated by `features.SERVER_PATH_IMPORT`, off on a hub). `workflows.definition.run_inputs(wf)` is what a run asks for.
- **Step versions** (`workflows/upgrades.py`): built-in ids carry a version (`civex.save_records@1`; none = version 0, the pre-versioning steps). A contract change (id, config keys, inputs/outputs) needs a new plugin id, a bump of `upgrades.LATEST`, an `@upgrade(base, from_version)` function that rewrites the raw workflow dict, and golden pairs in `tests/workflows/test_step_upgrades.py`. `load_workflow` upgrades a file on read and rewrites it (old text kept as `<name>.yaml.bak`, atomically, never overwritten); `parse_workflow` upgrades in memory (shared/pasted/saved text). A step version beyond `LATEST` raises `NeedsNewerCivex`. A setting `{from_field: x}` is resolved by the executor from the record (`resolve_from_fields`).
- `AutomationConfig.paused` is the kill switch; `WorkflowJobService` is its one decision point. Every drain must pass `WorkflowContext.job_depth` (chains stop at `MAX_JOB_DEPTH`).
- `civex.save_records` (files) refuses to guess: clashing keys are skipped and listed as `ambiguous`.
- `utils/runNarrative.runProblems` (frontend) is the one rule for "finished with problems"; a new plugin output meaning "left something undone" belongs there.

Built-in steps (`plugins/builtins/`, auto-discovered), in the app's three groups: Bring in: `civex.files@1`, `civex.table@1`; Work out: `civex.value_from_filename@1`; Save: `civex.save_records@1`, `civex.set_fields@1`.

## Frontend

React + TypeScript (Vite), React Router, TanStack Query v5. `api/` typed fetch wrappers, `hooks/` query hooks, `pages/` one per route, `components/`. Component and content rules are in `frontend/UI-AUDIT.md`.

- One component per concept in `components/ui/` (`Button`, `DataTable`, `TabNav`, `Disclosure`, `InfoTip`, `CheckRow`, `ProgressBar`, `FileDropZone`, …). Don't write a raw `<button>`, `<table>` or `<details>` outside `ui/` (lint warns). Reuse and extend existing components (explorer, `DataTable`, `useBulkSelection`, `useRangeSelect`, `ColumnPicker`, `FilterControls`) rather than building parallel ones.
- Few words: explanations are tooltips, not paragraphs. Rows and cards are clickable as a whole; controls are at least 32 px.
- **Anything that is a place lives in the address**: tabs (`useTabParam`), the explorer's state, list search/filter/sort/page (`useListParams`). Cancel/done use `useBack(fallback)`.
- **React Router's functional `setSearchParams` is not queued**: two calls in one event and the second undoes the first. Change several params in one call (e.g. `Pagination`'s `onPageSize` changes size and page together).
- **Served under a host**: never write `'/api/...'`; build URLs with `utils/host.apiUrl`. Browser-stored keys go through `utils/host.projectKey`. A new extension slot (`utils/slots.ts`) is a promise to every host: prefer data and links.
- `DynamicField` is the single editable input for any field type. File uploads go only through `hooks/useFileUploads` (batched `PUT /files/batch`; never a request per file).
- The status bar is generic: each kind of background work is a source hook in `hooks/tasks/`, listed in `hooks/useBackgroundTasks`.
- `JobsTable` owns its own pagination; don't duplicate it in parent pages.
- **Shift-click ranges** in any checkbox list use `hooks/useRangeSelect`.
- Permissions and features: `usePermissions`/`useFeatures` assume everything until the server answers, so nothing flickers.
- **The explorer** (`components/explorer/RecordsExplorer`): the records are the page; charts are a panel beside them (`SplitPane`), never a peer in a mode switch. Files (`show=files`) and problems (`show=checks`) are views of the same query, reached from menus. **All kinds** (`schema=*`) lists every kind: only `@open_notes` filters and `META_SORTS` sorts are allowed there, field conditions are refused ("choose a kind of record first"), and there are no charts. A record's page is the collection's explorer in its `inside` form under the fields, not a second explorer and never a link to the same records elsewhere.
- Ask AI's read tools build a `RecordQuery` and call the explorer's services: there is no AI query language, and a refused query comes back as `tool_error` for the model to correct.

## Key files for common tasks

| Task | File |
|---|---|
| Add a CLI command | `src/civex/cli/<group>.py` + register in `src/civex/main.py` |
| Add business logic | `src/civex/services/<name>_service.py` |
| Add a DB table | `src/civex/db/models.py` + `repositories/protocols.py` + `repositories/local/` + a migration |
| Add a built-in plugin | `src/civex/plugins/builtins/<name>.py` + `docs/_prose/plugins/<slug>.md` |
| Add a container-tier plugin starter | `plugin-templates/<language>/` (see `plugin-templates/r/`) |
| Add an API endpoint | `src/civex/server/routers/<resource>.py` |
| New domain types | `src/civex/domain/dtos.py` or `domain/exceptions.py` |
| Add a frontend API call | `frontend/src/api/<resource>.ts` + `frontend/src/hooks/use<Resource>.ts` |

**Migrations**: a committed migration's parent never changes (`tests/db/test_migration_parents.py` / `migration_parents.json`); join side-by-side migrations with a merge migration. A batch rebuild of `audit_log` drops the `local_seq` trigger. **Never edit a migration after it has run on any machine** (a database stamped past it then lacks the change, and Alembic can't tell): add a new revision. `civex doctor --repair` / the Health page (`services/health_service.py`) is the safety net for a database that lacks tables or columns, not a licence to edit.

## Documentation

The docs site is under `docs/` (MkDocs Material). Some pages are generated; editing them directly loses the change:

| Path | Source of truth |
|---|---|
| `docs/reference/cli/*` | Generated from `civex.main:app` by `docs/_gen/_cli.py` |
| `docs/reference/http-api.md` + `openapi.json` | Generated from `create_app().openapi()` |
| `docs/reference/plugins/*` | Generated from the plugin registry + `docs/_prose/plugins/*.md` |
| everything else under `docs/` | Hand-written |

- New CLI command: prose help only; no indented line art, never `\b` escapes.
- New HTTP endpoint: a docstring, and `Field(description=)` on new request/response models.
- New built-in plugin: `docs/_prose/plugins/<slug>.md` with the `<!-- civex:tables -->` marker, or CI fails.

`make docs` serves with live reload; `make docs-build` runs the strict build CI uses.

### Field indexes and query statistics

- **`db/field_values.field_value(entity, field_id, kind)` is the only way SQL reads a record field** (`kind` = `number` | `text` | `boolean`, from `domain/field_index.kind_of`): filters, sorts, `find_key_match` and indexes all use it, with the JSON path as a literal, because an expression index is used only when the query's expression is the indexed text. Sorts are `<value> ASC|DESC NULLS LAST` with `_tie_breakers` (`created_at, id`, in the last key's direction).
- **Managed field indexes** (`IndexService`, `ctx.index_svc`, the one decision point): a field is indexed when in a uniqueness key or chosen in `[db] indexed_fields` (config.toml, field ids; per computer, never synced). Made at runtime, not by migration (`ix_rf_<field id hex>`, `db/field_indexes.py`); `reconcile()` creates the missing, drops the stale, refreshes statistics. The server runs it on `services/index_jobs`, the CLI in the foreground. PostgreSQL builds CONCURRENTLY on an autocommit connection; SQLite builds give way to saves (`db/index_gate`). `civex db move` copies them.
- **PostgreSQL equality** is JSONB containment (`data @> {id: value}`, `ix_records_data_gin`) only when the value's JSON type is the field's (`_contains_same`); anything else stays a typed comparison. `tests/db/test_postgres_field_indexes.py` holds it.
- **Statistics** are decided in `db/statistics.py`: `ANALYZE records` after an index build and a bulk write (`after_bulk_write`), `PRAGMA optimize` on SQLite close and every 10 minutes in the server. `tests/services/test_field_indexes.py` checks plans with `EXPLAIN QUERY PLAN`.

### Metering a project (`civex.usage`)

`usage.project_usage(engine) -> Usage` is the public, read-only way for a host to measure a project (stored bytes/objects counted once per sha; `records_estimate` exact on SQLite, `reltuples` on PostgreSQL). Each measurement is its own read-only transaction under `statement_timeout`; a failure is `None`, never 0. The engine's `search_path` is honoured. Keep the signature and `Usage` fields stable (`tests/test_usage.py`).
