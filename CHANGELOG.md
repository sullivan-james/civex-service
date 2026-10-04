# Changelog

One section per tagged release: `## vX.Y.Z — <label> (YYYY-MM-DD)`. Every
`v*` tag must have a matching entry here *before* the tag is pushed —
`.github/workflows/release.yml` fails the release job if it's missing (see
PRODUCTION_READINESS.md §4a). The version itself has one source of truth,
the git tag (resolved via setuptools-scm into `civex.__version__`); this
file is release notes, not a second place to track the number.

Within a release, put breaking or migration-relevant changes under their
own `### Breaking` heading first — schema/DB migration changes (see
PRODUCTION_READINESS.md item 1) always belong there, even when handled
automatically, since that's what someone upgrading needs to scan for.

v0.0.1 through v1.0.3 were tagged and released without this discipline in
place. Rather than leave the changelog's most recent entry frozen at
v0.0.3 while nineteen undocumented tags shipped past it on PyPI, v1.0.4
below is a single retroactively-written entry consolidating everything
that shipped across that whole range — not nineteen fabricated
per-tag entries reconstructed after the fact. Discipline applies starting
from the next tag forward.

## v1.1.4 — Windows plugin fix, install checks (2026-10-04)

### Fixes

- Custom plugins failed on Windows with `did not find executable at
  ...\Temp\civex-plugin-...\Python\...\python.exe` when Python came from the
  Python install manager. Plugins run with a restricted environment that left
  out `LOCALAPPDATA`, so `uv` looked for interpreters under the plugin's
  scratch folder. That variable (and `APPDATA`, `PROGRAMDATA`, `PROGRAMFILES`,
  `WINDIR`, `COMSPEC`, `PATHEXT`, `HOMEDRIVE`/`HOMEPATH`) is now passed
  through, as are `UV_PYTHON`, `UV_PYTHON_PREFERENCE`, `UV_NATIVE_TLS`, the
  proxy variables and `SSL_CERT_FILE`. Secrets such as the database URL and
  API keys are still withheld.

### Features

- `civex doctor` now checks the installation, and works outside a project:
  - another `civex` earlier on PATH that shadows this one (it names the file
    and how to remove it),
  - required packages that are missing or at the wrong version,
  - whether `uv` is found, and whether a custom plugin's Python can start.

  Inside a project it still checks data integrity. It exits 1 only when a
  check fails outright; a shadowed copy or missing `uv` is a warning.
- `civex update` now verifies that every package civex needs is installed
  (also when already up to date) and reinstalls any that are missing, and
  warns after an upgrade if typing `civex` still runs an older copy.

## v1.1.3 — storage moves, run triage, record naming (2026-10-04)

### Breaking

- Five schema migrations run automatically on first connect, all additive:
  - `b8d2f4a61c93` adds `storage_transfers` (file moves between volumes) and
    `c5e1a8d37b42` adds its `control` column (pause/cancel).
  - `c4a9e17d5b20` adds `schemas.display_template`. Each schema's old
    `display_fields` list becomes the template joining the same fields with a
    space, so every record keeps its name.
  - `e1d5a39c7b84` adds `workflow_jobs.trigger_detail`. Runs that predate it
    simply have no recorded cause.
  - `f2a6c8d1e093` adds `audit_batches` and `audit_log.batch_id`, so a bulk
    operation is one history event. Earlier entries are unbatched.
- The `civex.load_csv` plugin is replaced by `civex.parse_table`, which reads
  any delimiter (CSV, TSV, ...) and can read several kinds in one step.
  Workflows that name `civex.load_csv` must be updated.
- Records are now named from a schema's name template instead of its starred
  `display_fields`. Old dumps still import.

### Features

- **Moving files between volumes.** Drain a volume or gather a collection's
  files onto one drive, with pause, resume, cancel and progress. Transfers
  queue and run one at a time, from the CLI (`civex store move`,
  `civex transfers ...`) or the server. Every file is verified against its
  hash before the original is removed. Settings → Storage has a Tasks tab.
- **Per-collection storage homes.** A collection can name a home volume and
  say whether to spill elsewhere or fail when it is unavailable. Content
  already stored is never duplicated.
- **Volumes are managed in Settings → Storage**: guided Add volume with a
  folder browser, a checks-before-adding step, network-drive detection, a
  page per volume, "where are my files" for every collection, and a
  per-volume clean-up. A missing drive is reported as offline with the
  reason and what to do, rather than as empty. Records show where each file
  is stored (`civex store where`).
- **Record name templates.** Name records with literal text and formatted
  values, e.g. `{site}-{taken_on:YYYY-MM}`, including one hop through a
  reference (`{ref.field}`). New schemas start with a visible template, and
  renaming or deleting a field rewrites the templates that use it.
- **Activity and retention.**
  - History is one filterable list (`/activity`, `civex history`) with
    field-level changes and where the item is now (live, deleted or gone). It
    replaces the Recently Deleted page (`civex trash list` for the CLI).
  - Bulk deletes, restores, workflow runs and browser imports each show as
    one event. A group restores only what was deleted with it, and a record
    can't be restored under a deleted collection, schema or parent.
  - Revert a record edit or create from its history entry, with a preview.
  - `[retention]` settings (Settings → Retention, `civex retention`,
    `POST /retention/run`) for deleted items, change history and runs. All
    keep forever by default, previews first, and never run by themselves.
  - Permanently deleting a record removes its audit entries and leaves one
    tombstone; `civex retention forget-purged` cleans up earlier purges.
  - Runs and reference values pointing at a deleted or purged record link to
    its history instead of a dead page.
- **Text box field type** (`longtext`): multi-line text with an optional
  `max_length`, available in the field picker, CLI and import wizard.
- **Workflow runs.**
  - An automation kill switch (stop and resume all) and per-run cancel.
  - Each run records which field change started it and the run that caused
    it.
  - Filter, sort and search runs with the records' filter; failure groups;
    re-run by filter; "completed with problems" status for runs that left
    things undone.
  - Bulk-run a workflow on selected records (`POST /workflows/{name}/run-many`).
  - A run page with Summary, Steps and Records touched tabs.
- **New menu and Add another.** Inside a record, New offers every allowed
  child schema; the new-record form gains "Add and add another".
- **Desktop shortcut.** `civex shortcut` (also in Settings → Advanced)
  creates a launcher that runs `civex serve --open`; works from WSL.
  `serve --open` opens the browser once the server answers.
- **UI.** A bottom status bar shows file moves and workflow runs; shift-click
  selects a range in every checkbox list; browser tabs are titled by
  context; explanations moved into tooltips and big pages into tabs held in
  the address; filter, sort and search for runs and history.

### Fixes

- Failure groups and bulk re-runs on a record's Runs tab are scoped to that
  record; they used to show, and could re-run, the whole project's failures.
- A workflow watching a file field no longer re-triggers itself on every save
  (derived `resolved_filename` was counted as a change).
- `civex.upsert_records`, `save_field` and `save_fields` no longer erase a
  record's other fields; they merge only what they were given.
- `civex.match_files_to_records` skips and reports files whose keys clash
  rather than silently overwriting records.
- A dead network mount no longer freezes requests; its volume shows as
  offline. `config.toml` is written atomically.
- The page-size menu now changes the size and returns to page one.
- Windows: `civex view export` leaves no open temp file, moving a SQLite
  database keeps `C:` paths intact, timed-out plugins are killed, and the
  folder browser's Up from a drive root is correct.

### Internal

- The OS-sensitive tests (storage, paths, processes, mounts, config) now run
  on Windows and macOS in a cross-platform workflow; LF line-ending rules
  added. Fixed type errors only `tsc -b` sees, and several flaky tests.

## v1.1.2 - startup and scaling reliability, geographical data types (2026-10-02)

### Features

- Web server when started would send a number of HTTP requests to the API,
  each of which would attempt to apply migrations to the datbaase schema.
  This fix does two things:
  - Run database migrations when the server is first started, not just
    when the HTTP endpoints are hit.
  - Put a lock on database migrations preventing a race condition.
- Add quick access and recent collections in the nav bar in order to facilitate
  quick access for users. Data for recent and favourits are stored in browser
  memory, not in a database.
- Add a database wide search for a Ctrl+K quick access bar. This was inspired
  by Ctrl+Shift+P functionality in VSCode.
- Add the following data types:
  - geo (for geographic types)
  - partial dates
  - float units


## v1.1.1 — collection timezones, scalable file store & queries (2026-09-30)

### Breaking
- Two schema migrations run automatically on first connect; both are
  additive, but the first backfills from existing data, so expect a pause on
  large installs:
  - `e5b81c3d7a04` adds `stored_objects` (file inventory),
    `file_references` (record/job → blob links, kept in sync by ORM events),
    `job_affected_schemas`, and indexes for the job queue, audit log, step
    analytics and record trees. Existing records and jobs are backfilled.
  - `7c2e9d4a1b58` adds a nullable `datasets.timezone`. No backfill: `NULL`
    means "unset", which is how every existing collection already behaves.
- Datetime values written through the API are now normalised to UTC. Before,
  only the CLI did this and the API stored the raw string. Offset-less values
  are read in field zone > collection zone > UTC; malformed values and times
  that a DST change skips or repeats are rejected with an error.
  `extract_from_filename` now returns offset-less datetimes (a filename
  timestamp is local wall time, not UTC), so they are localised by that same
  rule.

### Features
- **Collection and field timezones.** Collections take an optional IANA
  timezone (API, `--timezone` on the CLI, a picker in the UI; an empty value
  clears it). A datetime field can override it with a `timezone` restriction.
  The UI shows datetimes as wall time with a zone abbreviation (UTC on
  hover), edits them in the effective zone, sends UTC, and applies min/max
  bounds and view filters in that zone. The CSV import wizard says which zone
  offset-less times will be read in. Sync bundles carry the zone, and an older
  peer's bundle cannot clear a local one.
- **Editable child-record table.** The read-only child table on record pages
  is now editable in place (click, Enter or F2 to edit; Enter or blur saves,
  Esc cancels), with a draft row for creating child records. File and
  reference fields edit in a popover.
- `civex store gc --rebuild-refs` recomputes `file_references` from scratch
  if it is ever in doubt (raw SQL edits, an import that bypassed the ORM).
- Jobs can be filtered by `affected_schema`.

### Performance
- **File store.** Usage is read from the `stored_objects` inventory instead of
  walking the store on every request, and GC reconciles the inventory against
  disk so drift self-heals. Uploads (multipart is now chunked) and downloads
  (with Range support) stream instead of buffering whole files. GC checks
  bounded batches against `file_references` rather than loading every record
  and job. Dedupe hits now refresh an object's mtime, so the GC grace period
  applies to them.
- **Queries and exports.** View preview/export, collection CSV, dump and zip
  exports now sort, filter and page in SQL and write to temp files. Trash and
  job lists are paginated, and the AI count tool uses a SQL count.
- **Web UI.** Routes are lazy-loaded and heavy vendors split out (entry
  bundle 1.85 MB → 290 kB; CodeMirror, xterm and recharts load on demand).
  Idle job-count polling backs off, and stale record-picker responses are
  dropped.

### Fixes
- Purging a job that had step executions no longer fails (the bulk delete
  skipped the `step_executions` cascade).
- Accessibility: `aria-sort` now sits on column headers, and clickable table
  rows are keyboard-activatable.

### Security
- Bumped the transitive dependencies `urllib3` 2.7.0 → 2.8.0
  (CVE-2026-97687/97688/97689) and `virtualenv` 21.6.1 → 21.14.1
  (PYSEC-2026-4011..4014), plus `python-discovery`. Only `uv.lock` changes.

### Internal
- Route error boundary; colour-token migration finished with a wider
  hardcoded-colour lint; React Testing Library component tests for
  `DynamicField`, `RecordForm` and `MapStep`; `SchemaFieldsSection`
  extracted from `SchemaDetailPage`; `jsdom` pinned to `^27` so frontend tests
  run on Node 20; `tzdata` added for platforms without a system tz database.

## v1.1.0 — batteries included, `civex update` (2026-09-30)

### Breaking
- The `server`, `workflows`, `postgres`, `ai` and `telemetry` extras are now
  installed by default: a plain `pipx install civex` gives you the HTTP API
  and web UI, workflow execution and built-in plugins (pandas), the
  PostgreSQL driver, AI-assisted commands and the telemetry SDK.
  - The old extras remain as empty aliases, so `pip install "civex[server]"`
    and existing pipx installs keep resolving — no action needed.
  - Installs are larger (pandas/numpy alone add tens of MB), and
    `psycopg2-binary` is now required everywhere; on platforms without a
    prebuilt wheel it needs libpq to build.
  - `desktop` (pywebview) deliberately stays optional:
    `pipx install "civex[desktop]"`.
- New base dependencies: `packaging` and `civex-plugin-sdk` (`>=0.2.0,<0.3`).
  The SDK is now published to PyPI as its own MIT-licensed project instead of
  being vendored into the `civex` wheel; the bundled `_vendor/sdk` wheel and
  `civex_plugin_sdk` source copy are gone from the wheel. Publish the SDK
  (tag `sdk-v0.2.0`) before tagging this release — `release.yml` checks.
  - Upgrading from civex 1.0.6 or earlier: those releases shipped the SDK
    inside the civex wheel, and pip deletes the new SDK's files when it
    uninstalls the old civex. civex detects this on its first run after the
    upgrade and restores the SDK automatically (one stderr line, needs
    network access to PyPI or pip's cache). If that fails it prints the exact
    manual command: `pip install --force-reinstall --no-deps civex-plugin-sdk`.

### Features
- `civex update` upgrades an installed civex to the latest PyPI release. It
  detects pipx, `uv tool` or pip and runs the matching upgrade, refuses on
  editable dev installs, and verifies the installed version actually changed
  afterwards — pip can exit 0 while leaving the old version in place when a
  newer release's dependencies won't resolve (the v1.0.5 failure mode).
  `civex update --check` only reports.
- Records now include `reference_labels`: each reference/reference_list
  value's target `natural_name`, resolved in one batched query. The UI
  renders references as links with readable labels.
- Workflow, plugin and container-plugin editors are now routed pages
  (`/workflows/new`, `/plugins/:stem/edit`, …) instead of modals, and the
  import wizard is split into per-step components with a
  `/schemas/:id/import` entry point.

- The host now checks a plugin's wire `protocol_version` at describe time
  and refuses a mismatch with a message naming the side to upgrade, rather
  than failing opaquely mid-run. Plugins from SDKs that predate the field are
  read as version 1, so existing plugins keep working.
- CI now runs the SDK's own tests and guards that keep civex and the SDK in
  step (`scripts/check_sdk_sync.py`); the SDK has its own release workflow
  and its version comes from `sdk-v*` git tags, not from `pyproject.toml`.
  CI jobs that install the project now fetch full git history (tags).
  See `docs/contributing/sdk-release.md`.

### Fixes
- 4xx API errors are no longer retried by the UI, and a record that 404s
  stops polling, so "not found" pages render immediately instead of after
  ~7s of backoff.

## v1.0.6 — packaging fix (2026-08-16)

### Fixes
- `civex-plugin-sdk` was declared as a hard runtime dependency of `civex`
  in `pyproject.toml`, but was never published to PyPI in its own right.
  Since pip cannot resolve a nonexistent dependency, every
  `pip install civex` / `pipx install civex` since v1.0.5 shipped silently
  fell back to the last version that *did* resolve (v1.0.4) instead of
  installing the version actually requested, with no error shown. Fixed by
  bundling `civex-plugin-sdk` with `civex` itself instead of depending on it
  externally: its source is vendored directly into the `civex` wheel
  (`[tool.setuptools.packages.find]` / `[tool.setuptools.package-dir]` in
  `pyproject.toml`) for `civex`'s own imports, and a prebuilt SDK wheel now
  ships as package data at `civex/_vendor/sdk/` so subprocess-tier (Tier 1)
  plugins — which run in their own separate `uv run --no-project`
  environment per plugin — can resolve `civex-plugin-sdk` from this install
  instead of needing it on PyPI or a sibling dev checkout
  (`subprocess_runtime.py`'s `_bundled_sdk_wheel_dir()`).

### Known limitation
- This is a stopgap, not the real fix: every `civex` release now carries
  its own frozen copy of whatever SDK version was current at build time,
  rather than plugin authors being able to depend on `civex-plugin-sdk`
  independently or find it on PyPI. Publishing `civex-plugin-sdk` to PyPI
  as its own project is still separate, not-yet-done work. See
  [`docs/contributing/release.md`](contributing/release.md).

## v1.0.5 (2026-08-16)

### Breaking
- Schema and field `name`s are now slug-validated on create/rename
  (`^[a-z_][a-z0-9_]*$`); a new, optional `label` carries the free-text
  display name instead. Existing names created before this change keep
  working — `civex schema lint` reports any that don't conform.

### Features
- **Views** — save a column/filter/sort selection against a schema as a
  named view (web UI: column picker, AND/OR filter builder, live
  preview); export as CSV/JSON via the web UI or `civex view export`,
  with any file/file_list columns bundled into a zip. Columns can join
  one hop through a `reference` field (e.g. `customer.email`). A
  top-level **Views** page lists every saved view across all schemas,
  and a **Views** button on a collection's record list jumps to the
  views for whichever schema is currently filtered.
- **Analytics dashboard** — filterable, time-bucketed charts for data &
  schema growth, workflow reliability, AI usage, and the activity/audit
  trail, behind a shared URL-synced filter bar.
- **Advanced record filtering** — multi-operator, AND/OR grouped filters
  for record queries (web UI and API), plus a reusable search picker for
  reference-field and parent-record selection.
- **Soft-delete everywhere** — schemas, collections, and records now move
  to Recently Deleted instead of being removed outright, with restore and
  a typed-confirmation + blast-radius warning before cascading deletes.
- **Filename templates** — a `filename_template` restriction on
  `file`/`file_list` fields resolves a per-record download name from
  other field values; reflected in the record API's `resolved_filename`,
  single-file downloads, and bulk zip export.
- **Guided import wizard** — import a folder of files or a spreadsheet
  into a collection through a step-by-step wizard.
- **Change history everywhere** — schema and record detail pages show a
  collapsible change history; the audit log is also exposed via HTTP API.
- **Tier 2 container plugins** — `docker run` execution with memory/CPU
  limits and a timeout/kill wrapper, plus starter Dockerfiles + language
  shims for Go, Python, Rust, R, Java, and C/C++.
- Workflow YAML editor now autocompletes plugin ids, config keys, and
  step output references.
- Navigation restructured around researcher tasks (Collections, Views,
  Schemas, Workflows, Runs, Analytics) instead of raw database tables;
  Runs rebuilt as a readable audit trail.

### Other
- Internal data-model hardening, applied automatically via Alembic on
  upgrade: composite FK enforcing record parent/dataset consistency,
  normalized `workflow_jobs.step_executions`, referential integrity for
  `display_field`, and a `search_vector` trigger fix.
- Dark mode via token overrides; hardcoded color literals swept from the
  frontend and lint-blocked going forward.
- Broad frontend UI-primitive consolidation (Page template, Field/Input/
  Select/Checkbox, ConfirmDialog, Modal, Toast, IconButton, DataTable)
  applied across every route, plus aria-live regions and dialog semantics
  for sync/job/empty states and panels.

### Installation
See [README.md](README.md) for `pipx` install instructions.

## v1.0.4 (2026-07-16)

Consolidated summary of everything shipped since the original v0.0.3
alpha release (see `git log v0.0.3..v1.0.4` for the raw commit history).
Despite the version number, this is still an alpha release — see
PRODUCTION_READINESS.md for what's blocking a real 1.0.

### Breaking
- `civex dataset` CLI command renamed to `civex collection` (underlying
  service/module names are unchanged; update any scripts that call
  `civex dataset ...` directly).
- License changed from the original "Civex Freeware License" to a new
  "Civex Software License Agreement" — review terms before upgrading.

### Features
- **AI assistant** — `civex ai` configures a provider (Anthropic, Groq,
  Gemini, Ollama, or any OpenAI-compatible endpoint); a chat panel in the
  web UI can inspect and act on schemas/datasets/records via tool calls.
- **Desktop app** — `civex-desktop` packages civex as a native tray
  application (PyInstaller, cross-platform builds attached to GitHub
  releases), with open/recent-project UI and local file logging.
- **Database migrations** — Alembic-managed schema migrations
  (`src/civex/db/migrations/`), applied automatically on connect;
  `civex db current` / `civex db migrate` for manual control.
- **Structured logging & telemetry** — structlog-based JSON logging with
  secret redaction, and opt-in Sentry error telemetry.
- **Local server hardening** — `LocalGuardMiddleware` adds DNS-rebinding
  and CSRF defenses to the loopback-only dev server.
- **CivexHub remote sync** — SSH transport, multi-volume support, and UI
  parity for pushing/pulling to a bare civex repository. (CivexHub was
  later split out of this repo entirely — see CIVEX-13 — so this is the
  last entry here that touches it.)

### Fixes
- Creating a schema with a duplicate name no longer fails incorrectly.
- Plugin/workflow restore silently returning 0 on Windows.
- Various remote sync fixes.
- Terminal router now guarded behind a Unix platform check (it didn't
  work on Windows).
- Frontend build reliability in CI (esbuild `ETXTBSY` on Linux, a
  cross-platform shell for the build step).

### Other
- Expanded automated test suite (~32% coverage, CI-gated at 30% — see
  `docs/contributing/testing.md`).

### Installation
See [README.md](README.md) for `pipx` install instructions.
